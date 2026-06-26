"""Shared persistence-test fixtures.

One real, in-process WebDAV server (wsgidav on cheroot, ephemeral localhost port) is
brought up ONCE per session; each test gets an isolated collection on it. Nothing is
mocked — the adapter speaks real HTTP/WebDAV to a real server, exactly as the local-FS
adapter speaks to a real filesystem. Sharing the server (vs one per test) keeps the
suite fast even though many parametrized cases request a WebDAV store.
"""

import threading
import uuid
from collections.abc import Iterator

import httpx
import pytest
from cheroot.wsgi import Server as CherootServer
from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.wsgidav_app import WsgiDAVApp

from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore


@pytest.fixture(scope="session")
def webdav_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A real WebDAV server for the whole session; yields its base URL."""
    backing = tmp_path_factory.mktemp("dav")
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
