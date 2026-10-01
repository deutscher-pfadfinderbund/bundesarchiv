"""WebDavObjectStore-specific tests: behavior the shared conformance suite (run
against a healthy server) cannot reach — a down/unreachable mirror surfaces as
ArchiveError, not a raw httpx2 exception, and refusals under contention are retried
before `Busy` reaches the caller.
"""

import io
import socket
from urllib.parse import urlsplit

import httpx2
import pytest

from bundesarchiv.persistence.adapters import webdav
from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore
from bundesarchiv.persistence.errors import ArchiveError, Busy, NotFound


def test_transport_failure_surfaces_as_archive_error() -> None:
    # Port 9 (discard) is closed on a dev/CI host → real connection refused. A short
    # timeout keeps a filtered port from hanging (a timeout is also a TransportError).
    client = httpx2.Client(base_url="http://127.0.0.1:9/", timeout=1.0)
    store = WebDavObjectStore(client)
    operations = (
        lambda: store.read("k"),
        lambda: store.write_atomic("k", b"x"),
        lambda: store.put_large("k", io.BytesIO(b"data"), 4),
        lambda: store.create("k", b"x"),
        lambda: store.exists("k"),
        lambda: store.delete("k"),
        lambda: store.delete_prefix("a/b"),
        lambda: store.list(),
    )
    try:
        for operation in operations:
            with pytest.raises(ArchiveError):
                operation()
    finally:
        client.close()


def test_non_transport_httpx_error_surfaces_as_archive_error() -> None:
    # _request must contain ANY httpx2 error, not only TransportError. MockTransport is a real
    # httpx2 boundary (not a mock of the adapter), letting us raise a non-transport httpx2 error.
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.HTTPError("simulated non-transport failure")

    client = httpx2.Client(base_url="http://example.invalid/", transport=httpx2.MockTransport(boom))
    store = WebDavObjectStore(client)
    try:
        with pytest.raises(ArchiveError):
            store.exists("k")
    finally:
        client.close()


def test_malformed_multistatus_body_surfaces_as_archive_error() -> None:
    # A misbehaving mirror returning non-XML must not leak a raw xml.etree ParseError.
    from bundesarchiv.persistence.adapters.webdav import _parse_multistatus

    with pytest.raises(ArchiveError):
        list(_parse_multistatus(b"<not-valid-xml"))


def test_the_test_server_never_serves_an_unread_body_as_a_request(webdav_root: str) -> None:
    # A refused create is answered before its body is read. A real server then reads the rest
    # or closes; the in-process one parsing it as the next request made later writes flake.
    root = urlsplit(webdav_root)
    httpx2.put(f"{webdav_root}taken", content=b"x").raise_for_status()
    refused_create = (
        f"PUT {root.path}taken HTTP/1.1\r\nHost: {root.netloc}\r\nIf-None-Match: *\r\n"
        "Transfer-Encoding: chunked\r\n\r\n6\r\nsecond\r\n0\r\n\r\n"
    )
    with socket.create_connection((root.hostname, root.port), timeout=5) as sock:
        sock.sendall(refused_create.encode())
        reply = b"".join(iter(lambda: sock.recv(65536), b""))
    status, _, rest = reply.partition(b"\r\n")
    assert status == b"HTTP/1.1 412 Precondition Failed"
    assert b"HTTP/1.1 " not in rest, reply


@pytest.fixture
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webdav, "_RETRY_DELAYS", (0.0,) * len(webdav._RETRY_DELAYS))


def _scripted_store(refusals: list[int]) -> tuple[WebDavObjectStore, list[bytes]]:
    """A store whose server refuses the first PUTs with `refusals`, then accepts; returns the
    store and the body of every PUT it received. MockTransport is the real httpx2 boundary."""
    bodies: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method != "PUT":
            return httpx2.Response(201)  # MKCOL
        bodies.append(request.read())
        status = refusals.pop(0) if refusals else 201
        return httpx2.Response(status, headers={"ETag": '"v"'} if status == 201 else None)

    client = httpx2.Client(base_url="http://dav.invalid/", transport=httpx2.MockTransport(handler))
    return WebDavObjectStore(client), bodies


