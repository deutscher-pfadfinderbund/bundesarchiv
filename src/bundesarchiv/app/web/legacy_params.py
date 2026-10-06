"""Old German query params: a GET or HEAD naming one gets a 301 to its English URL.

The params and their fixed values were German before 2026-10-06 (English in code); links and
bookmarks from then keep working, as the old paths do. The redirect, not an in-request rewrite,
makes the address bar, ``next`` and every link built from the request English. Only the query
changes: same path, same param order, an English key already present wins over its old twin.
Other methods pass untouched: a 301 would turn a POST into a GET.
"""

from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode

from django.http import HttpRequest, HttpResponseBase, HttpResponsePermanentRedirect

from bundesarchiv.app.web import browse, browse_views, landing
from bundesarchiv.index.query import SortOrder

_KEYS = {
    "bestand": browse.PARAM_COLLECTION,
    "medienart": browse.PARAM_MEDIA_TYPE,
    "dokumenttyp": browse.PARAM_DOCUMENT_TYPE,
    "schlagwort": browse.PARAM_TAG,
    "jahrzehnt": browse.PARAM_DECADE,
    "ohne_datum": browse.PARAM_DATELESS,
    "von": browse.PARAM_DATE_FROM,
    "bis": browse.PARAM_DATE_TO,
    "entwuerfe": browse.PARAM_DRAFTS,
    "sortierung": browse.PARAM_SORT,
    "seite": browse.PARAM_PAGE,
    "auswahl": browse.PARAM_SELECTION,
    "artikel": browse_views._PANE_PARAM,
    "angelegt": landing._CREATED,
    "fokus": landing._FOCUS,
}
_SORTS: dict[str, SortOrder] = {
    "relevanz": "relevance",
    "signatur": "ref_code",
    "datierung": "date",
    "titel": "title",
    "hinzugefuegt": "added",
}
_FOCUS = {"signatur": landing._REF_CODE}


def _value(key: str, value: str) -> str:
    """``value`` in English where it is an old fixed value of ``key``, else verbatim."""
    if key == browse.PARAM_SORT:
        # read as browse._parse_sort reads it, so a padded or upper-case old label maps too
        name = value.strip().lower()
        minus = "-" if name.startswith("-") else ""
        old = name.removeprefix("-")
        return minus + _SORTS[old] if old in _SORTS else value
    if key == landing._FOCUS:
        return _FOCUS.get(value, value)
    return value


def english_query(query: str) -> str | None:
    """``query`` with every old key and value in English, or ``None`` when it holds none."""
    pairs = parse_qsl(query, keep_blank_values=True)
    present = {key for key, _ in pairs}
    english = [
        (_KEYS.get(key, key), _value(_KEYS.get(key, key), value))
        for key, value in pairs
        if _KEYS.get(key) not in present
    ]
    return urlencode(english) if english != pairs else None


class LegacyParamsMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if request.method in ("GET", "HEAD"):
            query = english_query(request.META.get("QUERY_STRING", ""))
            if query is not None:
                return HttpResponsePermanentRedirect(f"{request.path}?{query}")
        return self.get_response(request)
