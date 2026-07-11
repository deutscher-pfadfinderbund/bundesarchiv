"""Pure URL-as-state layer for the archivist workbench (Part 4.5-MVP).

The workbench is ONE form whose complete state lives in the query string (plan §4.5, ideas §1.1):
German param keys map to the English ``SearchFilters`` the index layer understands. This module is
deliberately IO-free and request-free — it is a total function over a plain string mapping — so the
whole URL-as-state contract (parse, link-build, chip-remove, pagination) is unit-testable without a
database or a request cycle, and the views stay thin.

Two halves:

- ``parse_query`` — strict-but-total: every field parses to its typed value or falls to that field's
  default (garbage never raises, never 500s — plan §4.5). Text comes from ``q``; the rest build a
  ``SearchFilters`` + sort + page.
- The link helpers (``with_param`` / ``without_param`` / ``page_query``) — pure query-string
  algebra the templates emit for facet clicks, sidebar removal and pagination. Adding or removing a
  facet resets ``seite`` (the result set changed, so the old page number is stale).

No visibility logic lives here (that is ``search`` / ``can_view``); this module only shuffles
strings between the URL and ``SearchFilters``.
"""

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlencode

from bundesarchiv.index.query import SearchFilters, SortOrder

# German query-string keys, mapped to what they mean. The template, the parser and the chip builder
# all read this ONE vocabulary so a rename can't drift between them.
PARAM_Q = "q"
PARAM_COLLECTION = "bestand"
PARAM_MEDIA_TYPE = "medienart"
PARAM_DOCUMENT_TYPE = "dokumenttyp"
PARAM_TAG = "schlagwort"
PARAM_DECADE = "jahrzehnt"
PARAM_DATELESS = "ohne_datum"
PARAM_DATE_FROM = "von"
PARAM_DATE_TO = "bis"
PARAM_SORT = "sortierung"
PARAM_PAGE = "seite"

#: The whitelist of SEARCH-state query keys — the full set the workbench URL carries as its state.
#: Deliberately excludes ``artikel`` (pane selection) and ``auswahl`` (bulk selection): neither is
#: search state. ``sanitize_query`` keeps ONLY these, so a return-state string can never smuggle a
#: pane/bulk param or an arbitrary key back into a link.
_SEARCH_PARAMS: frozenset[str] = frozenset(
    {
        PARAM_Q,
        PARAM_COLLECTION,
        PARAM_MEDIA_TYPE,
        PARAM_DOCUMENT_TYPE,
        PARAM_TAG,
        PARAM_DECADE,
        PARAM_DATELESS,
        PARAM_DATE_FROM,
        PARAM_DATE_TO,
        PARAM_SORT,
        PARAM_PAGE,
    }
)


def sanitize_query(raw: str) -> str:
    """Re-serialize an untrusted return-state query string to a CLEAN one carrying only known
    search params (4.6 §2, the ``zurueck`` return link). Parse the raw string, keep only
    ``_SEARCH_PARAMS`` with a non-empty value, and ``urlencode`` the result — so a value is never
    echoed raw (no reflection / open-redirect surface) and any unknown / pane / bulk key is dropped.
    Returns ``""`` when nothing survives (the caller then falls back to a bare ``/``)."""
    from urllib.parse import parse_qsl

    kept = {
        k: v for k, v in parse_qsl(raw, keep_blank_values=False) if k in _SEARCH_PARAMS and v != ""
    }
    return urlencode(kept)


#: The workbench's fixed result-page size. ONE constant shared by the view's ``search`` call and
#: ``has_next_page``, so the pager arithmetic can never drift from the window actually fetched.
PAGE_SIZE = 50

#: German sort labels -> the ``SortOrder`` the index understands. An unknown value falls to the
#: default (relevance), so a hand-edited URL can never 500 the sort.
_SORT_BY_LABEL: dict[str, SortOrder] = {
    "relevanz": "relevance",
    "signatur": "ref_code",
    "datierung": "date",
    "titel": "title",
}
_DEFAULT_SORT: SortOrder = "relevance"

