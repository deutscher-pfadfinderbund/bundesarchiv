"""The dev realm: it signs in exactly what it minted itself, under the dev key, and nothing else."""

from collections.abc import Callable, Mapping
from urllib.parse import parse_qs, urlsplit

import pytest
from pytest_django.fixtures import Settings
from tests.app.web._fixtures import DEV_KEY

from bundesarchiv.app.web.dev_realm import AUTHORIZE_PATH, Asked, DevRealm
from bundesarchiv.app.web.oidc import viewer_from_claims
from bundesarchiv.domain.viewer import Archivist

_CLAIMS: Mapping[str, object] = {
    "preferred_username": "anna",
    "realm_access": {"roles": ["Bundesarchiv"]},
}
_REDIRECT = "http://testserver/oidc/callback"


@pytest.fixture(autouse=True)
def _dev_key(settings: Settings) -> None:
    settings.DEV_VIEWER_SIGNING_KEY = DEV_KEY


def _tampered(value: str) -> str:
    return value[:-1] + ("a" if value[-1] != "a" else "b")


def test_a_minted_code_logs_in_as_its_claims() -> None:
    realm = DevRealm()
    code = realm.mint_code(_CLAIMS, nonce="n1")
    assert code is not None
    tokens = realm.fetch_tokens(code=code, nonce="n1", redirect_uri=_REDIRECT)
    assert tokens is not None
    claims = realm.verify_access(tokens.access)
    assert claims is not None
    assert viewer_from_claims(claims) == Archivist(username="anna")


def test_a_refresh_token_reissues_a_current_access_token() -> None:
    expired = DevRealm(lifetime=-1).mint_tokens(_CLAIMS)
    assert expired is not None
    realm = DevRealm()
    assert realm.verify_access(expired.access) is None
    renewed = realm.refresh(expired.refresh)
    assert renewed is not None
    assert realm.verify_access(renewed.access) == renewed.claims


def test_the_authorization_url_is_the_dev_page_carrying_the_login() -> None:
    url = DevRealm().authorization_url(state="s1", nonce="n1", redirect_uri=_REDIRECT)
    assert url is not None
    parts = urlsplit(url)
    assert parts.path == AUTHORIZE_PATH
    assert parse_qs(parts.query) == {"state": ["s1"], "nonce": ["n1"], "redirect_uri": [_REDIRECT]}


def test_logout_returns_to_the_post_logout_uri() -> None:
    realm = DevRealm()
    assert realm.logout_url(refresh_token=None, post_logout_redirect_uri="http://x/") == "http://x/"


def test_every_call_is_recorded() -> None:
    asked: Asked = []
    DevRealm(asked=asked).refresh("r1")
    assert asked == [("refresh", {"refresh_token": "r1"})]


def test_a_code_bound_to_another_nonce_logs_nobody_in() -> None:
    realm = DevRealm()
    code = realm.mint_code(_CLAIMS, nonce="n1")
    assert code is not None
    assert realm.fetch_tokens(code=code, nonce="n2", redirect_uri=_REDIRECT) is None


# --- every other value: nothing ------------------------------------------------------------------


def _code(realm: DevRealm) -> str:
    code = realm.mint_code(_CLAIMS, nonce="n1")
    assert code is not None
    return code


def _tokens(realm: DevRealm) -> tuple[str, str]:
    tokens = realm.mint_tokens(_CLAIMS)
    assert tokens is not None
    return tokens.access, tokens.refresh


def _access(realm: DevRealm) -> str:
    return _tokens(realm)[0]


def _refresh(realm: DevRealm) -> str:
    return _tokens(realm)[1]


def _fetch(code: str) -> object:
    return DevRealm().fetch_tokens(code=code, nonce="n1", redirect_uri=_REDIRECT)


def _verify(token: str) -> object:
    return DevRealm().verify_access(token)


def _renew(token: str) -> object:
    return DevRealm().refresh(token)


@pytest.mark.parametrize(
    ("minted", "use"),
    [
        pytest.param(_code, _fetch, id="code"),
        pytest.param(_access, _verify, id="access"),
        pytest.param(_refresh, _renew, id="refresh"),
    ],
)
@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param("another-key", id="another-key"),
        pytest.param("tampered", id="tampered"),
    ],
)
def test_a_value_it_did_not_mint_is_refused(
    settings: Settings,
    minted: Callable[[DevRealm], str],
    use: Callable[[str], object],
    spoil: str,
) -> None:
    if spoil == "another-key":
        settings.DEV_VIEWER_SIGNING_KEY = "another-key"
        value = minted(DevRealm())
        settings.DEV_VIEWER_SIGNING_KEY = DEV_KEY
    else:
        value = _tampered(minted(DevRealm()))
    assert use(value) is None


@pytest.mark.parametrize(
    ("minted", "use"),
    [
        pytest.param(_code, _fetch, id="code"),
        pytest.param(_access, _verify, id="access"),
    ],
)
def test_an_expired_value_is_refused(
    minted: Callable[[DevRealm], str], use: Callable[[str], object]
) -> None:
    assert use(minted(DevRealm(lifetime=-1))) is None


@pytest.mark.parametrize(
    ("minted", "use"),
    [
        pytest.param(_refresh, _verify, id="refresh-as-access"),
        pytest.param(_code, _verify, id="code-as-access"),
        pytest.param(_access, _renew, id="access-as-refresh"),
        pytest.param(_access, _fetch, id="access-as-code"),
    ],
)
def test_one_kind_of_value_is_never_another(
    minted: Callable[[DevRealm], str], use: Callable[[str], object]
) -> None:
    assert use(minted(DevRealm())) is None


@pytest.mark.parametrize("garbage", ["", "x", "a:b:c", "ü"])
@pytest.mark.parametrize("use", [_fetch, _verify, _renew])
def test_garbage_is_refused(use: Callable[[str], object], garbage: str) -> None:
    assert use(garbage) is None


def test_without_the_dev_key_it_mints_and_accepts_nothing(settings: Settings) -> None:
    realm = DevRealm()
    code, (access, refresh) = _code(realm), _tokens(realm)
    settings.DEV_VIEWER_SIGNING_KEY = None
    assert realm.mint_code(_CLAIMS, nonce="n1") is None
    assert realm.mint_tokens(_CLAIMS) is None
    assert realm.authorization_url(state="s", nonce="n1", redirect_uri=_REDIRECT) is None
    assert realm.fetch_tokens(code=code, nonce="n1", redirect_uri=_REDIRECT) is None
    assert realm.verify_access(access) is None
    assert realm.refresh(refresh) is None
    assert realm.logout_url(refresh_token=refresh, post_logout_redirect_uri="http://x/") is None
