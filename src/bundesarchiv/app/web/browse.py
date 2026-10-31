"""The workbench's state as a query string. IO-free; no visibility logic."""

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlencode

from bundesarchiv.index.query import FileKind, SearchFilters, SortOrder

# Query-string keys. The template, the parser and the chip builder
# all read this ONE vocabulary so a rename can't drift between them.
PARAM_Q = "q"
PARAM_COLLECTION = "collection"
PARAM_MEDIA_TYPE = "media_type"
PARAM_DOCUMENT_TYPE = "document_type"
PARAM_TAG = "tag"
PARAM_CREATOR = "creator"
PARAM_PLACE = "place"
PARAM_DECADE = "decade"
PARAM_DATELESS = "dateless"
PARAM_DATE_FROM = "date_from"
PARAM_DATE_TO = "date_to"
PARAM_DIGITAL = "digital"
PARAM_FILE = "file"
PARAM_DRAFTS = "drafts"
PARAM_TEMPLATES = "templates"
PARAM_SORT = "sort"
PARAM_PAGE = "page"
PARAM_PAGE_SIZE = "page_size"
PARAM_VIEW = "view"

#: The one ``view`` value: the table. A query reads in the Lesesaal unless the table is asked for;
#: without a query the list is the table (ParsedQuery.reading).
TABLE = "table"

PAGE_SIZE = 50
#: The sizes on offer; any other ``page_size`` falls to ``PAGE_SIZE``.
PAGE_SIZES: tuple[int, ...] = (25, 50, 100, 200)
_PAGE_SIZES_BY_PARAM: dict[str, int] = {str(size): size for size in PAGE_SIZES}

#: The ``sort`` values the index understands (``SortOrder``). An unknown value falls to the
#: default (relevance), so a hand-edited URL can never 500 the sort.
_SORTS: frozenset[str] = frozenset({"relevance", "ref_code", "date", "title", "added"})
_DEFAULT_SORT: SortOrder = "relevance"

#: Truthy spellings for the boolean toggles (Ohne Datum, Digital, Entwürfe, Vorlagen). Anything
#: else (incl. absence) is False.
_TRUTHY = frozenset({"1", "true", "ja", "on"})


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    text: str | None
    filters: SearchFilters
    sort: SortOrder
    descending: bool
    page: int
    reading: bool = False
    page_size: int = PAGE_SIZE


_SORT_DESC_PREFIX = "-"


def _parse_sort(raw: str | None) -> tuple[SortOrder, bool]:
    value = (raw or "").strip().lower()
    descending = value.startswith(_SORT_DESC_PREFIX)
    name = value[1:] if descending else value
    if name not in _SORTS or name == _DEFAULT_SORT:
        return _DEFAULT_SORT, False
    return cast(SortOrder, name), descending


def parse_query(params: Mapping[str, str]) -> ParsedQuery:
    """Parse the raw GET params into a ``ParsedQuery``. Total: every malformed field falls to its
    own default, so a hand-edited / garbage URL yields a sane all-defaults search, never a 500."""
    sort, descending = _parse_sort(params.get(PARAM_SORT))
    text = _nonempty(params.get(PARAM_Q))
    return ParsedQuery(
        text=text,
        filters=SearchFilters(
            collection=_nonempty(params.get(PARAM_COLLECTION)),
            media_type=_nonempty(params.get(PARAM_MEDIA_TYPE)),
            document_type=_nonempty(params.get(PARAM_DOCUMENT_TYPE)),
            tag=_nonempty(params.get(PARAM_TAG)),
            creator=_nonempty(params.get(PARAM_CREATOR)),
            place=_nonempty(params.get(PARAM_PLACE)),
            decade=_int_or_none(params.get(PARAM_DECADE)),
            date_from=_date_or_none(params.get(PARAM_DATE_FROM)),
            date_to=_date_or_none(params.get(PARAM_DATE_TO)),
            dateless=_truthy(params.get(PARAM_DATELESS)),
            has_files=_truthy(params.get(PARAM_DIGITAL)),
            file_kind=_file_kind(params.get(PARAM_FILE)),
            drafts_only=_truthy(params.get(PARAM_DRAFTS)),
            templates_only=_truthy(params.get(PARAM_TEMPLATES)),
        ),
        sort=sort,
        descending=descending,
        page=_page(params.get(PARAM_PAGE)),
        page_size=_PAGE_SIZES_BY_PARAM.get(params.get(PARAM_PAGE_SIZE) or "", PAGE_SIZE),
        reading=text is not None and (params.get(PARAM_VIEW) or "").strip() != TABLE,
    )