#: Truthy spellings for the boolean "Ohne Datum" toggle. Anything else (incl. absence) is False.
_TRUTHY = frozenset({"1", "true", "ja", "on"})


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """The workbench request state, parsed from the query string: the free text, the typed
    ``SearchFilters``, the sort (+ direction) and the (1-based) page. Everything ``search`` needs."""

    text: str | None
    filters: SearchFilters
    sort: SortOrder
    descending: bool
    page: int


#: Descending is encoded as a ``-`` prefix on the German ``sortierung`` label ("-signatur"), so the
#: whole sort state stays in one URL param. An unknown/blank label falls to the default (relevance),
#: which has no direction — the header cycle only ever sets a column label ± the prefix.
_SORT_DESC_PREFIX = "-"


def _parse_sort(raw: str | None) -> tuple[SortOrder, bool]:
    """Parse ``sortierung`` into (SortOrder, descending). A leading ``-`` means descending; the rest
    maps through ``_SORT_BY_LABEL``. An unknown label -> (default, ascending) — garbage never 500s."""
    value = (raw or "").strip().lower()
    descending = value.startswith(_SORT_DESC_PREFIX)
    label = value[1:] if descending else value
    sort = _SORT_BY_LABEL.get(label, _DEFAULT_SORT)
    # relevance has no direction; a stray "-relevanz" collapses to plain relevance (not descending).
    if sort == _DEFAULT_SORT:
        return _DEFAULT_SORT, False
    return sort, descending


def parse_query(params: Mapping[str, str]) -> ParsedQuery:
    """Parse the raw GET params into a ``ParsedQuery``. Total: every malformed field falls to its
    own default, so a hand-edited / garbage URL yields a sane all-defaults search, never a 500."""
    sort, descending = _parse_sort(params.get(PARAM_SORT))
    return ParsedQuery(
        text=_text(params.get(PARAM_Q)),
        filters=SearchFilters(
            collection=_nonempty(params.get(PARAM_COLLECTION)),
            media_type=_nonempty(params.get(PARAM_MEDIA_TYPE)),
            document_type=_nonempty(params.get(PARAM_DOCUMENT_TYPE)),
            tag=_nonempty(params.get(PARAM_TAG)),
            decade=_int_or_none(params.get(PARAM_DECADE)),
            date_from=_date_or_none(params.get(PARAM_DATE_FROM)),
            date_to=_date_or_none(params.get(PARAM_DATE_TO)),
            dateless=_truthy(params.get(PARAM_DATELESS)),
        ),
        sort=sort,
        descending=descending,
        page=_page(params.get(PARAM_PAGE)),
    )


def _text(raw: str | None) -> str | None:
    """The free-text term: stripped, or ``None`` for blank/absent (a browse, not an empty query)."""
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _nonempty(raw: str | None) -> str | None:
    """A scalar filter value, or ``None`` for a blank/absent param (no constraint)."""
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _int_or_none(raw: str | None) -> int | None:
    """Parse an int, or ``None`` on anything non-numeric/absent (the decade facet is optional)."""
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _date_or_none(raw: str | None) -> datetime.date | None:
    """Parse an ISO ``YYYY-MM-DD``, or ``None`` on any malformed/absent value. The date-range UI
    only ever emits ISO dates; a hand-edited garbage bound just drops that half of the range."""
    if raw is None or not raw.strip():
        return None
    try:
        return datetime.date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _truthy(raw: str | None) -> bool:
    """The "Ohne Datum" toggle: True for a known truthy spelling, else False (incl. absence)."""
    return (raw or "").strip().lower() in _TRUTHY


def _page(raw: str | None) -> int:
    """The 1-based page. A non-positive / non-numeric / absent value floors to 1 (never a bad
    slice); pagination and result windows are bounded by the index layer itself."""
    parsed = _int_or_none(raw)
    return parsed if parsed is not None and parsed >= 1 else 1


