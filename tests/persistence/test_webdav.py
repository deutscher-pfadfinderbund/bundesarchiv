"""WebDavObjectStore-specific tests: behavior the shared conformance suite (run
against a healthy server) cannot reach — a down/unreachable mirror surfaces as
ArchiveError, not a raw httpx exception, and refusals under contention are retried
before `Busy` reaches the caller.
"""

import io

import httpx
import pytest

from bundesarchiv.persistence.adapters import webdav
from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore
from bundesarchiv.persistence.errors import ArchiveError, Busy, NotFound


def test_transport_failure_surfaces_as_archive_error() -> None:
    # Port 9 (discard) is closed on a dev/CI host → real connection refused. A short
    # timeout keeps a filtered port from hanging (a timeout is also a TransportError).
    client = httpx.Client(base_url="http://127.0.0.1:9/", timeout=1.0)
    store = WebDavObjectStore(client)
    operations = (
        lambda: store.read("k"),
        lambda: store.write_atomic("k", b"x"),
        lambda: store.put_large("k", io.BytesIO(b"data"), 4),
        lambda: store.exists("k"),
        lambda: store.delete("k"),
        lambda: store.list(),
    )
    try:
        for operation in operations:
            with pytest.raises(ArchiveError):
                operation()
    finally:
        client.close()


def test_non_transport_httpx_error_surfaces_as_archive_error() -> None:
    # _request must contain ANY httpx error, not only TransportError. MockTransport is a real
    # httpx boundary (not a mock of the adapter), letting us raise a non-transport httpx error.
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.HTTPError("simulated non-transport failure")

    client = httpx.Client(base_url="http://example.invalid/", transport=httpx.MockTransport(boom))
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


@pytest.fixture
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webdav, "_RETRY_DELAYS", (0.0,) * len(webdav._RETRY_DELAYS))


def _scripted_store(refusals: list[int]) -> tuple[WebDavObjectStore, list[bytes]]:
    """A store whose server refuses the first PUTs with `refusals`, then accepts; returns the
    store and the body of every PUT it received. MockTransport is the real httpx boundary."""
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "PUT":
            return httpx.Response(201)  # MKCOL
        bodies.append(request.read())
        status = refusals.pop(0) if refusals else 201
        return httpx.Response(status, headers={"ETag": '"v"'} if status == 201 else None)

    client = httpx.Client(base_url="http://dav.invalid/", transport=httpx.MockTransport(handler))
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
    attempts = len(webdav._RETRY_DELAYS) + 1
    store, bodies = _scripted_store([refusal] * attempts)
    with pytest.raises(ArchiveError) as refused:
        store.write_atomic("articles/01J0/README.md", b"data")
    assert (isinstance(refused.value, Busy), len(bodies)) == (busy, attempts)


def test_read_of_collection_key_is_not_found_under_redirect_following(webdav_root: str) -> None:
    # read() must not depend on the injected client's redirect policy. With
    # follow_redirects=True a naive GET would chase the collection's 301 and return
    # the server's HTML listing as blob bytes; the adapter must still raise NotFound.
    client = httpx.Client(base_url=webdav_root, timeout=10, follow_redirects=True)
    store = WebDavObjectStore(client)
    try:
        store.write_atomic("art/1/README.md", b"body")
        with pytest.raises(NotFound):
            store.read("art/1")
    finally:
        client.close()
