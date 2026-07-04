"""Task 4.9 — mirror replay + reconcile against the REAL WebDAV adapter (not just the in-memory
double). The mirror is just another ``ObjectStore``, so the same ``push_key`` / ``reconcile`` logic
must work when the mirror is a live ``WebDavObjectStore`` on the session's in-process WsgiDAV server
(the Part 1 conformance harness — no mocking, real HTTP/WebDAV). This is the proof that the port
seam holds for the actual mirror backend; a live Nextcloud smoke is a Part 6 runbook item.
"""

from bundesarchiv.app.mirror import push_key, reconcile
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore


def test_push_key_replays_to_live_webdav_mirror(webdav_store: WebDavObjectStore) -> None:
    canonical = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"body")

    push_key(canonical, webdav_store, "articles/01A/README.md")

    assert webdav_store.read("articles/01A/README.md") == b"body"


def test_push_key_deletes_from_live_webdav_when_gone_from_canonical(
    webdav_store: WebDavObjectStore,
) -> None:
    canonical = InMemoryObjectStore()  # key absent from canonical
    webdav_store.write_atomic("articles/01A/README.md", b"leftover")

    push_key(canonical, webdav_store, "articles/01A/README.md")

    assert not webdav_store.exists("articles/01A/README.md")


def test_reconcile_against_live_webdav_pushes_and_deletes(webdav_store: WebDavObjectStore) -> None:
    """Full sweep against a real WebDAV mirror: a missing key is pushed, a mirror-only key is
    deleted, and the summary counts are right."""
    canonical = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"a")
    webdav_store.write_atomic("articles/01OLD/README.md", b"orphan")

    summary = reconcile(canonical, webdav_store)

    assert webdav_store.read("articles/01A/README.md") == b"a"
    assert not webdav_store.exists("articles/01OLD/README.md")
    assert (summary.pushed, summary.deleted, summary.failed) == (1, 1, 0)