def _nonempty(raw: str | None) -> str | None:
    """A param stripped, or ``None`` when blank/absent: no text is a browse, no filter value no
    constraint."""
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _int_or_none(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _date_or_none(raw: str | None) -> datetime.date | None:
    if raw is None or not raw.strip():
        return None
    try:
        return datetime.date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _TRUTHY


def _file_kind(raw: str | None) -> FileKind | None:
    try:
        return FileKind((raw or "").strip().lower())
    except ValueError:
        return None


def _page(raw: str | None) -> int:
    parsed = _int_or_none(raw)
    return parsed if parsed is not None and parsed >= 1 else 1


# ---------------------------------------------------------------------------
# Link helpers — pure query-string algebra for facets / chips / pagination
# ---------------------------------------------------------------------------


def _clean(params: Mapping[str, str]) -> dict[str, str]:
    """A mutable copy with blank values dropped — the base every link helper edits. Keeping only
    non-blank keys means a built URL never carries an empty ``media_type=`` that reads as a filter."""
    return {k: v for k, v in params.items() if v != ""}


def with_param(params: Mapping[str, str], key: str, value: str) -> str:
    """The query string for the current state PLUS ``key=value`` (a facet click). Replaces any
    existing value for ``key`` and resets ``page`` — the result set changed, so page 1 is honest."""
    updated = _clean(params)
    updated[key] = value
    updated.pop(PARAM_PAGE, None)
    return urlencode(updated)


def without_param(params: Mapping[str, str], key: str) -> str:
    """The query string for the current state MINUS ``key`` (a chip ✕ / facet un-click). Resets
    ``page`` for the same reason ``with_param`` does — the narrowing changed."""
    updated = _clean(params)
    updated.pop(key, None)
    updated.pop(PARAM_PAGE, None)
    return urlencode(updated)


def view_query(params: Mapping[str, str], *, table: bool) -> str:
    """The query string for the same search in the table (``table``) or the Lesesaal. Every other
    param stays, the page too: both views show the same hits."""
    updated = _clean(params)
    updated.pop(PARAM_VIEW, None)
    if table:
        updated[PARAM_VIEW] = TABLE
    return urlencode(updated)


FILTER_PARAMS: tuple[str, ...] = (
    PARAM_COLLECTION,
    PARAM_MEDIA_TYPE,
    PARAM_DOCUMENT_TYPE,
    PARAM_TAG,
    PARAM_CREATOR,
    PARAM_PLACE,
    PARAM_DECADE,
    PARAM_DATELESS,
    PARAM_DATE_FROM,
    PARAM_DATE_TO,
    PARAM_DIGITAL,
    PARAM_FILE,
    PARAM_DRAFTS,
    PARAM_TEMPLATES,
)


def clear_filters_query(params: Mapping[str, str]) -> str:
    updated = {k: v for k, v in _clean(params).items() if k not in FILTER_PARAMS}
    updated.pop(PARAM_PAGE, None)
    return urlencode(updated)


#: The bulk selection: the param repeats, one value per ulid.
PARAM_SELECTION = "selection"


def _paging_query(params: Mapping[str, str], selection: Sequence[str], key: str, value: int) -> str:
    """The search without its page, ``key=value`` set, the selection kept."""
    kept = [
        (k, v) for k, v in _clean(params).items() if k not in (PARAM_SELECTION, PARAM_PAGE, key)
    ]
    return urlencode([*kept, (key, str(value)), *((PARAM_SELECTION, u) for u in selection)])


def page_query_with_selection(
    params: Mapping[str, str], selection: Sequence[str], page: int
) -> str:
    return _paging_query(params, selection, PARAM_PAGE, page)


def page_size_query(params: Mapping[str, str], selection: Sequence[str], size: int) -> str:
    """The same list in pages of ``size``, from page 1."""
    return _paging_query(params, selection, PARAM_PAGE_SIZE, size)


def select_page_query(
    params: Mapping[str, str], selection: Sequence[str], page_ulids: Sequence[str]
) -> str:
    merged = list(dict.fromkeys([*selection, *page_ulids]))
    pairs: list[tuple[str, str]] = [
        (k, v) for k, v in _clean(params).items() if k != PARAM_SELECTION
    ]
    pairs.extend((PARAM_SELECTION, u) for u in merged)
    return urlencode(pairs)


def has_next_page(*, page: int, page_size: int, hits_on_page: int, total: int) -> bool:
    """Counts full windows before this page, not ``page * hits_on_page``, which understates on a
    short last page."""
    return (page - 1) * page_size + hits_on_page < total