@pytest.mark.usefixtures("no_retry_wait")
@pytest.mark.parametrize("refusal", [423, 404])
def test_a_refused_write_is_retried_until_it_lands(refusal: int) -> None:
    # 423 is Nextcloud's lock; 404 the transient answer right after creating a parent.
    store, bodies = _scripted_store([refusal, refusal])
    store.write_atomic("articles/01J0/README.md", b"data")
    assert bodies == [b"data"] * 3


@pytest.mark.usefixtures("no_retry_wait")
def test_a_retried_streamed_write_resends_the_stream_from_where_it_stood() -> None:
    store, bodies = _scripted_store([423])
    data = b"x" * (3 * 1024 * 1024 + 7)
    stream = io.BytesIO(b"hdr" + data)
    stream.seek(3)
    store.put_large("articles/01J0/media/scan.pdf", stream, len(data))
    assert bodies == [data, data]


class _Unseekable(io.BytesIO):
    def seekable(self) -> bool:
        return False


@pytest.mark.usefixtures("no_retry_wait")
def test_a_stream_that_cannot_rewind_gets_one_attempt() -> None:
    store, bodies = _scripted_store([423])
    with pytest.raises(Busy):
        store.put_large("articles/01J0/media/scan.pdf", _Unseekable(b"data"), 4)
    assert bodies == [b"data"]


@pytest.mark.usefixtures("no_retry_wait")
@pytest.mark.parametrize(("refusal", "busy"), [(423, True), (404, False), (409, False)])
def test_spent_retries_raise_busy_only_for_contention(refusal: int, busy: bool) -> None:
    # A 404/409 that outlasts the retries is a missing root or a file in the way, not contention.
    # Each attempt answered so makes the parents and sends the body again.
    puts = (len(webdav._RETRY_DELAYS) + 1) * (1 if busy else 2)
    store, bodies = _scripted_store([refusal] * puts)
    with pytest.raises(ArchiveError) as refused:
        store.write_atomic("articles/01J0/README.md", b"data")
    assert (isinstance(refused.value, Busy), len(bodies)) == (busy, puts)


def test_a_collection_answered_like_a_file_is_not_found() -> None:
    # Nextcloud answers a GET of a folder with 200, an HTML placeholder and no ETag
    # (measured 2026-09-25); only PROPFIND tells it from a blob.
    collection = (
        b'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:href>/art/1/</d:href>'
        b"<d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop>"
        b"<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "PROPFIND":
            return httpx2.Response(207, content=collection)
        return httpx2.Response(200, content=b"This is the WebDAV interface.")

    client = httpx2.Client(base_url="http://dav.invalid/", transport=httpx2.MockTransport(handler))
    store = WebDavObjectStore(client)
    with pytest.raises(NotFound):
        pytest.fail(f"read returned {store.read('art/1')!r}")


def _root_size_store(body: bytes) -> WebDavObjectStore:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert (request.method, request.headers["Depth"]) == ("PROPFIND", "0")
        return httpx2.Response(207, content=body)

    client = httpx2.Client(base_url="http://dav.invalid/", transport=httpx2.MockTransport(handler))
    return WebDavObjectStore(client)


def test_root_size_reads_the_nextcloud_recursive_size() -> None:
    body = (
        b'<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:response>'
        b"<d:href>/</d:href><d:propstat><d:prop><oc:size>5300000000</oc:size></d:prop>"
        b"</d:propstat></d:response></d:multistatus>"
    )
    assert _root_size_store(body).root_size() == 5_300_000_000


def test_root_size_is_none_when_the_server_does_not_say() -> None:
    body = (
        b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/</d:href></d:response></d:multistatus>'
    )
    assert _root_size_store(body).root_size() is None
