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
- The link helpers (``with_param`` / ``without_param`` / ``page_query`` / ``active_chips``) — pure
  query-string algebra the templates emit for facet clicks, removable chips and pagination. Adding
  or removing a facet resets ``seite`` (the result set changed, so the old page number is stale).

No visibility logic lives here (that is ``search`` / ``can_view``); this module only shuffles
strings between the URL and ``SearchFilters``.
"""

import datetime
from collections.abc import Mapping
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

#: German sort labels -> the ``SortOrder`` the index understands. An unknown value falls to the
#: default (relevance), so a hand-edited URL can never 500 the sort.
_SORT_BY_LABEL: dict[str, SortOrder] = {
    "relevanz": "relevance",
    "signatur": "ref_code",
    "datierung": "date",
    "titel": "title",
}
_DEFAULT_SORT: SortOrder = "relevance"

#: The German sort labels + human captions, in display order — the ``<select>`` renders from this.
SORT_CHOICES: tuple[tuple[str, str], ...] = (
    ("relevanz", "Relevanz"),
    ("signatur", "Signatur"),
    ("datierung", "Datierung"),
    ("titel", "Titel"),
)

#: Truthy spellings for the boolean "Ohne Datum" toggle. Anything else (incl. absence) is False.
_TRUTHY = frozenset({"1", "true", "ja", "on"})

#: The filter dimensions shown as removable chips, in display order: (param key, German label).
#: ``q`` is deliberately absent — free text is the search field, not a chip. Decade/dateless/date
#: are included so every active narrowing is one-click-removable (plan §4.5, ideas §1.2).
_CHIP_DIMENSIONS: tuple[tuple[str, str], ...] = (
    (PARAM_COLLECTION, "Bestand"),
    (PARAM_MEDIA_TYPE, "Medienart"),
    (PARAM_DOCUMENT_TYPE, "Dokumenttyp"),
    (PARAM_TAG, "Schlagwort"),
    (PARAM_DECADE, "Jahrzehnt"),
    (PARAM_DATE_FROM, "von"),
    (PARAM_DATE_TO, "bis"),
    (PARAM_DATELESS, "Ohne Datum"),
)


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """The workbench request state, parsed from the query string: the free text, the typed
    ``SearchFilters``, the sort and the (1-based) page. Everything ``search`` needs, nothing more."""

    text: str | None
    filters: SearchFilters
    sort: SortOrder
    page: int


def parse_query(params: Mapping[str, str]) -> ParsedQuery:
    """Parse the raw GET params into a ``ParsedQuery``. Total: every malformed field falls to its
    own default, so a hand-edited / garbage URL yields a sane all-defaults search, never a 500."""
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
        sort=_SORT_BY_LABEL.get((params.get(PARAM_SORT) or "").strip().lower(), _DEFAULT_SORT),
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


@dataclass(frozen=True, slots=True)
class ActiveChip:
    """One active filter, as a removable chip: its param key, German label, the shown value, and the
    query string that removes JUST this dimension (the ✕ target)."""

    param: str
    label: str
    value: str
    remove_query: str


def active_chips(params: Mapping[str, str]) -> tuple[ActiveChip, ...]:
    """The active filters as removable chips, in display order. Free text (``q``), sort and page are
    NOT chips — only the narrowing filter dimensions are. Each chip's ``remove_query`` drops exactly
    its own dimension, so ✕ is a single reversible step (ideas §1.2)."""
    cleaned = _clean(params)
    return tuple(
        ActiveChip(
            param=key,
            label=label,
            value=cleaned[key],
            remove_query=without_param(cleaned, key),
        )
        for key, label in _CHIP_DIMENSIONS
        if key in cleaned
    )
