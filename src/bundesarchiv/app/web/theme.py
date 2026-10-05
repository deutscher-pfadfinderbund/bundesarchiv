"""The viewer's light/dark choice: the "theme" cookie that ``theme.js`` sets or deletes. Without
one the page follows the system; with one the server's render already carries the scheme, so a
saved choice paints from the first frame."""

from django.http import HttpRequest

COOKIE = "theme"
_SCHEMES = frozenset({"light", "dark"})


def theme(request: HttpRequest) -> dict[str, str]:
    """Context processor: ``theme`` is the scheme the cookie fixes, or "" to follow the system."""
    value = request.COOKIES.get(COOKIE, "")
    return {"theme": value if value in _SCHEMES else ""}
