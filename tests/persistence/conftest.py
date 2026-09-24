"""Shared persistence-test fixtures.

One real, in-process WebDAV server (wsgidav on cheroot, ephemeral localhost port) is
brought up ONCE per session; each test gets an isolated collection on it. Nothing is
mocked — the adapter speaks real HTTP/WebDAV to a real server, exactly as the local-FS
adapter speaks to a real filesystem. Sharing the server (vs one per test) keeps the
suite fast even though many parametrized cases request a WebDAV store.

Where stock wsgidav is weaker than the Nextcloud the adapter targets, the server is
brought up to the measured Nextcloud behaviour (`docs/nextcloud-webdav-notes.md`), so a
green run means the adapter is right, not that wsgidav is lenient: a `PUT` replaces a
file in one rename (stock wsgidav truncates and writes in place).
"""

import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

import httpx
import pytest
from cheroot.wsgi import Server as CherootServer
from wsgidav.fs_dav_provider import FileResource, FilesystemProvider
from wsgidav.wsgidav_app import WsgiDAVApp

from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore


class _AtomicFile(FileResource):  # type: ignore[misc]
    """A file whose `PUT` body lands in a scratch file that then replaces it in one rename."""

    def __init__(self, path: str, environ: dict[str, Any], file_path: str, scratch: Path) -> None:
        super().__init__(path, environ, file_path)
        self._scratch = scratch / uuid.uuid4().hex

    def begin_write(self, *, content_type: str | None = None) -> BinaryIO:
        return self._scratch.open("wb")

    def end_write(self, *, with_errors: bool) -> None:
        if with_errors:
            self._scratch.unlink()
        else:
            self._scratch.replace(self._file_path)


class _NextcloudLikeProvider(FilesystemProvider):  # type: ignore[misc]
    def __init__(self, root: Path, scratch: Path) -> None:
        super().__init__(str(root), readonly=False)
        self._scratch = scratch

    def get_resource_inst(self, path: str, environ: dict[str, Any]) -> Any:
        resource = super().get_resource_inst(path, environ)
        if isinstance(resource, FileResource):
            return _AtomicFile(path, environ, resource._file_path, self._scratch)
        return resource


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
    server = CherootServer(("127.0.0.1", 0), WsgiDAVApp(config))
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
