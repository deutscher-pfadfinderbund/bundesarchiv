"""The push to the system of record (ADR 0020) against the real WebDAV adapter, on the session's
in-process WsgiDAV server: the mirror logic speaks only the port, so the same code must hold when
the system of record is a live ``WebDavObjectStore``. A live Nextcloud run is the conformance
suite's opt-in probe (``docs/nextcloud-webdav-notes.md``)."""

import io
from urllib.parse import urlsplit

import httpx2

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.mirror import push, reconcile
from bundesarchiv.app.push_record import InMemoryPushRecord
from bundesarchiv.domain.models import Article
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore


def test_push_sends_an_article_with_its_media_to_a_live_webdav_store(
    webdav_store: WebDavObjectStore,
) -> None:
    archive = Archive.of(InMemoryObjectStore())
    scan = archive.articles.add_media("01A", "Brief 100% ü.pdf", io.BytesIO(b"x" * 3_000_007))
    archive.articles.save(Article("01A", "Brief", "FOTOS", media=(scan,)), 0, changed_by="tester")
    archive.articles.save(Article("01A", "Brief", "FOTOS", media=(scan,)), 1, changed_by="tester")

    push(archive, webdav_store, InMemoryPushRecord(), "01A")

    local = {key: archive.store.read(key) for key in archive.store.list()}
    assert {key: webdav_store.read(key) for key in webdav_store.list()} == local


def test_reconcile_against_a_live_webdav_store_adds_and_deletes_nothing(
    webdav_store: WebDavObjectStore,
) -> None:
    archive = Archive.of(InMemoryObjectStore())
    archive.articles.save(Article("01A", "Brief", "FOTOS"), 0, changed_by="tester")
    webdav_store.write_atomic("articles/01OLD/README.md", b"orphan")

    report = reconcile(archive, webdav_store, InMemoryPushRecord())

    (readme,) = (key.key for key in archive.articles.keys_for("01A"))
    assert webdav_store.read(readme) == archive.store.read(readme)
    assert webdav_store.read("articles/01OLD/README.md") == b"orphan"
    assert (report.sent, report.remote_only) == ((readme,), ("articles/01OLD/README.md",))


def test_a_save_pushes_its_new_history_file_and_readme_in_one_request_each(
    webdav_root: str,
) -> None:
    """ADR 0020 push order on the wire, and each media file's bytes sent once."""
    sent: list[tuple[str, str]] = []
    client = httpx2.Client(
        base_url=webdav_root,
        timeout=10,
        event_hooks={"request": [lambda request: sent.append((request.method, request.url.path))]},
    )
    remote, record = WebDavObjectStore(client), InMemoryPushRecord()
    archive = Archive.of(InMemoryObjectStore())
    scan = archive.articles.add_media("01A", "Brief 100% ü.pdf", io.BytesIO(b"x" * 3_000_007))
    for version in (0, 1):
        archive.articles.save(
            Article("01A", "Brief", "FOTOS", media=(scan,)), version, changed_by="tester"
        )
    push(archive, remote, record, "01A")
    archive.articles.save(Article("01A", "Neu", "FOTOS", media=(scan,)), 2, changed_by="tester")
    first = len(sent)
    try:
        push(archive, remote, record, "01A")
    finally:
        client.close()

    root = urlsplit(webdav_root).path
    media, _, history, readme = (root + key.key for key in archive.articles.keys_for("01A"))
    assert sent[:first].count(("PUT", media)) == 1
    assert sent[first:] == [("PUT", history), ("PUT", readme)]
