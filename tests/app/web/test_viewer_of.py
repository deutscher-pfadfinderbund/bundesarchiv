"""``viewer_of`` through a login's token cookies: only an access token the realm issued and still
honours, or a refresh it accepts, yields a non-Public viewer; everything else is ``Public()``, never
an exception.
"""

from collections.abc import Iterator

import pytest
from django.core import signing
from django.http import HttpRequest
from django.test import RequestFactory, override_settings
from pytest_django.fixtures import Settings
from tests._login import DEV_KEY, viewer_cookies

from bundesarchiv.app.web.dev_realm import DevRealm, claims_of
from bundesarchiv.app.web.keycloak import KeycloakRealm
from bundesarchiv.app.web.viewers import login_cookies, realm, viewer_of
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

# A stand-in for a production SECRET_KEY: a token signed with any key but the dev realm's must not
# verify.
_PROD_SECRET_KEY = "totally-different-production-secret-key"

# Stands in for the deployment's ``VIEWER_SIGNING_KEY``, which prod settings leave unset.
_VIEWER_KEY = "test-web-viewer-signing-key"


@pytest.fixture(autouse=True)
def _dev_realm() -> Iterator[None]:
    with override_settings(
        DEV_VIEWER_SIGNING_KEY=DEV_KEY,
        VIEWER_SIGNING_KEY=_VIEWER_KEY,
        BUNDESARCHIV_REALM=DevRealm(),
    ):
        yield


def _request(cookies: dict[str, str]) -> HttpRequest:
    request = RequestFactory().get("/")
    request.COOKIES.update(cookies)
    return request


def _access(value: str) -> HttpRequest:
    return _request({login_cookies().access: value})


def _archivist_access() -> str:
    return viewer_cookies(Archivist())[login_cookies().access]


def test_no_cookie_is_public() -> None:
    assert viewer_of(_request({})) == Public()


def test_empty_cookie_is_public() -> None:
    assert (
        viewer_of(_request({login_cookies().access: "", login_cookies().refresh: ""})) == Public()
    )


@pytest.mark.parametrize(
    "viewer",
    [
        pytest.param(Archivist(), id="archivist"),
        pytest.param(Member(groups=()), id="member-no-groups"),
        pytest.param(Member(groups=("vorstand",)), id="member-single-group"),
        pytest.param(Member(groups=("vorstand", "archiv-ag")), id="member-multiple-groups"),
        pytest.param(Archivist(username="jürgen: 50% ,x"), id="archivist-with-a-hostile-name"),
        pytest.param(Member(groups=("Sales, EU",)), id="group-with-a-delimiter"),
    ],
)
def test_the_access_token_names_the_viewer(viewer: Viewer) -> None:
    assert viewer_of(_access(viewer_cookies(viewer)[login_cookies().access])) == viewer


def test_tampered_signature_is_public() -> None:
    access = _archivist_access()
    tampered = access[:-1] + ("A" if access[-1] != "A" else "B")  # flip the last signature char
    assert viewer_of(_access(tampered)) == Public()


def test_expired_access_without_refresh_is_public() -> None:
    expired = DevRealm(lifetime=-1).mint_tokens(claims_of(Archivist()))
    assert expired is not None
    assert viewer_of(_access(expired.access)) == Public()


def test_a_refresh_token_in_the_access_slot_is_public() -> None:
    # The same key under another salt: a token minted for one purpose never passes for another.
    refresh = viewer_cookies(Archivist())[login_cookies().refresh]
    assert viewer_of(_access(refresh)) == Public()


@pytest.mark.parametrize(
    "key",
    [pytest.param(_PROD_SECRET_KEY, id="prod-secret"), pytest.param(_VIEWER_KEY, id="viewer")],
)
def test_a_token_signed_with_another_key_is_public(key: str) -> None:
    # The viewer key signs only the transient login state; it must not mint an identity.
    with override_settings(DEV_VIEWER_SIGNING_KEY=key):
        forged = _archivist_access()
    assert viewer_of(_access(forged)) == Public()


def test_no_dev_key_configured_is_public() -> None:
    access = _archivist_access()
    with override_settings(DEV_VIEWER_SIGNING_KEY=None):
        assert viewer_of(_access(access)) == Public()


def test_a_stale_production_viewer_cookie_is_public() -> None:
    # The signed ``__Host-viewer`` cookie was removed (ADR 0018). One still sitting in a browser,
    # signed exactly as it used to be minted, must resolve as if it were absent.
    stale = signing.TimestampSigner(key=_VIEWER_KEY, salt="viewer").sign("v3:archivist:anna")
    assert viewer_of(_request({"__Host-viewer": stale})) == Public()


def test_a_stale_dev_viewer_cookie_is_public() -> None:
    # The dev switcher's cookie was removed (ADR 0025): one left in a dev browser names nobody.
    stale = signing.TimestampSigner(key=DEV_KEY, salt="dev-viewer").sign("archivist:anna")
    assert viewer_of(_request({"dev_viewer": stale})) == Public()


def test_the_viewer_is_resolved_once_per_request() -> None:
    request = _access(_archivist_access())
    resolved = viewer_of(request)
    request.COOKIES.update(viewer_cookies(Member(groups=("v",))))
    assert viewer_of(request) == resolved == Archivist()


def test_each_request_resolves_its_own_viewer() -> None:
    assert viewer_of(_access(_archivist_access())) == Archivist()
    assert viewer_of(_request({})) == Public()


def test_without_a_configured_realm_it_is_keycloak(settings: Settings) -> None:
    # Production sets no realm: any other fallback would lock every login out, or let one in.
    del settings.BUNDESARCHIV_REALM
    assert isinstance(realm(), KeycloakRealm)
