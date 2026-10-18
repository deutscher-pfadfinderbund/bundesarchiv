"""The dev realm's login page (ADR 0025), and its absence under production settings: unreachable by
missing code paths, not by a flag."""

import importlib
import os
import subprocess
import sys
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client, RequestFactory, override_settings
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import dev_realm_settings, page_forms

from bundesarchiv.app.web.dev_realm import DevRealm
from bundesarchiv.app.web.viewers import realm, viewer_of
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

#: A literal: under a URLconf without the page, ``reverse`` itself raises.
_PAGE = "/_dev/viewer/"

_CALLBACK = "http://testserver/oidc/callback"


@pytest.fixture(autouse=True)
def _dev() -> Iterator[None]:
    with override_settings(
        ROOT_URLCONF="bundesarchiv.app.web.dev_urls",
        MIDDLEWARE=["django.middleware.csrf.CsrfViewMiddleware"],
        **dev_realm_settings(),
    ):
        yield


def _flow(client: Client) -> dict[str, str]:
    """Start a login: the page the realm sends the browser to, as its query."""
    location = client.get("/login", {"next": "/articles/new"})["Location"]
    assert urlsplit(location).path == _PAGE
    return {name: values[0] for name, values in parse_qs(urlsplit(location).query).items()}


def _logged_in_as(client: Client) -> Viewer:
    request = RequestFactory().get("/")
    request.COOKIES.update({name: c.value for name, c in client.cookies.items()})
    return viewer_of(request)


def _answer(client: Client, choice: dict[str, str], **flow: str) -> Any:
    return client.post(_PAGE, {**_flow(client), **flow, **choice})


def test_the_page_renders_the_login_it_was_sent() -> None:
    client = Client()
    flow = _flow(client)
    ((action, fields),) = page_forms(client.get(_PAGE, flow).content.decode())
    assert action == _PAGE
    assert flow.items() <= fields.items()


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        (
            {"kind": "member", "groups": "vorstand, archiv-ag"},
            Member(groups=("vorstand", "archiv-ag")),
        ),
        ({"kind": "member"}, Member()),
        ({"kind": "archivist"}, Archivist()),
        ({"kind": "archivist", "username": "  "}, Archivist()),
        ({"kind": "archivist", "username": "anna.schmidt"}, Archivist(username="anna.schmidt")),
    ],
    ids=["member", "member-without-groups", "archivist", "blank-username", "named-archivist"],
)
def test_the_answer_logs_in_through_the_callback(choice: dict[str, str], expected: Viewer) -> None:
    client = Client()
    answer = _answer(client, choice)
    assert answer.status_code == 302
    assert answer["Location"].startswith(_CALLBACK + "?")
    landing = client.get(answer["Location"])
    assert landing["Location"] == "/articles/new"
    assert _logged_in_as(client) == expected


def test_an_unknown_kind_mints_nothing() -> None:
    client = Client()
    assert_denied(_answer(client, {"kind": "public"}))
    assert _logged_in_as(client) == Public()


@pytest.mark.parametrize(
    "redirect_uri",
    [
        pytest.param("http://evil.example/oidc/callback", id="another-host"),
        pytest.param("http://testserver/elsewhere", id="another-path"),
        pytest.param("//evil.example/oidc/callback", id="scheme-relative"),
        pytest.param("https://testserver/oidc/callback", id="another-scheme"),
        pytest.param("/oidc/callback", id="relative"),
        pytest.param("http://testserver@evil.example/oidc/callback", id="userinfo"),
        pytest.param(_CALLBACK + "?next=//evil.example", id="extra-query"),
        pytest.param(_CALLBACK + "/", id="trailing-slash"),
    ],
)
def test_the_page_answers_only_this_sites_callback(redirect_uri: str) -> None:
    """No open redirect: the code goes back to this site's own callback, or nowhere."""
    client = Client()
    flow = {**_flow(client), "redirect_uri": redirect_uri}
    assert_denied(client.get(_PAGE, flow))
    assert_denied(client.post(_PAGE, {**flow, "kind": "archivist"}))


def test_a_bookmark_starts_a_login() -> None:
    response = Client().get(_PAGE)
    assert response.status_code == 302
    assert response["Location"] == reverse("login") + "?next=%2F"


def test_the_answer_carries_its_csrf_token_so_it_works_under_enforcement() -> None:
    client = Client(enforce_csrf_checks=True)
    flow = _flow(client)
    ((_, fields),) = page_forms(client.get(_PAGE, flow).content.decode())
    response = client.post(_PAGE, {**fields, "kind": "archivist"})
    assert response.status_code == 302  # accepted (a missing token would be 403)


def test_the_page_shows_who_is_logged_in() -> None:
    client = Client()
    client.get(_answer(client, {"kind": "archivist", "username": "anna.schmidt"})["Location"])
    assert "anna.schmidt" in client.get(_PAGE, _flow(client)).content.decode()


def test_dev_settings_name_the_dev_realm() -> None:
    dev = importlib.import_module("bundesarchiv.index.settings_dev")
    with override_settings(BUNDESARCHIV_REALM=dev.BUNDESARCHIV_REALM):
        assert isinstance(realm(), DevRealm)


# --- prod-safety: the dev realm is unreachable under production settings ---------------------


def test_prod_settings_name_no_dev_realm_and_no_dev_key() -> None:
    prod = importlib.import_module("bundesarchiv.index.settings")
    assert not hasattr(prod, "BUNDESARCHIV_REALM")
    assert not hasattr(prod, "DEV_VIEWER_SIGNING_KEY")


def test_prod_root_urlconf_is_the_media_surface_not_the_dev_urls() -> None:
    prod = importlib.import_module("bundesarchiv.index.settings")
    assert prod.ROOT_URLCONF == "bundesarchiv.app.web.urls"


def test_prod_media_urlconf_exposes_no_dev_login_page() -> None:
    prod_urls = importlib.import_module("bundesarchiv.app.web.urls")
    assert not any(getattr(p, "name", None) == "dev-authorize" for p in prod_urls.urlpatterns)


def test_the_dev_login_page_lives_only_in_the_dev_urlconf() -> None:
    dev_urls = importlib.import_module("bundesarchiv.app.web.dev_urls")
    assert any(getattr(p, "name", None) == "dev-authorize" for p in dev_urls.urlpatterns)


@override_settings(ROOT_URLCONF="tests.app.web._empty_urls")
def test_the_page_neither_resolves_nor_reverses_without_the_dev_urlconf() -> None:
    with pytest.raises(Resolver404):
        resolve(_PAGE)
    with pytest.raises(NoReverseMatch):
        reverse("dev-authorize")


# Explicit: the subprocess connects to Postgres out of band, so no DB fixture appears in this
# test's closure and the requires_pg derivation in tests/conftest.py cannot see it.
@pytest.mark.requires_pg
def test_prod_process_boots_clean_under_prod_settings() -> None:
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
