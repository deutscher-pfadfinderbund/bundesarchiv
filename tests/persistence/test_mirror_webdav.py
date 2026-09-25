"""The push to the system of record (ADR 0020) against the real WebDAV adapter, on the session's
in-process WsgiDAV server: the mirror logic speaks only the port, so the same code must hold when
the system of record is a live ``WebDavObjectStore``. A live Nextcloud run is the conformance
suite's opt-in probe (``docs/nextcloud-webdav-notes.md``)."""

import io

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
