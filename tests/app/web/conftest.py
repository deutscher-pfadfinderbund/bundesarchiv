"""Web-subtree test wiring: the shared corpus fixtures + the genuine external service seams.

The ``corpus`` / ``make_corpus`` fixtures hand out ``_fixtures.Corpus`` with
``override_settings(**settings_for(...))`` already entered, so a web test neither builds the store
wiring nor wraps its request in a settings block.

The Part 4.7 cataloging views drive the REAL write path — ``create_article`` / ``save_article`` /
``hard_delete_article`` — which exercises the repository, the README round-trip, and the ADR-0013
CAS check (all FS-store, no DB). Those services then reach TWO genuine external boundaries the web
subtree deliberately does not stand up: the Postgres index (``index_article``) and the Procrastinate
worker queue (``enqueue_*``). ``app.articles`` imports both as module-level names precisely so they
are monkeypatchable (its docstring calls them "a genuine boundary").

This autouse fixture no-ops exactly those boundaries, so the web tests keep the whole
canonical-write + CAS path real. ``_sync_index`` swallows the index step's outcome into
``index_updated``; a no-op that returns None reads as a successful index, which is what these tests
assert against unless a test overrides the seam to force the ADR-0014 lag path.
"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from itertools import count
from pathlib import Path

import pytest
from django.test import override_settings
from tests.app.web._fixtures import Corpus, settings_for, standard_corpus


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


@pytest.fixture(scope="session", autouse=True)
def _collect_static_assets() -> None:
    """Build STATIC_ROOT + the manifest once per session — the web tests run under prod settings,
    where {% static %} RAISES without one (ADR 0016). ``--clear`` drops a prior asset set's orphans."""
    from django.core.management import call_command

    call_command("collectstatic", "--no-input", "--clear", verbosity=0)


@pytest.fixture(autouse=True)
def _stub_service_boundaries(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No-op the index write and every worker enqueue on ``app.articles`` for the duration of a web
    test. The canonical write (repository + README + CAS) stays real; only the two external
    boundaries are stubbed."""
    from bundesarchiv.app import articles

    monkeypatch.setattr(articles, "index_article", lambda *a, **k: None)
    monkeypatch.setattr(articles, "enqueue_generate_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(articles, "enqueue_mirror_push", lambda *a, **k: None)
    monkeypatch.setattr(articles, "enqueue_mirror_delete_article", lambda *a, **k: None)
    monkeypatch.setattr(articles, "enqueue_reindex_article", lambda *a, **k: None)
    yield
