"""Web-subtree test wiring: the shared corpus fixtures + the genuine external service seams.

The ``corpus`` / ``make_corpus`` fixtures hand out ``_fixtures.Corpus`` with
``override_settings(**settings_for(...))`` already entered, so a web test neither builds the store
wiring nor wraps its request in a settings block.

The Part 4.7 cataloging views drive the REAL write path — ``create_article`` / ``save_article`` /
``hard_delete_article`` — which exercises the repository, the README round-trip, and the ADR-0013
CAS check (all FS-store, no DB). Those services then reach TWO genuine external boundaries the web
subtree deliberately does not stand up: the Postgres index (``index_article``, ``index_subtree``) and
the Procrastinate worker queue (``enqueue_*``). ``app.after_write`` (and ``app.articles``, for the
thumbnail job) import both as module-level names precisely so they are monkeypatchable.

This autouse fixture no-ops exactly those boundaries, so the web tests keep the whole
canonical-write + CAS path real. ``after_write.run`` swallows the index step's outcome into
``index_updated``; a no-op that returns None reads as a successful index, which is what these tests
assert against unless a test overrides the seam to force the ADR-0014 lag path.
"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from itertools import count
from pathlib import Path
from typing import cast

import pytest
from django.test import override_settings
from tests.app.web._fixtures import Corpus, KeyRecordingStore, settings_for, standard_corpus

from bundesarchiv.app.archive import Archive
from bundesarchiv.persistence.objectstore import ObjectStore


@pytest.fixture
def corpus(tmp_path: Path) -> Iterator[Corpus]:
    """The frozen standard corpus (see ``_fixtures``), live for the test's duration."""
    built = standard_corpus(tmp_path / "canonical")
    with override_settings(**settings_for(built)):
        yield built


@pytest.fixture
def make_corpus(tmp_path: Path) -> Iterator[Callable[[], Corpus]]:
    """Build a fresh ROOT-only corpus to fill with bespoke content. Each call gets its own store
    and becomes the canonical root, so a test that needs two archives builds them in the order it
    wants to query them."""
    roots = count()
    with ExitStack() as stack:

        def build() -> Corpus:
            built = Corpus(tmp_path / f"canonical-{next(roots)}")
            stack.enter_context(override_settings(**settings_for(built)))
            return built

        yield build


@pytest.fixture
def recording_store(monkeypatch: pytest.MonkeyPatch) -> KeyRecordingStore:
    """Every view's ``Archive.canonical`` goes through a recorder over the real LocalFs store of
    whichever corpus is live, so a deny test can assert no blob was probed."""
    store = KeyRecordingStore(Archive.canonical)
    monkeypatch.setattr(
        Archive, "canonical", classmethod(lambda _: Archive.of(cast("ObjectStore", store)))
    )
    return store


@pytest.fixture(scope="session", autouse=True)
def _collect_static_assets() -> None:
    """Build STATIC_ROOT + the manifest once per session — the web tests run under prod settings,
    where {% static %} RAISES without one (ADR 0016). ``--clear`` drops a prior asset set's orphans."""
    from django.core.management import call_command

    call_command("collectstatic", "--no-input", "--clear", verbosity=0)


@pytest.fixture(autouse=True)
def _stub_service_boundaries(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No-op the index writes and every worker enqueue for the duration of a web test. The
    canonical write (repository + README + CAS) stays real; only the two external boundaries are
    stubbed."""
    from bundesarchiv.app import after_write, articles

    for name in (
        "index_article",
        "index_subtree",
        "enqueue_mirror_push",
        "enqueue_mirror_delete_article",
        "enqueue_reindex_article",
        "enqueue_reindex_subtree",
    ):
        monkeypatch.setattr(after_write, name, lambda *a, **k: None)
    monkeypatch.setattr(articles, "enqueue_generate_thumbnail", lambda *a, **k: None)
    yield
