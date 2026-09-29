"""``viewer_of(request)`` — the request→Viewer trust boundary (Part 4.4), through the dev cookie.

The seam under test is the ONE function the web layer calls to answer *who is asking*. The
FAIL-CLOSED contract: only a cookie correctly signed with the DEDICATED dev key and salt,
unexpired, and parsing to a known viewer shape yields a non-Public viewer — every other input
(no cookie, wrong key or salt, tampered signature, expired, signed garbage, a cookie the app no
longer reads) resolves to ``Public()`` and never raises. The payload codec's adversarial round trip
lives here too. The token cookies have their own file (``test_token_viewer.py``).

These tests are DB-free: they build requests with ``RequestFactory`` and drive the signer directly.
They take no corpus fixture: the seam reads exactly one setting and never a store, so each test
declares that key itself — and the last test declares its ABSENCE, which a shared settings block
cannot express.
"""

import pytest
from django.core import signing
from django.http import HttpRequest
from django.test import RequestFactory, override_settings
from tests.app.web._fixtures import DEV_KEY

from bundesarchiv.app.web.viewers import (
    _DEV_VIEWER_SALT,
    DEV_VIEWER_COOKIE,
    _parse_viewer,
    encode_viewer,
    viewer_of,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

# A stand-in for a production SECRET_KEY: prod settings define none, so we supply one purely to
# simulate the key-confusion scenario (a cookie signed with prod's key must NOT verify as a dev one).
_PROD_SECRET_KEY = "totally-different-production-secret-key"

# Stands in for the deployment's ``VIEWER_SIGNING_KEY``, which prod settings leave unset.
_VIEWER_KEY = "test-web-viewer-signing-key"


def _request_with_cookie(value: str | None) -> HttpRequest:
    request = RequestFactory().get("/")
    if value is not None:
        request.COOKIES[DEV_VIEWER_COOKIE] = value
    return request


def _sign(payload: str, *, key: str, salt: str = _DEV_VIEWER_SALT) -> str:
    """Sign a raw payload the way the dev switcher does (same signer class, salt, and key handling),
    so the test constructs cookies through the identical code path viewer_of verifies against."""
    return signing.TimestampSigner(key=key, salt=salt).sign(payload)


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_no_cookie_is_public() -> None:
    assert viewer_of(_request_with_cookie(None)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_empty_cookie_is_public() -> None:
    assert viewer_of(_request_with_cookie("")) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_valid_archivist_cookie() -> None:
    cookie = _sign(encode_viewer(Archivist()), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Archivist()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_valid_public_cookie() -> None:
    cookie = _sign(encode_viewer(Public()), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_valid_member_no_groups() -> None:
    cookie = _sign(encode_viewer(Member(groups=())), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Member(groups=())


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_valid_member_single_group() -> None:
    cookie = _sign(encode_viewer(Member(groups=("vorstand",))), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Member(groups=("vorstand",))


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_valid_member_multiple_groups() -> None:
    cookie = _sign(encode_viewer(Member(groups=("vorstand", "archiv-ag"))), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Member(groups=("vorstand", "archiv-ag"))


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_tampered_signature_is_public() -> None:
    cookie = _sign(encode_viewer(Archivist()), key=DEV_KEY)
    tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")  # flip the last signature char
    assert viewer_of(_request_with_cookie(tampered)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_expired_cookie_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force every cookie to read as expired by shrinking the seam's max_age to a negative window;
    # TimestampSigner.unsign then raises SignatureExpired (a BadSignature) -> Public. This exercises
    # viewer_of's real expiry branch without sleeping 12h or forging timestamp bytes.
    monkeypatch.setattr("bundesarchiv.app.web.viewers._DEV_VIEWER_MAX_AGE", -1)
    cookie = _sign(encode_viewer(Archivist()), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("superuser", id="unknown-shape"),
        pytest.param("archivist", id="unnamed-archivist"),
        pytest.param("v3:archivist:anna", id="versioned-payload"),
    ],
)
def test_signed_garbage_shape_is_public(payload: str) -> None:
    # Correctly signed with the RIGHT key, but the payload is not a known viewer shape.
    assert viewer_of(_request_with_cookie(_sign(payload, key=DEV_KEY))) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_the_dev_key_under_another_salt_is_public() -> None:
    cookie = _sign(encode_viewer(Archivist()), key=DEV_KEY, salt="viewer")
    assert viewer_of(_request_with_cookie(cookie)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_cookie_signed_with_prod_secret_key_is_public() -> None:
    # THE key-confusion test: a cookie signed with the production SECRET_KEY must be worthless.
    cookie = _sign(encode_viewer(Archivist()), key=_PROD_SECRET_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


def test_no_dev_key_configured_is_public() -> None:
    # Under production settings (no DEV_VIEWER_SIGNING_KEY) the seam falls closed even for a cookie
    # that WOULD verify under a dev key — there is simply no key to verify against. No
    # override_settings here: the default test settings are prod (settings.py), which defines none.
    cookie = _sign(encode_viewer(Archivist()), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


@override_settings(VIEWER_SIGNING_KEY=_VIEWER_KEY, DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_a_value_signed_with_the_viewer_signing_key_is_public_in_the_dev_slot() -> None:
    # The production key signs only the transient login state; it must not mint a dev identity.
    cookie = _sign(encode_viewer(Archivist()), key=_VIEWER_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


@override_settings(VIEWER_SIGNING_KEY=_VIEWER_KEY, DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_a_stale_production_viewer_cookie_is_public() -> None:
    # The signed ``__Host-viewer`` cookie was removed (ADR 0018). One still sitting in a browser,
    # signed exactly as it used to be minted, must resolve as if it were absent.
    stale = signing.TimestampSigner(key=_VIEWER_KEY, salt="viewer").sign("v3:archivist:anna")
    request = RequestFactory().get("/")
    request.COOKIES["__Host-viewer"] = stale
    assert viewer_of(request) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
@pytest.mark.parametrize(
    "viewer",
    [
        pytest.param(Archivist(username="jürgen: 50% ,x"), id="archivist-with-a-hostile-name"),
        pytest.param(Member(groups=("Sales, EU",)), id="group-with-a-delimiter"),
    ],
)
def test_hostile_names_survive_the_real_cookie(viewer: Viewer) -> None:
    cookie = _sign(encode_viewer(viewer), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == viewer


@pytest.mark.parametrize(
    "username",
    [
        pytest.param("anna", id="plain"),
        pytest.param("", id="empty"),
        pytest.param("a:b", id="colon"),
        pytest.param("a,b", id="comma"),
        pytest.param("%3A100%", id="percent"),
        pytest.param(" anna ", id="leading-and-trailing-whitespace"),
        pytest.param("jürgen.müller", id="unicode"),
        pytest.param("member:vorstand", id="another-viewer-payload"),
    ],
)
def test_a_username_survives_the_payload_verbatim(username: str) -> None:
    # The username is who a save is attributed to (ADR 0019): one that round-trips to another
    # string credits the change to somebody else.
    archivist = Archivist(username=username)
    assert _parse_viewer(encode_viewer(archivist)) == archivist


@pytest.mark.parametrize(
    "groups",
    [
        pytest.param(("Sales, EU",), id="comma-and-space"),
        pytest.param(("a,b",), id="comma"),
        pytest.param(("a:b",), id="colon"),
        pytest.param(("50%",), id="percent"),
        pytest.param(("Gruppe Nord",), id="space"),
        pytest.param(("Überregional",), id="unicode"),
        pytest.param(("Sales, EU", "a:b", "50%", "Überregional"), id="mixed"),
    ],
)
def test_group_names_survive_the_payload_verbatim(groups: tuple[str, ...]) -> None:
    # Keycloak group names may contain the payload's own delimiters, and a group name IS an
    # authorization scope: a name that round-trips to something else silently moves the member
    # between scopes. The encoding must be total over arbitrary names.
    member = Member(groups=groups)
    assert _parse_viewer(encode_viewer(member)) == member


def test_a_delimiter_free_group_encodes_to_itself() -> None:
    # The escaping must not change the payload for any group name that exists today, or every
    # outstanding cookie would become unreadable.
    assert encode_viewer(Member(groups=("vorstand", "archiv-ag"))) == "member:vorstand,archiv-ag"


def test_empty_group_segments_are_dropped() -> None:
    assert _parse_viewer("member:a,,b") == Member(groups=("a", "b"))


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_the_viewer_is_resolved_once_per_request() -> None:
    # Four call sites ask viewer_of the same question per request. They must not be able to answer
    # it differently: the first resolution fixes the request's identity, and a cookie swapped
    # underneath it (which no real request can do — set and clear happen on responses) is ignored.
    request = _request_with_cookie(_sign(encode_viewer(Archivist()), key=DEV_KEY))
    resolved = viewer_of(request)
    request.COOKIES[DEV_VIEWER_COOKIE] = _sign(encode_viewer(Member(groups=("v",))), key=DEV_KEY)
    assert viewer_of(request) == resolved == Archivist()


@override_settings(DEV_VIEWER_SIGNING_KEY=DEV_KEY)
def test_each_request_resolves_its_own_viewer() -> None:
    cookie = _sign(encode_viewer(Archivist()), key=DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Archivist()
    assert viewer_of(_request_with_cookie(None)) == Public()
