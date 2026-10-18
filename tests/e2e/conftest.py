"""E2E wiring: pytest-playwright against ``live_server`` under ``settings_dev``'s urlconf and
middleware.
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
from django.test import override_settings
from playwright.sync_api import Browser, BrowserContext, Page
from pytest_django.live_server_helper import LiveServer
from pytest_django.plugin import DjangoDbBlocker
from tests.e2e._corpus import CorpusHandles, build_corpus

from bundesarchiv.app.web.dev_realm import DevRealm, claims_of
from bundesarchiv.app.web.viewers import login_cookies
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index import settings_dev

# Any key works: the suite both mints and verifies the dev realm's tokens with it.
_DEV_KEY = "test-e2e-dev-viewer-key"

#: Outlives the longest journey or gallery state, so one access token serves the whole test.
_ACCESS_LIFETIME = 60 * 60


_REPORT_CSP_VIOLATIONS = """
document.addEventListener("securitypolicyviolation", (e) => window.__cspViolation(
  `${e.effectiveDirective} blocked ${e.blockedURI} in ${e.sourceFile}:${e.lineNumber}`));
"""


@pytest.fixture(autouse=True)
def _no_csp_violations(browser: Browser, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hooked on ``browser.new_context`` because tests open their own contexts."""
    violations: list[str] = []
    new_context = browser.new_context

    def guarded(**kwargs: object) -> BrowserContext:
        context = new_context(**kwargs)  # type: ignore[arg-type]
        context.expose_binding("__cspViolation", lambda _source, v: violations.append(v))
        context.add_init_script(_REPORT_CSP_VIOLATIONS)
        return context

    monkeypatch.setattr(browser, "new_context", guarded)
    yield
    assert not violations, f"CSP violations: {violations}"


@pytest.fixture
def _e2e_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Per test: pytest-django truncates the index between tests, so a session corpus would
    vanish."""
    return tmp_path_factory.mktemp("e2e-canonical")


@pytest.fixture
def _e2e_thumbs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("e2e-thumbs")


@pytest.fixture
def _e2e_settings(_e2e_root: Path, _e2e_thumbs: Path) -> Iterator[dict[str, object]]:
    """``settings_dev``'s layer, so a dev change never skips this suite. Views read the roots per
    request, so the session-scoped ``live_server`` follows each test's dirs.
    """
    settings: dict[str, object] = {
        "ROOT_URLCONF": settings_dev.ROOT_URLCONF,
        "MIDDLEWARE": settings_dev.MIDDLEWARE,
        # Non-manifest storage: live_server's StaticFilesHandler serves from the finders, so the e2e
        # run needs no collectstatic (ADR 0016).
        "STORAGES": settings_dev.STORAGES,
        # off: anonymous browses as Public, as in dev
        "ANONYMOUS_GATE_ENABLED": settings_dev.ANONYMOUS_GATE_ENABLED,
        # ...and its plain-http switch: live_server is http, and prod's Secure flag only survives
        # here because Chromium exempts localhost. It names the login cookies too (ADR 0025).
        "CSRF_COOKIE_SECURE": settings_dev.CSRF_COOKIE_SECURE,
        "BUNDESARCHIV_REALM": settings_dev.BUNDESARCHIV_REALM,
        "VIEWER_SIGNING_KEY": settings_dev.VIEWER_SIGNING_KEY,
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
    """Committed through ``transactional_db`` so the live server's thread reads it."""
    with django_db_blocker.unblock():
        return build_corpus(_e2e_root, thumbnail_root=_e2e_thumbs)


@pytest.fixture
def live_workbench(
    live_server: LiveServer, _e2e_settings: dict[str, object], e2e_corpus: CorpusHandles
) -> str:
    return live_server.url


def _archivist_cookie(base_url: str) -> dict[str, object]:
    """A Playwright cookie dict carrying the access token a dev-realm login as an Archivist leaves,
    scoped to the live server's host so the browser sends it on every request. Called under the
    e2e settings, whose key and cookie names it mints with."""
    from urllib.parse import urlparse

    tokens = DevRealm(lifetime=_ACCESS_LIFETIME).mint_tokens(claims_of(Archivist()))
    assert tokens is not None
    host = urlparse(base_url).hostname or "localhost"
    return {"name": login_cookies().access, "value": tokens.access, "domain": host, "path": "/"}


def _archivist_context_page(browser: Browser, base_url: str, *, javascript: bool) -> Iterator[Page]:
    context = browser.new_context(java_script_enabled=javascript)
    context.add_cookies([_archivist_cookie(base_url)])  # type: ignore[list-item]
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def archivist_page(live_workbench: str, browser: Browser) -> Iterator[Page]:
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
