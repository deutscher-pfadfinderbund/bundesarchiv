"""Task 4.9 — the WebDAV mirror replay + reconcile LOGIC (``bundesarchiv.app.mirror``).

The mirror is a CONVENIENCE browse copy: never a read path, never counted as durability (restic is
the backup). These tests exercise the pure two-argument functions — ``push_key(canonical, mirror,
key)`` and ``reconcile(canonical, mirror)`` — against two ``InMemoryObjectStore``s standing in for
the canonical store and the mirror (the port IS the seam: a mirror is just another ObjectStore, so
no live WebDAV is needed here). Reference semantics: a job carries only a key, and execution
re-reads canonical truth, so a key GONE from canonical by execution time is DELETED from the mirror
(the mirror mirrors; it does not accumulate).
"""

from bundesarchiv.app.mirror import ReconcileSummary, push_key, reconcile
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore


def _stores() -> tuple[InMemoryObjectStore, InMemoryObjectStore]:
    return InMemoryObjectStore(), InMemoryObjectStore()


# --- push_key: reference replay of a single key ----------------------------------


def test_push_key_copies_new_key_to_mirror() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"body")

    push_key(canonical, mirror, "articles/01A/README.md")

    assert mirror.read("articles/01A/README.md") == b"body"


def test_push_key_overwrites_changed_key() -> None:
    canonical, mirror = _stores()
    mirror.write_atomic("articles/01A/README.md", b"stale")
    canonical.write_atomic("articles/01A/README.md", b"fresh")

    push_key(canonical, mirror, "articles/01A/README.md")

    assert mirror.read("articles/01A/README.md") == b"fresh"


def test_push_key_is_idempotent() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"body")

    push_key(canonical, mirror, "articles/01A/README.md")
    push_key(canonical, mirror, "articles/01A/README.md")

    assert mirror.read("articles/01A/README.md") == b"body"


def test_push_key_deletes_from_mirror_when_key_gone_from_canonical() -> None:
    """Reference semantics: a stale push job whose key was deleted from canonical by execution time
    must DELETE it from the mirror, not resurrect it — current canonical truth wins."""
    canonical, mirror = _stores()
    mirror.write_atomic("articles/01A/README.md", b"leftover")  # canonical has NOTHING at this key

    push_key(canonical, mirror, "articles/01A/README.md")

    assert not mirror.exists("articles/01A/README.md")


def test_push_key_delete_of_absent_mirror_key_is_a_noop() -> None:
    canonical, mirror = _stores()  # gone from canonical AND never on the mirror

    push_key(canonical, mirror, "articles/01A/README.md")  # must not raise

    assert not mirror.exists("articles/01A/README.md")


# --- reconcile: full diff, push missing/changed, delete mirror-only --------------


def test_reconcile_pushes_missing_keys() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"a")
    canonical.write_atomic("articles/01B/README.md", b"b")

    summary = reconcile(canonical, mirror)

    assert mirror.read("articles/01A/README.md") == b"a"
    assert mirror.read("articles/01B/README.md") == b"b"
    assert summary.pushed == 2
    assert summary.deleted == 0
    assert summary.failed == 0


def test_reconcile_repushes_changed_keys() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"fresh")
    mirror.write_atomic("articles/01A/README.md", b"stale")  # same key, different bytes

    summary = reconcile(canonical, mirror)

    assert mirror.read("articles/01A/README.md") == b"fresh"
    assert summary.pushed == 1  # changed key counts as a push


def test_reconcile_skips_unchanged_keys() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"same")
    mirror.write_atomic("articles/01A/README.md", b"same")

    summary = reconcile(canonical, mirror)

    assert summary.pushed == 0  # identical bytes: nothing re-pushed
    assert summary.deleted == 0


def test_reconcile_deletes_mirror_only_keys() -> None:
    """The mirror MIRRORS — it does not accumulate. A key present on the mirror but absent from
    canonical is stale and must be deleted."""
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"keep")
    mirror.write_atomic("articles/01A/README.md", b"keep")
    mirror.write_atomic("articles/01OLD/README.md", b"deleted-from-canonical")

    summary = reconcile(canonical, mirror)

    assert not mirror.exists("articles/01OLD/README.md")  # stale mirror-only key removed
    assert mirror.exists("articles/01A/README.md")  # still-canonical key kept
    assert summary.deleted == 1


def test_reconcile_empty_canonical_clears_mirror() -> None:
    canonical, mirror = _stores()
    mirror.write_atomic("articles/01OLD/README.md", b"orphan")

    summary = reconcile(canonical, mirror)

    assert list(mirror.list()) == []
    assert summary.deleted == 1
    assert summary.pushed == 0


def test_reconcile_summary_is_the_result_shape() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"a")
    mirror.write_atomic("articles/01OLD/README.md", b"orphan")

    summary = reconcile(canonical, mirror)

    assert isinstance(summary, ReconcileSummary)
    assert (summary.pushed, summary.deleted, summary.failed) == (1, 1, 0)
