"""The anonymous gate (ADR 0018): unauthenticated requests are redirected, not answered.

The gate is OFF in the web suite's standard settings (``_fixtures.settings_for``) because dev and
the browser suites browse anonymously through the dev switcher — so every test here turns it ON
explicitly. The other half of the contract, that the gate changes NOTHING for an authenticated
viewer, is the leak matrix's whole existing body plus the archivist row below.
"""

from collections.abc import Iterator

import pytest
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http.response import HttpResponseBase
from django.test import Client, override_settings
from tests.app.web._asserts import assert_login_target
from tests.app.web._fixtures import PUBLISHED_ULID, Corpus, client_as

from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


@pytest.fixture
def gated(corpus: Corpus) -> Iterator[Corpus]:
    """The standard corpus with the gate ON — the production configuration."""
    with override_settings(ANONYMOUS_GATE_ENABLED=True):
        yield corpus


def _expect_login(response: HttpResponseBase, path: str) -> None:
    assert response.status_code == 302, f"{path}: expected a redirect"
    assert_login_target(response["Location"], path)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/?q=sommer&seite=2",
        f"/artikel/{PUBLISHED_ULID}",
        "/artikel/does-not-exist",
        "/artikel/neu",
        "/nichts-dergleichen",
    ],
)
def test_an_anonymous_request_is_sent_to_the_login(gated: Corpus, path: str) -> None:
    """Every path alike — a real article, a made-up one and a route that does not exist all answer
    the same redirect, so existence is only answerable after authentication."""
    _expect_login(client_as(None).get(path), path)


def test_a_signed_public_cookie_is_still_anonymous(gated: Corpus) -> None:
    """Public is the absence of an identity, however it was arrived at."""
    _expect_login(client_as(Public()).get("/"), "/")


def test_an_anonymous_post_is_sent_to_the_login_too(gated: Corpus) -> None:
    """The gate is method-blind: one check, no route- or verb-specific holes."""
    path = f"/artikel/{PUBLISHED_ULID}/loeschen"
    response = client_as(None).post(path, {"bestaetigt": "1"})
    assert response.status_code == 302
    assert_login_target(response.headers["Location"], path)


@pytest.mark.parametrize("viewer", [Member(groups=()), Archivist()])
def test_an_authenticated_viewer_passes_the_gate(gated: Corpus, viewer: Viewer) -> None:
    """The gate authenticates; it does not authorize. A Member still gets the catalog route's 404
    and an Archivist still gets its form — exactly as with the gate off."""
    response = client_as(viewer).get("/artikel/neu")
    assert response.status_code == (200 if isinstance(viewer, Archivist) else 404)


def test_an_htmx_request_is_sent_to_the_login_by_header(gated: Corpus) -> None:
    """An XHR cannot follow this redirect: it ends at Keycloak's cross-origin authorize URL, where
    the browser blocks the response and htmx swaps NOTHING — a save whose cookie just expired would
    look like a button that does nothing. ``HX-Redirect`` navigates the whole page instead."""
    response = client_as(None).get("/?q=sommer", headers={"hx-request": "true"})
    assert response.status_code == 204
    assert_login_target(response.headers["HX-Redirect"], "/?q=sommer")


def test_static_assets_stay_public(gated: Corpus) -> None:
    """ADR 0016: /static/* is public by design and never behind the gate."""
    assert client_as(None).get(staticfiles_storage.url("tokens.css")).status_code == 200


def test_the_gate_is_off_when_the_flag_is_off(corpus: Corpus) -> None:
    """settings_dev's configuration: anonymous browsing behaves exactly as it did before the gate."""
    with override_settings(ANONYMOUS_GATE_ENABLED=False):
        assert Client().get("/artikel/neu").status_code == 404
