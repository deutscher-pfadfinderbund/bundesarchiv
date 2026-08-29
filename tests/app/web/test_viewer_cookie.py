"""The production Viewer cookie: ``mint_viewer_cookie`` → ``viewer_of`` (ADR 0018).

This is the login's only durable output — after the callback, this cookie IS the viewer's identity
for every later request, so the tests below drive the real round trip (mint onto a response, read
the response's own cookie back through the seam) and then walk every way that trip can be attacked
or merely go stale: absent, empty, tampered, signed with the wrong key, signed with the DEV key,
carrying a superseded format version, past its tier's lifetime, or signed-but-garbage. Each one must
resolve to ``Public()`` and never raise.

The lifetimes are a security property of their own: an archivist's cookie must stop working after
its own 48h even though the outer verification window is a member's 30 days.

DB-free — ``RequestFactory`` requests and a real ``HttpResponse``; the default test settings are the
production ones, which define no ``VIEWER_SIGNING_KEY``, so each test declares the key it needs and
the last two declare its absence.
"""

import pytest
from django.core import signing
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, override_settings
from tests.app.web._fixtures import DEV_KEY

from bundesarchiv.app.web.viewers import (
    _DEV_VIEWER_SALT,
    _VIEWER_FORMAT_VERSION,
    _VIEWER_SALT,
    DEV_VIEWER_COOKIE,
    VIEWER_COOKIE,
    encode_viewer,
    mint_viewer_cookie,
    viewer_of,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

PROD_KEY = "test-web-viewer-signing-key"
_OTHER_KEY = "a-different-viewer-signing-key"

_ARCHIVIST_HOURS_48 = 48 * 60 * 60
_MEMBER_DAYS_30 = 30 * 24 * 60 * 60


def _mint(viewer: Viewer) -> str:
    """The cookie value a login would hand the browser for ``viewer`` — minted through the real
    function, read off a real response."""
    response = HttpResponse()
    assert mint_viewer_cookie(viewer, response) is True
    return response.cookies[VIEWER_COOKIE].value


def _sign(payload: str, *, key: str, salt: str = _VIEWER_SALT) -> str:
    return signing.TimestampSigner(key=key, salt=salt).sign(payload)


def _request_with(value: str | None, *, cookie: str = VIEWER_COOKIE) -> HttpRequest:
    request = RequestFactory().get("/")
    if value is not None:
        request.COOKIES[cookie] = value
    return request


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
@pytest.mark.parametrize(
    "viewer",
    [
        pytest.param(Archivist(), id="archivist"),
        pytest.param(Member(groups=()), id="member-without-groups"),
        pytest.param(Member(groups=("vorstand", "archiv-ag")), id="member-with-groups"),
    ],
)
def test_minted_cookie_reads_back_as_the_same_viewer(viewer: Viewer) -> None:
    assert viewer_of(_request_with(_mint(viewer))) == viewer


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_cookie_is_httponly_secure_and_samesite() -> None:
    response = HttpResponse()
    mint_viewer_cookie(Archivist(), response)
    morsel = response.cookies[VIEWER_COOKIE]
    assert morsel["httponly"] is True
    assert morsel["secure"] is True
    assert morsel["samesite"] == "Lax"


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
@pytest.mark.parametrize(
    ("viewer", "expected_max_age"),
    [
        pytest.param(Archivist(), _ARCHIVIST_HOURS_48, id="archivist-48h"),
        pytest.param(Member(groups=()), _MEMBER_DAYS_30, id="member-30d"),
    ],
)
def test_cookie_lifetime_per_tier(viewer: Viewer, expected_max_age: int) -> None:
    response = HttpResponse()
    mint_viewer_cookie(viewer, response)
    assert int(response.cookies[VIEWER_COOKIE]["max-age"]) == expected_max_age


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_the_cookie_name_is_host_locked() -> None:
    # __Host- makes shadowing impossible: a sibling host on the registrable domain (Keycloak lives
    # on one) can otherwise set Domain=.example/viewer=<junk>, which the browser sends alongside the
    # real cookie and Django resolves to the junk — a login loop the visitor cannot clear.
    response = HttpResponse()
    mint_viewer_cookie(Archivist(), response)
    morsel = response.cookies[VIEWER_COOKIE]
    assert VIEWER_COOKIE.startswith("__Host-")
    assert morsel["secure"] is True and morsel["path"] == "/" and not morsel["domain"]


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_no_cookie_is_public() -> None:
    assert viewer_of(_request_with(None)) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_empty_cookie_is_public() -> None:
    assert viewer_of(_request_with("")) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_tampered_cookie_is_public() -> None:
    cookie = _mint(Archivist())
    tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")
    assert viewer_of(_request_with(tampered)) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_cookie_signed_with_another_key_is_public() -> None:
    cookie = _sign(f"{_VIEWER_FORMAT_VERSION}:{encode_viewer(Archivist())}", key=_OTHER_KEY)
    assert viewer_of(_request_with(cookie)) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY, DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_cookie_signed_with_the_dev_key_is_public() -> None:
    # Key confusion across the two seams: the dev switcher's key must not mint production identity,
    # not even under the dev salt it normally uses.
    dev_salted = _sign(encode_viewer(Archivist()), key=DEV_KEY, salt=_DEV_VIEWER_SALT)
    assert viewer_of(_request_with(dev_salted)) == Public()
    prod_salted = _sign(f"{_VIEWER_FORMAT_VERSION}:{encode_viewer(Archivist())}", key=DEV_KEY)
    assert viewer_of(_request_with(prod_salted)) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY, DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_production_cookie_signed_with_the_prod_key_is_not_read_by_the_dev_seam() -> None:
    # The mirror of the above: the production key must not mint a dev-switcher identity either.
    minted = _sign(f"{_VIEWER_FORMAT_VERSION}:{encode_viewer(Archivist())}", key=PROD_KEY)
    assert viewer_of(_request_with(minted, cookie=DEV_VIEWER_COOKIE)) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY, DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_the_minted_cookie_wins_over_a_dev_cookie() -> None:
    # Both seams live at once only in a mixed configuration; the real login is the stronger claim.
    request = _request_with(_mint(Member(groups=("vorstand",))))
    request.COOKIES[DEV_VIEWER_COOKIE] = _sign(
        encode_viewer(Archivist()), key=DEV_KEY, salt=_DEV_VIEWER_SALT
    )
    assert viewer_of(request) == Member(groups=("vorstand",))


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_superseded_format_version_is_public() -> None:
    # The ADR 0018 emergency lever: bumping the version must invalidate outstanding cookies, so a
    # correctly signed cookie carrying any other version is worthless.
    cookie = _sign(f"v0:{encode_viewer(Archivist())}", key=PROD_KEY)
    assert viewer_of(_request_with(cookie)) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_versionless_cookie_is_public() -> None:
    cookie = _sign(encode_viewer(Archivist()), key=PROD_KEY)
    assert viewer_of(_request_with(cookie)) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_signed_garbage_payload_is_public() -> None:
    cookie = _sign(f"{_VIEWER_FORMAT_VERSION}:superuser", key=PROD_KEY)
    assert viewer_of(_request_with(cookie)) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_expired_cookie_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    # Shrink the outer verification window to a negative one: every cookie then reads as expired
    # (SignatureExpired is a BadSignature) without forging timestamps or waiting 30 days.
    monkeypatch.setattr("bundesarchiv.app.web.viewers._MEMBER_MAX_AGE", -1)
    assert viewer_of(_request_with(_mint(Member(groups=())))) == Public()


@override_settings(VIEWER_SIGNING_KEY=PROD_KEY)
def test_archivist_cookie_expires_on_its_own_shorter_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The 48h archivist lifetime is enforced on READ, not merely offered to the browser: an
    # archivist cookie past 48h falls closed while a member cookie of the same age still verifies.
    archivist = _mint(Archivist())
    member = _mint(Member(groups=()))
    monkeypatch.setattr("bundesarchiv.app.web.viewers._ARCHIVIST_MAX_AGE", -1)
    assert viewer_of(_request_with(archivist)) == Public()
    assert viewer_of(_request_with(member)) == Member(groups=())


def test_without_a_signing_key_nothing_is_minted() -> None:
    # Production settings define no key until the deploy supplies one: minting must report failure
    # and set no cookie at all, so a callback cannot hand out an unsigned identity.
    response = HttpResponse()
    assert mint_viewer_cookie(Archivist(), response) is False
    assert VIEWER_COOKIE not in response.cookies


def test_without_a_signing_key_a_valid_cookie_is_public() -> None:
    cookie = _sign(f"{_VIEWER_FORMAT_VERSION}:{encode_viewer(Archivist())}", key=PROD_KEY)
    assert viewer_of(_request_with(cookie)) == Public()