# ---------------------------------------------------------------------------
# Link helpers — pure query-string algebra for facets / chips / pagination
# ---------------------------------------------------------------------------


def _clean(params: Mapping[str, str]) -> dict[str, str]:
    """A mutable copy with blank values dropped — the base every link helper edits. Keeping only
    non-blank keys means a built URL never carries an empty ``medienart=`` that reads as a filter."""
    return {k: v for k, v in params.items() if v != ""}


def with_param(params: Mapping[str, str], key: str, value: str) -> str:
    """The query string for the current state PLUS ``key=value`` (a facet click). Replaces any
    existing value for ``key`` and resets ``seite`` — the result set changed, so page 1 is honest."""
    updated = _clean(params)
    updated[key] = value
    updated.pop(PARAM_PAGE, None)
    return urlencode(updated)


def without_param(params: Mapping[str, str], key: str) -> str:
    """The query string for the current state MINUS ``key`` (a chip ✕ / facet un-click). Resets
    ``seite`` for the same reason ``with_param`` does — the narrowing changed."""
    updated = _clean(params)
    updated.pop(key, None)
    updated.pop(PARAM_PAGE, None)
    return urlencode(updated)


def page_query(params: Mapping[str, str], page: int) -> str:
    """The query string for the current state at ``page`` (pagination). Preserves every filter,
    text and sort; only ``seite`` moves — URL-as-state, back-button-honest, no infinite scroll."""
    updated = _clean(params)
    updated[PARAM_PAGE] = str(page)
    return urlencode(updated)


#: The bulk-edit selection param. Multi-valued (one per selected ulid); preserved across pagination
#: so a no-JS selection survives page moves (spec §2/§3). NOT a search param — stripped from facet/
#: sort links elsewhere, threaded only through the pagination + select-page links below.
PARAM_AUSWAHL = "auswahl"


def page_query_with_auswahl(params: Mapping[str, str], auswahl: Sequence[str], page: int) -> str:
    """The pagination query string at ``page`` PLUS the multi-valued ``auswahl`` selection (spec §2).
    Like ``page_query`` but re-attaches every selected ulid (``doseq``) so paging never drops the
    selection. An empty selection omits the param entirely."""
    pairs: list[tuple[str, str]] = [(k, v) for k, v in _clean(params).items() if k != PARAM_AUSWAHL]
    pairs = [(k, v) for k, v in pairs if k != PARAM_PAGE]
    pairs.append((PARAM_PAGE, str(page)))
    pairs.extend((PARAM_AUSWAHL, u) for u in auswahl)
    return urlencode(pairs)


def select_page_query(
    params: Mapping[str, str], auswahl: Sequence[str], page_ulids: Sequence[str]
) -> str:
    """The "Alle auf dieser Seite" link: the current state with this page's ulids ADDED to the
    selection (deduped, order-preserving), staying on the current page (spec §2, no-JS select-page)."""
    merged = list(dict.fromkeys([*auswahl, *page_ulids]))
    pairs: list[tuple[str, str]] = [(k, v) for k, v in _clean(params).items() if k != PARAM_AUSWAHL]
    pairs.extend((PARAM_AUSWAHL, u) for u in merged)
    return urlencode(pairs)


def has_next_page(*, page: int, page_size: int, hits_on_page: int, total: int) -> bool:
    """Whether a further result page exists after the current one.

    Rows consumed so far = the ``page_size``-sized windows before this page PLUS the hits actually
    on it — NOT ``page * hits_on_page``: on a partial last page ``len(hits)`` understates the window
    (total=60, page 2 with 10 hits would read 20 < 60 and offer a spurious link to an empty page 3).
    An overshot empty page consumes its full preceding windows, so it also reports no next."""
    return (page - 1) * page_size + hits_on_page < total
