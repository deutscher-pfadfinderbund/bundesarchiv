"""The dev-realm login every browser-free and browser suite shares: the key and the token cookies a
login as a viewer leaves."""

from bundesarchiv.app.web.dev_realm import DevRealm, claims_of
from bundesarchiv.app.web.viewers import login_cookies
from bundesarchiv.domain.viewer import Archivist, Member, Viewer

DEV_KEY = "test-web-dev-viewer-key"


def viewer_cookies(viewer: Viewer | None) -> dict[str, str]:
    """The token cookies a dev-realm login as ``viewer`` leaves, minted under the settings in force;
    none for ``Public()`` or ``None`` (an anonymous visitor)."""
    if not isinstance(viewer, Archivist | Member):
        return {}
    tokens = DevRealm().mint_tokens(claims_of(viewer))
    assert tokens is not None, "no DEV_VIEWER_SIGNING_KEY: run under settings_for"
    cookies = login_cookies()
    return {cookies.access: tokens.access, cookies.refresh: tokens.refresh}
