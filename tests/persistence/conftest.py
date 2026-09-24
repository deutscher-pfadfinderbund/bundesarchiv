"""Shared persistence-test fixtures.

One real, in-process WebDAV server (wsgidav on cheroot, ephemeral localhost port) is
brought up ONCE per session; each test gets an isolated collection on it. Nothing is
mocked — the adapter speaks real HTTP/WebDAV to a real server, exactly as the local-FS
adapter speaks to a real filesystem. Sharing the server (vs one per test) keeps the
suite fast even though many parametrized cases request a WebDAV store.

The server is brought up to the backend semantics the adapter relies on
(`docs/nextcloud-webdav-notes.md`), so a green run means the adapter maps them right, not
that wsgidav is lenient: a `PUT` places a file in one rename, as measured on Nextcloud
(stock wsgidav writes in place, and first puts an empty file at a new key), and requests
that change the tree run one at a time, so a `PUT` with `If-None-Match: *` is atomic (stock
wsgidav checks it and writes without a lock, so two creates could both win). Whether a real
server gives the same is what the live run checks.

`live_dav_store` points the same conformance suite at a real WebDAV server: the
opt-in live run (`docs/nextcloud-webdav-notes.md`, "Probes").
"""

import contextlib
import os
import threading
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, BinaryIO
from wsgiref.types import StartResponse, WSGIApplication, WSGIEnvironment

import httpx
import pytest
from cheroot.server import HTTPConnection, HTTPRequest
from cheroot.wsgi import Server as CherootServer
from wsgidav import util
from wsgidav.dav_provider import DAVNonCollection
from wsgidav.fs_dav_provider import FileResource, FilesystemProvider, FolderResource
from wsgidav.wsgidav_app import WsgiDAVApp

from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore


class _AtomicFile(FileResource):  # type: ignore[misc]
    """A file whose `PUT` body lands in a scratch file that then takes its place in one rename,
    whether it replaces the file or creates it: until then the path shows the old file or
    none, and a failed `PUT` leaves nothing."""

    def __init__(self, path: str, environ: dict[str, Any], file_path: str, scratch: Path) -> None:
        # Not FileResource.__init__: it stats a file that a create has not placed yet.
        DAVNonCollection.__init__(self, path, environ)
        self._file_path = file_path
        self._scratch = scratch / uuid.uuid4().hex
        with contextlib.suppress(FileNotFoundError):
            self.file_stat = Path(file_path).stat()

    def begin_write(self, *, content_type: str | None = None) -> BinaryIO:
        return self._scratch.open("wb")

    def end_write(self, *, with_errors: bool) -> None:
        if with_errors:
            self._scratch.unlink(missing_ok=True)
        else:
            self._scratch.replace(self._file_path)


class _Folder(FolderResource):  # type: ignore[misc]
    def __init__(self, path: str, environ: dict[str, Any], file_path: str, scratch: Path) -> None:
        super().__init__(path, environ, file_path)
        self._scratch = scratch

    def create_empty_resource(self, name: Any) -> Any:
        # Stock wsgidav puts an empty file at the final path first; this places nothing yet.
        path = util.join_uri(self.path, name)
        return _AtomicFile(path, self.environ, str(Path(self._file_path, name)), self._scratch)


class _NextcloudLikeProvider(FilesystemProvider):  # type: ignore[misc]
    def __init__(self, root: Path, scratch: Path) -> None:
        super().__init__(str(root), readonly=False, fs_opts={})
        self._scratch = scratch

    def get_resource_inst(self, path: str, environ: dict[str, Any]) -> Any:
        resource = super().get_resource_inst(path, environ)
        if isinstance(resource, FileResource):
            return _AtomicFile(path, environ, resource._file_path, self._scratch)
        if isinstance(resource, FolderResource):
            return _Folder(path, environ, resource._file_path, self._scratch)
        return resource


def _one_change_at_a_time(app: WSGIApplication) -> WSGIApplication:
    lock = threading.Lock()

    def serialized(environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        if environ["REQUEST_METHOD"] in ("GET", "HEAD", "PROPFIND", "OPTIONS"):
            return app(environ, start_response)
        with lock:
            return list(app(environ, start_response))

    return serialized


class _Request(HTTPRequest):
    def send_headers(self) -> None:
        # cheroot drains a sized body the app left unread, but not a chunked one, which it
        # would then parse as the next request: close the connection instead.
        if self.chunked_read and not self.rfile.closed:
            self.close_connection = True
        super().send_headers()


class _Connection(HTTPConnection):
    RequestHandlerClass = _Request

    def close(self) -> None:
        # cheroot never closes the writer: a reply to a client that hung up would flush at GC.
        with contextlib.suppress(OSError):
            self.wfile.close()
        super().close()


@pytest.fixture(scope="session")
def webdav_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A real WebDAV server for the whole session; yields its base URL."""
    backing = tmp_path_factory.mktemp("dav")
    scratch = tmp_path_factory.mktemp("dav-scratch")
    provider = _NextcloudLikeProvider(backing, scratch)
    config: dict[str, object] = {
        "provider_mapping": {"/": provider},
        "simple_dc": {"user_mapping": {"*": True}},  # anonymous, read/write
        "verbose": 0,
        "logging": {"enable": False},
    }
    app = _one_change_at_a_time(WsgiDAVApp(config))
    server = CherootServer(("127.0.0.1", 0), app, numthreads=16, request_queue_size=64)
    server.ConnectionClass = _Connection
    server.prepare()  # binds + listens synchronously before the serving thread starts
    port = server.bind_addr[1]
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.stop()
        thread.join(timeout=5)


@pytest.fixture
def webdav_root(webdav_server: str) -> str:
    """A fresh, isolated collection on the shared server for one test; yields its URL."""
    base = f"{webdav_server}{uuid.uuid4().hex}/"
    with httpx.Client(timeout=10) as setup:
        setup.request("MKCOL", base).raise_for_status()  # fail loudly if setup didn't create it
    return base


@pytest.fixture
def webdav_store(webdav_root: str) -> Iterator[WebDavObjectStore]:
    client = httpx.Client(base_url=webdav_root, timeout=10)
    try:
        yield WebDavObjectStore(client)
    finally:
        client.close()


@pytest.fixture(scope="session")
def live_dav_root() -> Iterator[str]:
    """A throwaway folder directly under `LIVE_DAV_URL`, removed with everything in it at the
    end of the session. Nothing else on the server is touched."""
    root = os.environ["LIVE_DAV_URL"].rstrip("/")
    assert "Bundesarchiv" not in root, "the live run never writes inside the system of record"
    folder = f"{root}/bundesarchiv-conformance-{uuid.uuid4().hex}/"
    with httpx.Client(auth=_live_auth(), timeout=60) as client:
        client.request("MKCOL", folder).raise_for_status()
        try:
            yield folder
        finally:
            client.request("DELETE", folder).raise_for_status()


@pytest.fixture
def live_dav_store(live_dav_root: str) -> Iterator[WebDavObjectStore]:
    base = f"{live_dav_root}{uuid.uuid4().hex}/"
    client = httpx.Client(base_url=base, auth=_live_auth(), timeout=60)
    try:
        client.request("MKCOL", "").raise_for_status()
        yield WebDavObjectStore(client)
    finally:
        client.close()


def _live_auth() -> tuple[str, str]:
    return os.environ["DAV_USER"], os.environ["DAV_PASSWORD"]
