"""Production-deploy settings whose DIRECTION is the security property (sibling of
``test_auth_settings.py``).

Each fact here is silent when wrong: a forgotten SECRET_KEY serves happily until something signs,
a missing proxy header turns every POST into a CSRF origin failure behind Traefik+nginx, and an
insecure CSRF cookie leaks over any plain-http hop. The deploy env itself is enforced at the one
entry point a real app server uses.
"""

import importlib
import runpy
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from tests.app.web._fixtures import PUBLISHED_ULID, client_as

from bundesarchiv.domain.viewer import Public
from bundesarchiv.index import settings as prod_settings
from bundesarchiv.index import settings_dev

_WSGI = "bundesarchiv.index.wsgi"


def _boot_wsgi() -> ModuleType:
    """Import (or re-import) the WSGI entry point under the current environment."""
    module = importlib.import_module(_WSGI)
    return importlib.reload(module)


@pytest.fixture(autouse=True)
def _restore_wsgi() -> Iterator[None]:
    """Leave the process as found: these tests import the WSGI module under doctored env."""
    yield
    sys.modules.pop(_WSGI, None)


def test_serving_env_is_complete_and_the_wsgi_entry_boots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in prod_settings.REQUIRED_SERVING_ENV:
        monkeypatch.setenv(name, "set-for-this-test")
    assert getattr(_boot_wsgi(), "application", None) is not None


@pytest.mark.parametrize("missing", prod_settings.REQUIRED_SERVING_ENV)
def test_wsgi_entry_refuses_to_serve_without_a_required_env_var(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for name in prod_settings.REQUIRED_SERVING_ENV:
        monkeypatch.setenv(name, "set-for-this-test")
    monkeypatch.delenv(missing)
    with pytest.raises(ImproperlyConfigured, match=missing):
        _boot_wsgi()


def test_production_trusts_the_proxy_chain_for_the_scheme() -> None:
    # Traefik terminates TLS and nginx forwards; without this Django sees http, and every POST
    # fails the CSRF origin check against an https Referer.
    assert prod_settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_csrf_cookie_is_secure_in_production_and_not_in_dev() -> None:
    assert prod_settings.CSRF_COOKIE_SECURE is True
    assert settings_dev.CSRF_COOKIE_SECURE is False  # dev serves plain http


def test_the_upload_ceiling_is_four_gibibytes_by_default() -> None:
    # Owner ruling, 2026-09-19. Per FILE — nginx's client_max_body_size bounds the whole request
    # and stays above this number (deploy/nginx/nginx.conf), so the oversize error is this one.
    assert prod_settings.BUNDESARCHIV_MAX_UPLOAD_BYTES == 4 * 1024**3


def test_the_token_cookie_middleware_wraps_everything_that_resolves_the_viewer() -> None:
    """``TokenCookieMiddleware`` writes a refresh outcome onto the response, so it must sit outside
    every middleware that calls ``viewer_of`` (ADR 0018). Missing, a refreshed login never reaches
    the browser and a dead refresh cookie is never cleared."""
    token = "bundesarchiv.app.web.viewers.TokenCookieMiddleware"
    gate = "bundesarchiv.app.web.anonymous_gate.AnonymousGateMiddleware"
    for stack in (prod_settings.MIDDLEWARE, settings_dev.MIDDLEWARE):
        assert stack.index(token) < stack.index(gate)


def test_security_middleware_leads_both_middleware_stacks() -> None:
    for stack in (prod_settings.MIDDLEWARE, settings_dev.MIDDLEWARE):
        assert stack[0] == "django.middleware.security.SecurityMiddleware"
        assert stack[1] == "whitenoise.middleware.WhiteNoiseMiddleware"


@pytest.mark.usefixtures("corpus")
def test_a_page_carries_the_page_policy_with_the_keycloak_origin_as_form_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Spelled out, not built from the setting, so a weakened directive fails HERE. The settings run
    # fresh under a deploy's issuer: form-action takes the Keycloak origin, never its realm path.
    monkeypatch.setenv("BUNDESARCHIV_OIDC_ISSUER", "https://auth.example.org/realms/master")
    deploy_policy = runpy.run_path(prod_settings.__file__)["SECURE_CSP"]
    with override_settings(SECURE_CSP=deploy_policy):
        response = client_as(Public()).get(f"/articles/{PUBLISHED_ULID}")
    assert response.status_code == 200
    assert response["Content-Security-Policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self' https://auth.example.org"
    )
