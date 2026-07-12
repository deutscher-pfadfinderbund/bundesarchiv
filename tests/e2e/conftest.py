"""E2E journey suite wiring (Part #26): pytest-playwright against a live Django server + real Postgres.

Every journey drives the REAL app end to end in a browser — no view-function shortcuts, no stubbed
services. The stack:

- ``live_server`` (pytest-django) serves the app in a thread. It is pointed at ``settings_dev`` (dev
  urlconf + DevViewerMiddleware + the dev signing key) via ``override_settings`` per test, so the
  archivist cookie the browser carries is honoured exactly as in dev; the canonical store is a fresh
  temp dir per test.
- A canonical corpus is built + committed per test (the live server reads committed rows; pytest-
  django TRUNCATEs the index between tests, so a once-per-session corpus would vanish), indexed so
  ``search`` sees it. A fresh store per test also isolates the mutating journeys from the read-only.
- ``archivist_page`` is a Playwright page whose context already carries the signed ``dev_viewer``
  archivist cookie, so a journey lands authenticated. ``public_page`` carries none (anonymous).

Marked ``e2e`` (excluded from the default run); the cached chromium-1228 drives headless. These need
Postgres like the other DB suites (the shared ``_pg_guard`` fails, not skips, when it is down).
"""

import os
from collections.abc import Iterator
from pathlib import Path

# Playwright's sync API runs an event loop in its worker thread; Django then flags any ORM call
# (e.g. the corpus build/teardown) as SynchronousOnlyOperation even though it is sync-safe here (the
# loop is Playwright's, not an async DB context). Allow it for the e2e suite only — set before Django
# imports read it. (The other suites never import this conftest, so their async-safety check stands.)
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

import pytest
from django.core import signing
from django.test import override_settings
from playwright.sync_api import Browser, Page
from pytest_django.live_server_helper import LiveServer
from pytest_django.plugin import DjangoDbBlocker
from tests.e2e._corpus import CorpusHandles, build_corpus

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index import settings_dev

# The E2E suite's own dev-viewer signing key: the cookie signer (``_archivist_cookie``) and the
# middleware (via the override below) both use it, so it need not match the real dev default.
_DEV_KEY = "test-e2e-dev-viewer-key"


@pytest.fixture
def _e2e_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The canonical store root for ONE journey (a fresh temp dir per test).

    Per-test, not per-session: ``live_server`` drives its requests through pytest-django's
    ``transactional_db``, which TRUNCATEs the index tables between tests — a once-built session corpus
    would be gone by the second test. A fresh dir + rebuild per test also isolates the mutating
    journeys (create/edit/delete/bulk) from the read-only ones, so order never matters.
    """
    return tmp_path_factory.mktemp("e2e-canonical")


@pytest.fixture
def _e2e_thumbs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The LOCAL derived-thumbnail cache root for ONE journey. Per-test so the corpus builder can
    pre-generate thumbnail WebPs into it (the worker-side generation the live e2e run has no worker
    for) and the live server reads the same dir through the settings override — so a detail/pane
    thumbnail actually renders in the gallery instead of 404ing to a broken <img>."""
    return tmp_path_factory.mktemp("e2e-thumbs")


@pytest.fixture
def _e2e_settings(_e2e_root: Path, _e2e_thumbs: Path) -> Iterator[dict[str, object]]:
    """The settings the live server runs under. Composed FROM ``settings_dev`` (the real dev layer:
    its urlconf + middleware) so a change to the dev middleware/urlconf never silently skips this
    suite — only the genuinely per-test values are overridden on top: this test's signing key, its
    canonical store + thumbnail cache, and ``DEBUG=False`` (the suite exercises prod-like handling).

    Views read ``settings.BUNDESARCHIV_CANONICAL_ROOT`` / ``BUNDESARCHIV_THUMBNAIL_ROOT`` per request,
    so the session-scoped ``live_server`` thread picks up each test's fresh dirs through this override.
    """
    settings: dict[str, object] = {
        "ROOT_URLCONF": settings_dev.ROOT_URLCONF,
        "MIDDLEWARE": settings_dev.MIDDLEWARE,
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(_e2e_root),
        "BUNDESARCHIV_THUMBNAIL_ROOT": str(_e2e_thumbs),
        "DEBUG": False,
    }
    with override_settings(**settings):
        yield settings


@pytest.fixture
def e2e_corpus(
    _e2e_root: Path,
    _e2e_thumbs: Path,
    _e2e_settings: dict[str, object],
    transactional_db: None,
    django_db_blocker: DjangoDbBlocker,
) -> CorpusHandles:
    """Build + index the canonical corpus for THIS journey, committed so the live server (a separate
    thread) reads it. Depends on ``transactional_db`` — the same fixture ``live_server`` uses — so the
    corpus is committed into the shared, per-test-truncated DB the live server queries. Thumbnails are
    pre-generated into ``_e2e_thumbs`` (no worker in the e2e run) so media <img>s actually render."""
    with django_db_blocker.unblock():
        return build_corpus(_e2e_root, thumbnail_root=_e2e_thumbs)


@pytest.fixture
def live_workbench(
    live_server: LiveServer, _e2e_settings: dict[str, object], e2e_corpus: CorpusHandles
) -> str:
    """The live server's base URL, with the corpus built + the dev settings active. The base for
    every journey's navigation."""
    return live_server.url


def _archivist_cookie(base_url: str) -> dict[str, object]:
    """A Playwright cookie dict carrying the signed dev_viewer=archivist value (same signer the dev
    switcher uses), scoped to the live server's host so the browser sends it on every request."""
    from urllib.parse import urlparse

    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    value = signer.sign(encode_viewer(Archivist()))
    host = urlparse(base_url).hostname or "localhost"
    return {"name": "dev_viewer", "value": value, "domain": host, "path": "/"}


def _archivist_context_page(browser: Browser, base_url: str, *, javascript: bool) -> Iterator[Page]:
    """A page in a fresh archivist-cookie context, JS on or off. Shared by the JS and no-JS
    archivist fixtures so the only difference between them is the ``java_script_enabled`` flag."""
    context = browser.new_context(java_script_enabled=javascript)
    context.add_cookies([_archivist_cookie(base_url)])  # type: ignore[list-item]
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def archivist_page(live_workbench: str, browser: Browser) -> Iterator[Page]:
    """A Playwright page authenticated as an Archivist (the dev_viewer cookie is pre-set on its
    context), JS enabled. Journeys start here."""
    yield from _archivist_context_page(browser, live_workbench, javascript=True)


@pytest.fixture
def no_js_archivist_page(live_workbench: str, browser: Browser) -> Iterator[Page]:
    """An archivist page with JavaScript DISABLED — pins the no-JS baseline promise (the forms +
    workbench must work server-rendered, without HTMX or the PE enhancements)."""
    yield from _archivist_context_page(browser, live_workbench, javascript=False)


@pytest.fixture
def public_page(live_workbench: str, browser: Browser) -> Iterator[Page]:
    """A Playwright page with NO viewer cookie — an anonymous/public visitor (for the leak journeys)."""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


# The shared PG guard + guarded django_db_setup live at tests/conftest.py; the e2e suite inherits
# them, so a down Postgres fails (not skips) with the actionable hint like every other DB suite.
