"""The anonymous gate (ADR 0018): an unauthenticated request gets the door, never the content.

The gate is OFF in the web suite's standard settings (``_fixtures.settings_for``) because dev and
the browser suites browse anonymously through the dev switcher — so every test here turns it ON
explicitly. The other half of the contract, that the gate changes NOTHING for an authenticated
viewer, is the leak matrix's whole existing body plus the archivist row below.
"""

from collections.abc import Iterator

import pytest
from django.contrib.staticfiles.storage import staticfiles_storage
from django.test import Client, override_settings
from tests.app.web._asserts import assert_door, assert_login_target
from tests.app.web._fixtures import PUBLISHED_ULID, Corpus, client_as

from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


@pytest.fixture
def gated(corpus: Corpus) -> Iterator[Corpus]:
    """The standard corpus with the gate ON — the production configuration."""
    with override_settings(ANONYMOUS_GATE_ENABLED=True):
        yield corpus


_PATHS = (
    "/",
    "/?q=sommer&page=2",
    f"/articles/{PUBLISHED_ULID}",
    "/articles/does-not-exist",
    "/articles/new",
    "/nichts-dergleichen",
)


@pytest.mark.parametrize("path", _PATHS)
def test_an_anonymous_request_gets_the_door(gated: Corpus, path: str) -> None:
    assert_door(client_as(None).get(path), path)


def test_the_door_is_the_same_page_on_every_path(gated: Corpus) -> None:
    """A real article, a made-up one and a route that does not exist answer the same page, apart
    from the login target it carries: existence is only answerable after authentication."""
    doors = {assert_door(client_as(None).get(path), path) for path in _PATHS}
    assert len(doors) == 1
    (door,) = doors
    assert "<form" not in door, "the door offers no search and no other way in"


def test_a_signed_public_cookie_is_still_anonymous(gated: Corpus) -> None:
    """Public is the absence of an identity, however it was arrived at."""
    assert_door(client_as(Public()).get("/"), "/")


def test_an_anonymous_post_gets_the_door_too(gated: Corpus) -> None:
    """The gate is method-blind: one check, no route- or verb-specific holes."""
    path = f"/articles/{PUBLISHED_ULID}/delete"
    assert_door(client_as(None).post(path, {"confirmed": "1"}), path)


def test_the_door_never_carries_a_foreign_login_target(gated: Corpus) -> None:
    """A path that is not the shape of a local one lands on the root instead (``safe_next``)."""
    # set in the environ: the test client would parse a "//host" argument as a host, not a path
    response = client_as(None).get("/", PATH_INFO="//evil.example/articles")
    assert_door(response, "/")


@pytest.mark.parametrize("viewer", [Member(groups=()), Archivist()])
def test_an_authenticated_viewer_passes_the_gate(gated: Corpus, viewer: Viewer) -> None:
    """The gate authenticates; it does not authorize. A Member still gets the catalog route's 404
    and an Archivist still gets its form — exactly as with the gate off."""
    response = client_as(viewer).get("/articles/new")
    assert response.status_code == (200 if isinstance(viewer, Archivist) else 404)


def test_an_htmx_request_is_sent_to_the_login_by_header(gated: Corpus) -> None:
    """An XHR cannot follow this redirect: it ends at Keycloak's cross-origin authorize URL, where
    the browser blocks the response and htmx swaps NOTHING — a save whose cookie just expired would
    look like a button that does nothing. ``HX-Redirect`` navigates the whole page instead."""
    response = client_as(None).get("/?q=sommer", headers={"hx-request": "true"})
    assert response.status_code == 204
    assert_login_target(response.headers["HX-Redirect"], "/?q=sommer")


def test_an_htmx_history_restore_is_sent_to_the_login_by_header(gated: Corpus) -> None:
    """htmx 4's Back-button restore is a fetch carrying ``HX-History-Restore-Request`` but NOT
    ``HX-Request``; a plain 302 would end at Keycloak's cross-origin URL like any other XHR."""
    response = client_as(None).get("/?q=sommer", headers={"hx-history-restore-request": "true"})
    assert response.status_code == 204
    assert_login_target(response.headers["HX-Redirect"], "/?q=sommer")


def test_static_assets_stay_public(gated: Corpus) -> None:
    """ADR 0016: /static/* is public by design and never behind the gate."""
    assert client_as(None).get(staticfiles_storage.url("tokens.css")).status_code == 200


def test_the_gate_is_off_when_the_flag_is_off(corpus: Corpus) -> None:
    """settings_dev's configuration: anonymous browsing behaves exactly as it did before the gate."""
    with override_settings(ANONYMOUS_GATE_ENABLED=False):
        assert Client().get("/articles/new").status_code == 404
