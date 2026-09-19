"""Production-deploy settings whose DIRECTION is the security property (sibling of
``test_auth_settings.py``).

Each fact here is silent when wrong: a forgotten SECRET_KEY serves happily until something signs,
a missing proxy header turns every POST into a CSRF origin failure behind Traefik+nginx, and an
insecure CSRF cookie leaks over any plain-http hop. The deploy env itself is enforced at the one
entry point a real app server uses.
"""

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

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


def test_security_middleware_leads_both_middleware_stacks() -> None:
    for stack in (prod_settings.MIDDLEWARE, settings_dev.MIDDLEWARE):
        assert stack[0] == "django.middleware.security.SecurityMiddleware"
        assert stack[1] == "whitenoise.middleware.WhiteNoiseMiddleware"
