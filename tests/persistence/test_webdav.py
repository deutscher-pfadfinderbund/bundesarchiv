"""WebDavObjectStore-specific tests: behavior the shared conformance suite (run
against a healthy server) cannot reach — chiefly that a down/unreachable mirror
surfaces as ArchiveError, not a raw httpx transport exception, past the port.

No mocking: the client really tries to connect to a refused port.
"""

import io

import httpx
import pytest

from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore
from bundesarchiv.persistence.errors import ArchiveError, NotFound


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
