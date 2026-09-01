"""Shared response assertions for the web suite: the deny and the anonymous gate's bounce.

The single definition of what a deny looks like over HTTP, so every per-route test pins the
same contract and there is ONE edit point if it ever changes (e.g. when a styled access-denied
page ships). Relaxed from the byte-identical-404 law (owner ruling 2026-08, see
docs/requirements/owner-interview-2026-08.md): the byte-for-byte shape comparison is gone;
what remains is that a deny is a 404 whose body reveals nothing — production emits the shared
empty ``_not_found()``, so an empty body is a true invariant, not a snapshot.
"""

from typing import Protocol
from urllib.parse import parse_qs, urlsplit


class _Response(Protocol):
    """The two fields a deny assert reads — covers HttpResponse and the test client's response."""

    status_code: int
    content: bytes


def assert_denied(response: _Response, ctx: str = "") -> None:
    """A deny/absence response: status 404 and an empty body (nothing revealed)."""
    label = f" [{ctx}]" if ctx else ""
    assert response.status_code == 404, f"expected a 404 deny{label}, got {response.status_code}"
    assert response.content == b"", f"a deny must not reveal content{label}"


def assert_login_target(url: str, next_path: str, ctx: str = "") -> None:
    """The anonymous gate's bounce target (ADR 0018): the login route, carrying the path the
    visitor was going to. Takes the URL apart instead of re-spelling production's percent encoding
    by hand — the spelling is not the contract, and a second encoder drifts from the first."""
    label = f" [{ctx}]" if ctx else ""
    target = urlsplit(url)
    assert target.path == "/login", f"expected the login route{label}, got {url}"
    assert parse_qs(target.query).get("next") == [next_path], (
        f"the login target must carry next={next_path}{label}, got {url}"
    )
