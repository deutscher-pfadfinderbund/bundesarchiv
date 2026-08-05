"""Dev viewer switcher + prod-safety (Part 4.4).

Two seams:

- The switcher round-trip UNDER dev settings: POST a viewer choice -> a signed cookie is set ->
  the next request's ``viewer_of`` returns that viewer. Exercised through Django's test ``Client``
  with the dev URLconf + middleware active (the real request path, not mocks).
- Prod-safety: under the PRODUCTION settings module the ``DevViewerMiddleware`` is absent from
  ``MIDDLEWARE`` and the switcher route does not resolve — the dev mechanism is unreachable in prod
  by absence of code paths, not by a flag.
"""

import importlib
import os
import subprocess
import sys

import pytest
from django.test import Client, RequestFactory, override_settings
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.viewer import Archivist, Member, Public

#: The switcher's route as a raw path literal — needed ONLY where a test must exercise `resolve()`
#: under a URLconf where `reverse("dev-switch-viewer")` itself would already raise (the point of that
#: test); everywhere else in this file the dev URLconf is active and `reverse()` is used instead.
_SWITCHER_PATH = "/_dev/viewer/"

_DEV = {
    "ROOT_URLCONF": "bundesarchiv.app.web.dev_urls",
    # Mirror the real settings_dev MIDDLEWARE: CSRF first (the Part 4.7 fix wave), then the dev viewer.
    "MIDDLEWARE": [
        "django.middleware.csrf.CsrfViewMiddleware",
        "bundesarchiv.app.web.dev.DevViewerMiddleware",
    ],
    "DEV_VIEWER_SIGNING_KEY": "test-dev-viewer-key",
}


@override_settings(**_DEV)
def test_switcher_get_renders_form() -> None:
    response = Client().get(reverse("dev-switch-viewer"))
    assert response.status_code == 200
    body = response.content.decode()
    assert 'name="kind"' in body or "name=kind" in body
    assert "Betrachter" in body  # German switcher heading


@override_settings(**_DEV)
@pytest.mark.parametrize(
    ("post_data", "expected"),
    [
        (
            {"kind": "member", "groups": "vorstand, archiv-ag"},
            Member(groups=("vorstand", "archiv-ag")),
        ),
        ({"kind": "archivist"}, Archivist()),
        ({"kind": "public"}, Public()),
    ],
    ids=["member", "archivist", "public"],
)
def test_switcher_post_roundtrips_to_viewer_of(post_data: dict[str, str], expected: object) -> None:
    client = Client()
    response = client.post(reverse("dev-switch-viewer"), post_data)
    assert response.status_code == 302  # redirect back to the switcher
    # The signed cookie is now on the client; a fresh request through viewer_of must decode it.
    request = RequestFactory().get("/")
    request.COOKIES.update({k: c.value for k, c in client.cookies.items()})
    assert viewer_of(request) == expected


@override_settings(**_DEV)
def test_switcher_post_carries_csrf_token_so_it_works_under_enforcement() -> None:
    # With CsrfViewMiddleware now active in dev, the switcher's hand-rolled form must carry the token.
    # Enforce CSRF: GET the form (seeds the cookie + renders the hidden token), then POST with it.
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("dev-switch-viewer"))
    token = client.cookies["csrftoken"].value
    response = client.post(
        reverse("dev-switch-viewer"), {"kind": "archivist", "csrfmiddlewaretoken": token}
    )
    assert response.status_code == 302  # accepted (a missing token would be 403)


@override_settings(**_DEV)
def test_middleware_attaches_viewer_to_request() -> None:
    client = Client()
    client.post(reverse("dev-switch-viewer"), {"kind": "archivist"})
    # A subsequent GET runs through DevViewerMiddleware, which sets request.viewer used by the form.
    response = client.get(reverse("dev-switch-viewer"))
    assert "Archivar" in response.content.decode()


# --- prod-safety: the dev mechanism is unreachable under production settings -----------------


def test_prod_settings_have_no_dev_middleware() -> None:
    prod = importlib.import_module("bundesarchiv.index.settings")
    assert "bundesarchiv.app.web.dev.DevViewerMiddleware" not in getattr(prod, "MIDDLEWARE", [])


def test_prod_settings_define_no_dev_signing_key() -> None:
    prod = importlib.import_module("bundesarchiv.index.settings")
    assert not hasattr(prod, "DEV_VIEWER_SIGNING_KEY")


def test_prod_root_urlconf_is_the_media_surface_not_the_dev_urls() -> None:
    # Part 4.3: prod now HAS a ROOT_URLCONF — the authorized media surface — but NOT the dev URLconf
    # (which is what adds the switcher). Prod points straight at the media routes; the dev switcher
    # composes those media routes WITH the switcher only under settings_dev.
    prod = importlib.import_module("bundesarchiv.index.settings")
    assert prod.ROOT_URLCONF == "bundesarchiv.app.web.urls"
    assert prod.ROOT_URLCONF != "bundesarchiv.app.web.dev_urls"


def test_prod_media_urlconf_exposes_no_dev_switcher_route() -> None:
    # The prod URLconf carries the media routes and nothing dev-only: the switcher name is unknown
    # there, so it cannot resolve/reverse under production settings (unreachable by absence).
    prod_urls = importlib.import_module("bundesarchiv.app.web.urls")
    assert not any(getattr(p, "name", None) == "dev-switch-viewer" for p in prod_urls.urlpatterns)


def test_switcher_route_lives_only_in_the_dev_urlconf() -> None:
    # The switcher route exists ONLY in the dev URLconf — nothing production imports adds it.
    dev_urls = importlib.import_module("bundesarchiv.app.web.dev_urls")
    assert any(getattr(p, "name", None) == "dev-switch-viewer" for p in dev_urls.urlpatterns)


@override_settings(ROOT_URLCONF="tests.app.web._empty_urls")
def test_switcher_neither_resolves_nor_reverses_without_the_dev_urlconf() -> None:
    # With a URLconf that has no routes (a stand-in for a prod process mounting no HTTP surface),
    # the switcher path 404s and its name is unreversible — the concrete "does not resolve"
    # assertion the prod-safety spec calls for.
    with pytest.raises(Resolver404):
        resolve(_SWITCHER_PATH)
    with pytest.raises(NoReverseMatch):
        reverse("dev-switch-viewer")


def test_prod_process_boots_clean_under_prod_settings() -> None:
    # The strongest, realest prod-safety proof: a fresh process runs ``manage.py check`` under the
    # PRODUCTION settings module (no SECRET_KEY, no MIDDLEWARE, no ROOT_URLCONF) and passes. If prod
    # settings had grown any dev-viewer coupling (a middleware/URLconf referencing dev code that
    # needs the dev key), this real boot would surface it — mocks cannot.
    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = "bundesarchiv.index.settings"
    env.pop("DEV_VIEWER_SIGNING_KEY", None)
    env.pop("SECRET_KEY", None)
    env.pop("BUNDESARCHIV_DEV_VIEWER_SIGNING_KEY", None)
    result = subprocess.run(
        [sys.executable, "manage.py", "check"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, (
        f"prod `manage.py check` failed:\n{result.stdout}\n{result.stderr}"
    )
