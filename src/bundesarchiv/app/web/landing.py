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


def bestand_created_url(ulid: str) -> str:
    """The create-article form with the just-created Bestand pre-selected and announced."""
    return f"{reverse('artikel-neu')}?{urlencode({PARAM_COLLECTION: ulid, _ANGELEGT: _YES})}"


def copy_url(ulid: str) -> str:
    """The edit form of a fresh copy, with the cleared Signatur focused."""
    return f"{reverse('artikel-bearbeiten', args=[ulid])}?{urlencode({_FOKUS: _SIGNATUR})}"


def index_lagged_url(ulid: str) -> str:
    """The record's page, told that the search index lagged behind the write."""
    return f"{reverse('artikel-detail', args=[ulid])}?{urlencode({_INDEX: _LAGGING})}"


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
