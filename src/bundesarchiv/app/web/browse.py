"""The workbench's search state: read from a request's params, printed back as a query string.

Parsing and printing are pure; ``SearchState.search`` runs a state against the index. No visibility
logic: ``search`` scopes by viewer.
"""

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Self, cast
from urllib.parse import urlencode

from bundesarchiv.domain.viewer import Viewer
from bundesarchiv.index import query as index
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
#: The bulk selection, no search param: it repeats, one value per ulid.
PARAM_SELECTION = "selection"

#: The one ``view`` value: the table. A query reads in the Lesesaal unless the table is asked for;
#: without a query the list is the table (``SearchState.reading``).
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


_SORT_DESC_PREFIX = "-"

#: Each filter's param and the ``SearchFilters`` field it sets, in print order. ``deleted`` has
#: none: the Papierkorb is its own route (ADR 0022).
_FILTERS: tuple[tuple[str, str], ...] = (
    (PARAM_COLLECTION, "collection"),
    (PARAM_MEDIA_TYPE, "media_type"),
    (PARAM_DOCUMENT_TYPE, "document_type"),
    (PARAM_TAG, "tag"),
    (PARAM_CREATOR, "creator"),
    (PARAM_PLACE, "place"),
    (PARAM_DECADE, "decade"),
    (PARAM_DATELESS, "dateless"),
    (PARAM_DATE_FROM, "date_from"),
    (PARAM_DATE_TO, "date_to"),
    (PARAM_DIGITAL, "has_files"),
    (PARAM_FILE, "file_kind"),
    (PARAM_DRAFTS, "drafts_only"),
    (PARAM_TEMPLATES, "templates_only"),
)

#: A param's dependents: a state that changes the key leaves them behind. The Dokumenttyp belongs
#: to the Medienart it was picked under.
_DEPENDENTS: Mapping[str, tuple[str, ...]] = {PARAM_MEDIA_TYPE: (PARAM_DOCUMENT_TYPE,)}


@dataclass(frozen=True, slots=True)
class SearchState:
    """One search of the list: what ``parse`` reads from a request's params and ``query`` prints
    back, so that ``parse(state.query()) == state``. ``text`` is stripped and never blank, ``page``
    at least 1, ``page_size`` one of ``PAGE_SIZES``, and relevance is never descending."""

    text: str | None = None
    filters: SearchFilters = field(default_factory=SearchFilters)
    sort: SortOrder = _DEFAULT_SORT
    descending: bool = False
    page: int = 1
    page_size: int = PAGE_SIZE
    table: bool = False

    @classmethod
    def parse(cls, params: Mapping[str, str]) -> Self:
        """Total: every malformed field falls to its own default, so a hand-edited or garbage URL
        yields a sane all-defaults search, never a 500. Params it does not know are dropped."""
        sort, descending = _parse_sort(params.get(PARAM_SORT))
        return cls(
            text=_nonempty(params.get(PARAM_Q)),
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
            table=(params.get(PARAM_VIEW) or "").strip() == TABLE,
        )

    @property
    def reading(self) -> bool:
        """Does the list read in the Lesesaal? Only a query does, unless the table is asked for."""
        return self.text is not None and not self.table

    def params(self) -> dict[str, str]:
        """The params this state prints, in a fixed order; a default prints nothing."""
        sort = f"{_SORT_DESC_PREFIX if self.descending else ''}{self.sort}"
        printed = {
            PARAM_Q: self.text,
            **{param: _printed(getattr(self.filters, field)) for param, field in _FILTERS},
            PARAM_SORT: None if self.sort == _DEFAULT_SORT else sort,
            PARAM_VIEW: TABLE if self.table else None,
            PARAM_PAGE_SIZE: None if self.page_size == PAGE_SIZE else str(self.page_size),
            PARAM_PAGE: None if self.page == 1 else str(self.page),
        }
        return {param: value for param, value in printed.items() if value is not None}

    def query(self, selection: Sequence[str] = ()) -> str:
        """The query string, the bulk ``selection`` after it (one pair per ulid)."""
        pairs = [*self.params().items(), *((PARAM_SELECTION, ulid) for ulid in selection)]
        return urlencode(pairs)

    def value(self, param: str) -> str | None:
        """``param`` as this state prints it, ``None`` when it is not set."""
        return self.params().get(param)

    def with_(self, param: str, value: str) -> Self:
        """This state with ``param`` set to ``value`` (a facet click), from page 1."""
        return self.parse({**self._changing(param), param: value})

    def without(self, param: str) -> Self:
        """This state with ``param`` unset (a chip's ✕), from page 1."""
        return self.parse(self._changing(param))

    def without_filters(self) -> Self:
        """This state with no filter set, from page 1; the text, the sort and the view stay."""
        return replace(self, filters=SearchFilters(), page=1)

    def search(
        self, viewer: Viewer, *, facets: tuple[index.Facet, ...], page_size: int | None = None
    ) -> index.SearchPage:
        """This state's page of hits for ``viewer``. A preview of a preset (the start page's)
        asks for its first ``page_size`` hits."""
        return index.search(
            viewer,
            text=self.text,
            filters=self.filters,
            sort=self.sort,
            descending=self.descending,
            page=self.page,
            page_size=page_size or self.page_size,
            facets=facets,
            headlines=self.reading,
        )

    def _changing(self, param: str) -> dict[str, str]:
        """The params of a state that changes ``param``: without it, its dependents and ``page``
        (the result set changed, so page 1 is honest)."""
        dropped = {param, PARAM_PAGE, *_DEPENDENTS.get(param, ())}
        return {k: v for k, v in self.params().items() if k not in dropped}


def sort_parts(raw: str | None) -> tuple[str, bool]:
    """A ``sort`` param's name, lower-cased, and whether its ``-`` asks for descending."""
    value = (raw or "").strip().lower()
    return value.removeprefix(_SORT_DESC_PREFIX), value.startswith(_SORT_DESC_PREFIX)


def _parse_sort(raw: str | None) -> tuple[SortOrder, bool]:
    name, descending = sort_parts(raw)
    if name not in _SORTS or name == _DEFAULT_SORT:
        return _DEFAULT_SORT, False
    return cast(SortOrder, name), descending


def _printed(value: object) -> str | None:
    """A filter field's param value; ``None`` (no constraint) when unset or False."""
    match value:
        case None | False:
            return None
        case True:
            return "1"
        case datetime.date():
            return value.isoformat()
        case _:
            return str(value)


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


def select_page_query(selection: Sequence[str], page_ulids: Sequence[str]) -> str:
    return SearchState().query(list(dict.fromkeys([*selection, *page_ulids])))


def has_next_page(*, page: int, page_size: int, hits_on_page: int, total: int) -> bool:
    """Counts full windows before this page, not ``page * hits_on_page``, which understates on a
    short last page."""
    return (page - 1) * page_size + hits_on_page < total
