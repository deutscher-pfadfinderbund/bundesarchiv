"""Shared persistence-test fixtures.

`webdav_store` brings up a real, in-process WebDAV server (wsgidav served on cheroot,
bound to an ephemeral localhost port) and yields a WebDavObjectStore pointed at it.
Nothing is mocked — the adapter speaks real HTTP/WebDAV to a real server, exactly as
the local-FS adapter speaks to a real filesystem.
"""

import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from cheroot.wsgi import Server as CherootServer
from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.wsgidav_app import WsgiDAVApp

from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore


@pytest.fixture
def webdav_server(tmp_path: Path) -> Iterator[str]:
    """A real WebDAV server bound to an ephemeral port; yields its base URL."""
    backing = tmp_path / "dav"
    backing.mkdir()
    config: dict[str, object] = {
        "provider_mapping": {"/": FilesystemProvider(str(backing), readonly=False)},
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
def webdav_store(webdav_server: str) -> Iterator[WebDavObjectStore]:
    client = httpx.Client(base_url=webdav_server, timeout=10)
    try:
        yield WebDavObjectStore(client)
    finally:
        client.close()
