"""The state a redirect hands the next page: built and parsed here, nowhere else.

Keys are German and stay so (they are URLs). Every value read back is closed: a flag compares
against one literal, a Bestand id is checked here against the real set. No text from the URL is
ever shown."""

from urllib.parse import urlencode

from django.http import HttpRequest
from django.urls import reverse

from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.browse import PARAM_COLLECTION

_ANGELEGT, _FOKUS, _INDEX = "angelegt", "fokus", "index"
_YES, _SIGNATUR, _LAGGING = "1", "signatur", "lagging"

#: The keys that hand state to ONE page: no link built from that page's address may carry them on.
FLAG_KEYS = frozenset({_ANGELEGT, _FOKUS, _INDEX})
#: What the address-clearing script (``list_address.js``) spells; pinned by a test.
LAG_FLAG = (_INDEX, _LAGGING)


def bestand_created_url(ulid: str) -> str:
    """The create-article form with the just-created Bestand pre-selected and announced."""
    return f"{reverse('article-create')}?{urlencode({PARAM_COLLECTION: ulid, _ANGELEGT: _YES})}"


def copy_url(ulid: str) -> str:
    """The edit form of a fresh copy, with the cleared Signatur focused."""
    return f"{reverse('article-edit', args=[ulid])}?{urlencode({_FOKUS: _SIGNATUR})}"


def noting_lag(url: str, index_updated: bool) -> str:
    """``url``, told when the search index lagged behind the write that leads there (ADR 0014)."""
    if index_updated:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urlencode({_INDEX: _LAGGING})}"


def preselected_bestand(request: HttpRequest, bestand: BestandChooser) -> str:
    """The pre-selected Bestand's ulid if it is a real one, else "" (a bogus id is no oracle)."""
    ulid = request.GET.get(PARAM_COLLECTION, "").strip()
    return ulid if bestand.accepts(ulid) else ""


def created_bestand_name(request: HttpRequest, bestand: BestandChooser) -> str:
    """The name to announce as just created: the pre-selected real Bestand's, or "" without one."""
    if request.GET.get(_ANGELEGT) != _YES:
        return ""
    return bestand.name_of(preselected_bestand(request, bestand)) or ""


def focus_signatur(request: HttpRequest) -> bool:
    return request.GET.get(_FOKUS) == _SIGNATUR


def index_lagging(request: HttpRequest) -> bool:
    return request.GET.get(_INDEX) == _LAGGING
