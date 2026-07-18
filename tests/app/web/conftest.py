"""Web-subtree test wiring: stub the genuine external service seams (index + worker queue).

The Part 4.7 cataloging views drive the REAL write path — ``create_article`` / ``save_article`` /
``hard_delete_article`` — which exercises the repository, the README round-trip, and the ADR-0013
CAS check (all FS-store, no DB). Those services then reach TWO genuine external boundaries the web
subtree deliberately does not stand up: the Postgres index (``index_article``) and the Procrastinate
worker queue (``enqueue_*``). ``app.articles`` imports both as module-level names precisely so they
are monkeypatchable (its docstring calls them "a genuine boundary").

This autouse fixture no-ops exactly those boundaries, so the web tests keep the whole
canonical-write + CAS path real while staying DB-free (the ``tests/app/web`` subtree is exempt from
SKIP_PG by ``tests/app/conftest.py``). ``_sync_index`` swallows the index step's outcome into
``index_updated``; a no-op that returns None reads as a successful index, which is what these tests
assert against unless a test overrides the seam to force the ADR-0014 lag path.
"""

from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def _collect_static_assets() -> None:
    """Build STATIC_ROOT + the staticfiles manifest once per session so {% static %} resolves and
    WhiteNoise serves the collected tree (ADR 0016). The web tests run under prod settings (manifest
    storage), where {% static %} RAISES without a manifest — collectstatic builds it. Writes to
    STATIC_ROOT (``var/static``, gitignored); ``--clear`` drops orphans from a prior asset set.
    collectstatic populates the in-process ``staticfiles_storage`` singleton, so no reset is needed;
    autouse+session guarantees it runs before the first web test builds a client + WhiteNoise reads
    STATIC_ROOT."""
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
    monkeypatch.setattr(articles, "enqueue_reindex_article", lambda *a, **k: None)
    yield
