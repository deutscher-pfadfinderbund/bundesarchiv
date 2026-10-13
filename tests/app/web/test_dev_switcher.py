"""The dev viewer switcher, and its absence under production settings: unreachable by missing code
paths, not by a flag."""

import importlib
import os
import subprocess
import sys

import pytest
from django.test import Client, RequestFactory, override_settings
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.viewer import Archivist, Member, Public

#: A literal: under a URLconf without the switcher, ``reverse`` itself raises.
_SWITCHER_PATH = "/_dev/viewer/"

_DEV = {
    "ROOT_URLCONF": "bundesarchiv.app.web.dev_urls",
    "MIDDLEWARE": ["django.middleware.csrf.CsrfViewMiddleware"],
    "DEV_VIEWER_SIGNING_KEY": "test-dev-viewer-key",
}


@override_settings(**_DEV)
def test_switcher_get_renders_form() -> None:
    response = Client().get(reverse("dev-switch-viewer"))
    assert response.status_code == 200
    body = response.content.decode()
    assert 'name="kind"' in body or "name=kind" in body
    assert "Betrachter" in body


@override_settings(**_DEV)
@pytest.mark.parametrize(
    ("post_data", "expected"),
    [
        (
            {"kind": "member", "groups": "vorstand, archiv-ag"},
            Member(groups=("vorstand", "archiv-ag")),
        ),
        ({"kind": "archivist"}, Archivist()),
        ({"kind": "archivist", "username": "anna.schmidt"}, Archivist(username="anna.schmidt")),
        ({"kind": "public"}, Public()),
    ],
    ids=["member", "archivist", "named-archivist", "public"],
)
def test_switcher_post_roundtrips_to_viewer_of(post_data: dict[str, str], expected: object) -> None:
    client = Client()
    response = client.post(reverse("dev-switch-viewer"), post_data)
    assert response.status_code == 302
    request = RequestFactory().get("/")
    request.COOKIES.update({k: c.value for k, c in client.cookies.items()})
    assert viewer_of(request) == expected


@override_settings(**_DEV)
def test_switcher_post_carries_csrf_token_so_it_works_under_enforcement() -> None:
    # the switcher's hand-rolled form must render the token itself
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("dev-switch-viewer"))
    token = client.cookies["csrftoken"].value
    response = client.post(
        reverse("dev-switch-viewer"), {"kind": "archivist", "csrfmiddlewaretoken": token}
    )
    assert response.status_code == 302  # accepted (a missing token would be 403)


@override_settings(**_DEV)
def test_the_switcher_shows_the_active_archivists_name() -> None:
    client = Client()
    client.post(reverse("dev-switch-viewer"), {"kind": "archivist", "username": "anna.schmidt"})
    response = client.get(reverse("dev-switch-viewer"))
    assert "anna.schmidt" in response.content.decode()


# --- prod-safety: the dev mechanism is unreachable under production settings -----------------


def test_prod_settings_define_no_dev_signing_key() -> None:
    prod = importlib.import_module("bundesarchiv.index.settings")
    assert not hasattr(prod, "DEV_VIEWER_SIGNING_KEY")


def test_prod_root_urlconf_is_the_media_surface_not_the_dev_urls() -> None:
    prod = importlib.import_module("bundesarchiv.index.settings")
    assert prod.ROOT_URLCONF == "bundesarchiv.app.web.urls"
    assert prod.ROOT_URLCONF != "bundesarchiv.app.web.dev_urls"


def test_prod_media_urlconf_exposes_no_dev_switcher_route() -> None:
    prod_urls = importlib.import_module("bundesarchiv.app.web.urls")
    assert not any(getattr(p, "name", None) == "dev-switch-viewer" for p in prod_urls.urlpatterns)


def test_switcher_route_lives_only_in_the_dev_urlconf() -> None:
    dev_urls = importlib.import_module("bundesarchiv.app.web.dev_urls")
    assert any(getattr(p, "name", None) == "dev-switch-viewer" for p in dev_urls.urlpatterns)


@override_settings(ROOT_URLCONF="tests.app.web._empty_urls")
def test_switcher_neither_resolves_nor_reverses_without_the_dev_urlconf() -> None:
    with pytest.raises(Resolver404):
        resolve(_SWITCHER_PATH)
    with pytest.raises(NoReverseMatch):
        reverse("dev-switch-viewer")


# Explicit: the subprocess connects to Postgres out of band, so no DB fixture appears in this
# test's closure and the requires_pg derivation in tests/conftest.py cannot see it.
@pytest.mark.requires_pg
def test_prod_process_boots_clean_under_prod_settings() -> None:
    # a real boot under prod settings surfaces any dev-viewer coupling that needs the dev key
    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = "bundesarchiv.index.settings"
    env.pop("DEV_VIEWER_SIGNING_KEY", None)
    env.pop("SECRET_KEY", None)
    env.pop("BUNDESARCHIV_DEV_VIEWER_SIGNING_KEY", None)
    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"prod `manage.py check` failed:\n{result.stdout}\n{result.stderr}"
    )
