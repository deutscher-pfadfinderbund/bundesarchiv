"""``viewer_of(request)`` — the request→Viewer trust boundary (Part 4.4).

The seam under test is the ONE function the web layer calls to answer *who is asking*. Every test
here asserts the FAIL-CLOSED contract: only a cookie correctly signed with the DEDICATED dev key,
unexpired, and parsing to a known viewer shape yields a non-Public viewer — every other input
(no cookie, wrong key, tampered signature, expired, signed garbage) resolves to ``Public()`` and
never raises. THE key-confusion test pins that the production ``SECRET_KEY`` cannot sign a valid
dev cookie.

These tests are DB-free: they build requests with ``RequestFactory`` and drive the signer directly.
"""

import pytest
from django.core import signing
from django.http import HttpRequest
from django.test import RequestFactory, override_settings

from bundesarchiv.app.web.viewers import (
    _DEV_VIEWER_SALT,
    DEV_VIEWER_COOKIE,
    encode_viewer,
    viewer_of,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public

_DEV_KEY = "test-dev-viewer-key"
# A stand-in for a production SECRET_KEY: prod settings define none, so we supply one purely to
# simulate the key-confusion scenario (a cookie signed with prod's key must NOT verify as a dev one).
_PROD_SECRET_KEY = "totally-different-production-secret-key"


def _request_with_cookie(value: str | None) -> HttpRequest:
    request = RequestFactory().get("/")
    if value is not None:
        request.COOKIES[DEV_VIEWER_COOKIE] = value
    return request


def _sign(payload: str, *, key: str) -> str:
    """Sign a raw payload the way the dev switcher does (same signer class, salt, and key handling),
    so the test constructs cookies through the identical code path viewer_of verifies against."""
    return signing.TimestampSigner(key=key, salt=_DEV_VIEWER_SALT).sign(payload)


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_no_cookie_is_public() -> None:
    assert viewer_of(_request_with_cookie(None)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_empty_cookie_is_public() -> None:
    assert viewer_of(_request_with_cookie("")) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_valid_archivist_cookie() -> None:
    cookie = _sign(encode_viewer(Archivist()), key=_DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Archivist()


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_valid_public_cookie() -> None:
    cookie = _sign(encode_viewer(Public()), key=_DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_valid_member_no_groups() -> None:
    cookie = _sign(encode_viewer(Member(groups=())), key=_DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Member(groups=())


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_valid_member_single_group() -> None:
    cookie = _sign(encode_viewer(Member(groups=("vorstand",))), key=_DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Member(groups=("vorstand",))


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_valid_member_multiple_groups() -> None:
    cookie = _sign(encode_viewer(Member(groups=("vorstand", "archiv-ag"))), key=_DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Member(groups=("vorstand", "archiv-ag"))


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_tampered_signature_is_public() -> None:
    cookie = _sign(encode_viewer(Archivist()), key=_DEV_KEY)
    tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")  # flip the last signature char
    assert viewer_of(_request_with_cookie(tampered)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_expired_cookie_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force every cookie to read as expired by shrinking the seam's max_age to a negative window;
    # TimestampSigner.unsign then raises SignatureExpired (a BadSignature) -> Public. This exercises
    # viewer_of's real expiry branch without sleeping 12h or forging timestamp bytes.
    monkeypatch.setattr("bundesarchiv.app.web.viewers._DEV_VIEWER_MAX_AGE", -1)
    cookie = _sign(encode_viewer(Archivist()), key=_DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_signed_garbage_shape_is_public() -> None:
    # Correctly signed with the RIGHT key, but the payload is not a known viewer shape.
    cookie = _sign("superuser", key=_DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


@override_settings(DEV_VIEWER_SIGNING_KEY=_DEV_KEY)
def test_cookie_signed_with_prod_secret_key_is_public() -> None:
    # THE key-confusion test: a cookie signed with the production SECRET_KEY must be worthless.
    cookie = _sign(encode_viewer(Archivist()), key=_PROD_SECRET_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()


def test_no_dev_key_configured_is_public() -> None:
    # Under production settings (no DEV_VIEWER_SIGNING_KEY) the seam falls closed even for a cookie
    # that WOULD verify under a dev key — there is simply no key to verify against. No
    # override_settings here: the default test settings are prod (settings.py), which defines none.
    cookie = _sign(encode_viewer(Archivist()), key=_DEV_KEY)
    assert viewer_of(_request_with_cookie(cookie)) == Public()
