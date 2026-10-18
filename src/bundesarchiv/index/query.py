"""Viewer-scoped search over the derived index (ADR 0003, ADR 0004).

Every ``ArticleIndex`` query starts from ``_scoped``; the only other viewer branch is the tsvector
choice in ``_matched_vector``. No QuerySet or model instance crosses the interface.
"""

import datetime
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import groupby
from operator import itemgetter
from typing import Any, Literal, TypedDict, assert_never, cast

from django.contrib.postgres.expressions import ArraySubquery
from django.contrib.postgres.search import (
    SearchHeadline,
    SearchQuery,
    SearchRank,
    SearchVectorField,
)
from django.db.models import (
    Case,
    Count,
    F,
    Func,
    IntegerField,
    Q,
    QuerySet,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Collate, Lower
from django.db.models.lookups import Exact

from bundesarchiv.domain.models import ULID
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index.models import ArticleIndex, MediaText
from bundesarchiv.index.scope import _viewer_scope

# Must name the config the tsvector wrappers use (migration 0001).
_CONFIG = "bundesarchiv_german"

_MAX_PAGE_SIZE = 200

_DE_NUMERIC = "de_numeric"

type SortOrder = Literal["relevance", "ref_code", "date", "title", "added"]

type Facet = Literal[
    "collection", "tags", "decades", "media_type", "document_type", "file_kind", "creator", "place"
]
#: What ``search`` computes unless asked otherwise. ``creator`` and ``place`` are opt-in: each is an
#: unbounded GROUP BY over a free-text column (one bucket per distinct value).
_DEFAULT_FACETS: tuple[Facet, ...] = (
    "collection",
    "tags",
    "decades",
    "media_type",
    "document_type",
    "file_kind",
)


class FileKind(StrEnum):
    """The closed set of kinds a record's files are counted by, in the order a summary lists them."""

    IMAGE = "image"
    PDF = "pdf"
    VIDEO = "video"
    AUDIO = "audio"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """None or False means no constraint, except ``deleted``, which picks the side of the
    Papierkorb (ADR 0022). ``collection`` matches the whole subtree; ``date_from``/``date_to`` keep
    rows whose date range overlaps the window."""

    collection: str | None = None
    media_type: str | None = None
    document_type: str | None = None
    tag: str | None = None
    creator: str | None = None
    place: str | None = None  # the ``subject_place`` column
    decade: int | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    dateless: bool = False
    has_files: bool = False
    file_kind: FileKind | None = None
    drafts_only: bool = False
    templates_only: bool = False
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class TextPage:
    """A page of one of a hit's files whose text matches the query; pages count from 1."""

    content_hash: str
    page: int


#: The fields a hit's headlines read: the member-searchable ones of the general vector, less the
#: Signatur and the two type words a row prints anyway. Never ``archivist_text``: a headline is the
#: same for every viewer, an Archivist's included.
type HeadlineField = Literal["title", "tags", "creator", "subject_place", "body"]
HEADLINE_FIELDS: tuple[HeadlineField, ...] = ("title", "tags", "creator", "subject_place", "body")


@dataclass(frozen=True, slots=True)
class Headline:
    """An excerpt of one of a hit's fields in which the query matched: runs of its text, each
    ``True`` where it is a matched word, and whether the excerpt leaves out the field's start or
    end. The runs are plain text, whatever markup the field holds."""

    field: HeadlineField
    runs: tuple[tuple[str, bool], ...]
    cut_start: bool
    cut_end: bool


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Never carries a floored column (``physical_location``, ``custom``, ``archivist_text``)."""

    ulid: ULID
    title: str
    ref_code: str | None
    date_edtf: str | None
    media_type: str | None
    document_type: str | None
    is_draft: bool
    collection_id: ULID  # the Bestand the Article sits in; names no Bestand on a fail-closed row
    # (kind, count) in FileKind order, zero kinds left out; () = no files.
    file_counts: tuple[tuple[FileKind, int], ...]
    # The Papierkorb mark (ADR 0022); None on a live row. Only archivist_only rows carry one.
    deleted_at: datetime.datetime | None = None
    deleted_by: str | None = None
    added_at: datetime.datetime | None = None  # None = unknown
    is_template: bool = False
    text_pages: tuple[TextPage, ...] = ()
    headlines: tuple[Headline, ...] = ()


@dataclass(frozen=True, slots=True)
class FacetCount:
    """One facet value and how many in-scope, in-filter rows carry it. ``value`` is always a
    string (decade ints are stringified) so every facet is uniform for the caller/UI."""

    value: str
    count: int


@dataclass(frozen=True, slots=True)
class SearchPage:
    """``total`` counts every match, not just this page; ``dateless_count`` is the "Ohne Datum"
    facet, None when the search asked for no facets."""

    hits: tuple[SearchHit, ...]
    total: int
    facets: Mapping[str, tuple[FacetCount, ...]]
    dateless_count: int | None


class _HitRow(TypedDict):
    """One ``.values(*_HIT_COLUMNS)`` row: the columns of a ``SearchHit``, plus the files' hashes."""

    ulid: ULID
    title: str
    ref_code: str | None
    date_edtf: str | None
    media_type: str | None
    document_type: str | None
    is_draft: bool
    collection_id: ULID
    file_counts: dict[str, int]
    deleted_at: datetime.datetime | None
    deleted_by: str | None
    added_at: datetime.datetime | None
    is_template: bool
    media_hashes: list[str]


_HIT_COLUMNS = tuple(_HitRow.__annotations__)


def search(
    viewer: Viewer,
    *,
    text: str | None = None,
    filters: SearchFilters | None = None,
    sort: SortOrder = "relevance",
    descending: bool = False,
    page: int = 1,
    page_size: int = 50,
    facets: tuple[Facet, ...] = _DEFAULT_FACETS,
    headlines: bool = False,
) -> SearchPage:
    """``descending`` reverses a column sort; ``relevance`` and ``added`` ignore it."""
    filters = filters or SearchFilters()
    query = _search_query(text)

    base = _scoped(viewer, deleted=filters.deleted)
    ref_code_match = _ref_code_hit(text)
    if ref_code_match is not None:
        base = base.annotate(_ref_code_key=_REF_CODE_KEY)
    matched = _apply_text(base, query, viewer, ref_code_match)
    filtered = _apply_filters(matched, filters)

    total = filtered.count()
    hits = _page_of_hits(
        filtered,
        query=query,
        ref_code_match=ref_code_match,
        viewer=viewer,
        sort=sort,
        descending=descending,
        page=page,
        page_size=page_size,
    )
    if headlines and query is not None:
        hits = _with_headlines(filtered, query, hits)
    return SearchPage(
        hits=hits,
        total=total,
        facets=_facets(matched, filters, facets),
        dateless_count=_dateless_count(matched, filters) if facets else None,
    )


def facet_counts(viewer: Viewer, facets: tuple[Facet, ...]) -> Mapping[str, tuple[FacetCount, ...]]:
    """The ``facets`` of everything ``viewer`` may see outside the Papierkorb: ``search``'s facets
    for no text and no filter, without its total and hits."""
    return _facets(_scoped(viewer, deleted=False), SearchFilters(), facets)


def dateless_count(viewer: Viewer) -> int:
    """How many Articles ``viewer`` may see outside the Papierkorb carry no date (the start page's
    "Unbekannt"): ``search``'s dateless bucket for no text and no filter."""
    return _dateless_count(_scoped(viewer, deleted=False), SearchFilters())


def _scoped(viewer: Viewer, *, deleted: bool) -> QuerySet[ArticleIndex]:
    """The rows ``viewer`` may see on one side of the Papierkorb: every query starts here."""
    return ArticleIndex.objects.filter(_viewer_scope(viewer), deleted_at__isnull=not deleted)


#: How many Schlagworte one suggestion list offers.
_MAX_SUGGESTIONS = 10


def suggest_tags(viewer: Viewer, text: str, *, exclude: Iterable[str] = ()) -> tuple[str, ...]:
    """The Schlagworte of ``viewer``'s Articles outside the Papierkorb that contain ``text``, in
    ``values_containing``'s order. At most ten, none in ``exclude`` (ignoring case)."""
    taken = {tag.casefold() for tag in exclude}
    kept = (fc.value for fc in values_containing(viewer, "tags", text))
    return tuple(tag for tag in kept if tag.casefold() not in taken)[:_MAX_SUGGESTIONS]


type Suggested = Literal["creator", "place", "tags"]

_SUGGESTED_COLUMNS: Mapping[Suggested, str] = {
    "creator": "creator",
    "place": "subject_place",
    "tags": "tags",
}


def values_containing(
    viewer: Viewer, field: Suggested, text: str, filters: SearchFilters | None = None
) -> tuple[FacetCount, ...]:
    """The values of ``field`` on ``viewer``'s Articles outside the Papierkorb that contain
    ``text``, ignoring case, each with how many of those Articles carry it: the ones starting with
    it first, each part by count, then alphabetically. A blank ``text`` matches nothing.
    ``filters`` narrow the Articles as they narrow a facet: all but ``field``'s own, and never
    across the Papierkorb (their ``deleted`` is ignored)."""
    needle = text.strip().casefold()
    if not needle:
        return ()
    column = _SUGGESTED_COLUMNS[field]
    value = Func(F(column), function="unnest") if field == "tags" else F(column)
    narrowed = _apply_filters(
        _scoped(viewer, deleted=False), _without(filters or SearchFilters(), field)
    )
    rows = (
        narrowed.annotate(_elem=value)
        .values("_elem")
        .annotate(_n=Count("ulid"))
        .order_by("-_n", Collate("_elem", _DE_NUMERIC))
    )
    matches = [
        FacetCount(row["_elem"], row["_n"])
        for row in rows
        if row["_elem"] and needle in row["_elem"].casefold()
    ]
    return tuple(sorted(matches, key=lambda fc: not fc.value.casefold().startswith(needle)))


def _search_query(text: str | None) -> SearchQuery | None:
    if text is None or not text.strip():
        return None
    return _PrefixWebSearchQuery(text, config=_CONFIG, search_type="websearch")


class _PrefixWebSearchQuery(SearchQuery):
    """A ``websearch_to_tsquery`` with ``:*`` appended to its trailing lexeme (ADR 0011).

    Postgres has no inline ``:*`` in ``websearch_to_tsquery``, so the ADR's verified pattern is
    applied at the SQL level: parse with ``websearch_to_tsquery``, cast to text, append ``:*``, and
    re-parse with ``to_tsquery`` (``'berlin' & 'lied'`` → ``'berlin' & 'lied':*``). The ``:*``
    goes only after a closing quote: a query ending in a negated phrase (``!( 'a' <-> 'b' )``) has
    no trailing lexeme and is re-parsed as it is; so is an all-stopword query (``''``, which
    matches nothing). Subclassing ``SearchQuery`` (not a bare ``Func``) keeps it a first-class
    query expression usable by both ``@@`` and ``ts_rank``.
    """

    def as_sql(  # type: ignore[override]
        self,
        compiler: object,
        connection: object,
        function: str | None = None,
        template: str | None = None,
    ) -> tuple[str, list[object]]:
        sql, params = super().as_sql(compiler, connection, function, template)  # type: ignore[arg-type]
        # The inner ``websearch_to_tsquery`` consumes the config, its first param; re-supply it
        # for the outer ``to_tsquery``.
        config_param = next(iter(params))
        wrapped = f"to_tsquery(%s::regconfig, regexp_replace(({sql})::text, '''$', ''':*'))"
        return wrapped, [config_param, *params]


def _matched_vector(viewer: Viewer) -> F | Func:
    """The tsvector expression a text query is matched (and ranked) against for ``viewer``.

    THE SANCTIONED EXCEPTION to "no viewer branching in query.py": the scope ``Q`` selects which
    ROWS a viewer sees, but not which text COLUMNS to search — an Archivist additionally searches
    the archivist-only tsvector (``physical_location`` / ``custom`` values), which no non-Archivist
    may reach even on rows they can see. That column choice is a per-viewer decision the scope seam
    deliberately does not carry, so it lives here as one closed ``match`` with ``assert_never``.

    RANK-COMBINATION CHOICE. For the Archivist the two vectors are concatenated into one
    (``general_tsv || archivist_tsv``): the ``@@`` match AND the ``ts_rank`` then both run over that
    single combined vector. This is preferred over ``GREATEST(rank_general, rank_archivist)`` or a
    weighted sum because ``||`` merges the lexeme position lists, so ``ts_rank`` sees term frequency
    across both sources exactly as if they were one document — one defensible score, no tuning knob.
    For every non-Archivist the vector is ``general_tsv`` alone, so an archivist-only term is
    unreachable for both matching and ranking.
    """
    match viewer:
        case Archivist():
            return Func(
                F("general_tsv"),
                F("archivist_tsv"),
                function="",  # no function name; the template is the bare "(a || b)" concat
                template="(%(expressions)s)",
                arg_joiner=" || ",
                output_field=SearchVectorField(),
            )
        case Member() | Public():
            return F("general_tsv")
        case _ as unreachable:
            assert_never(unreachable)


def _apply_text(
    qs: QuerySet[ArticleIndex], query: SearchQuery | None, viewer: Viewer, ref_code_match: Q | None
) -> QuerySet[ArticleIndex]:
    """Restrict ``qs`` to rows whose matched vector matches ``query``, or one of whose files has a
    page that matches it, or whose Signatur equals the text (``ref_code_match``). A ``None`` query
    is a browse — the queryset is returned unchanged."""
    if query is None:
        return qs
    own_page = Q(
        media_hashes__overlap=ArraySubquery(
            _matching_pages(query).values("content_hash").distinct()
        )
    )
    hit = Q(_vector=query) | own_page
    if ref_code_match:
        hit |= ref_code_match
    return qs.annotate(_vector=_matched_vector(viewer)).filter(hit)


def _matching_pages(query: SearchQuery) -> QuerySet[MediaText]:
    """The pages whose text matches ``query``; none for a query without a positive word (ADR 0023):
    it would match every page that lacks the word, empty pages and markers included."""
    tree = Func(query, function="querytree", output_field=TextField())
    return MediaText.objects.filter(tsv=query).exclude(Exact(tree, "T"))


# ``ref_code`` with case and whitespace removed: "BA 10", "ba10" and "BA10" share one key. A
# sequential scan over the scoped rows; an expression index only pays at far more than the corpus.
_REF_CODE_KEY = Lower(
    Func(
        F("ref_code"),
        Value(r"\s+"),
        Value(""),
        Value("g"),
        function="regexp_replace",
        output_field=TextField(),
    )
)


def _ref_code_hit(text: str | None) -> Q | None:
    """The predicate "this row's Signatur is what the user typed", or ``None`` for a blank text.
    The row side needs the ``_ref_code_key`` annotation (see ``_REF_CODE_KEY``)."""
    key = "".join((text or "").split()).lower()
    return Q(_ref_code_key=key) if key else None


def _apply_filters(qs: QuerySet[ArticleIndex], f: SearchFilters) -> QuerySet[ArticleIndex]:
    if f.collection is not None:
        qs = qs.filter(collection_ancestors__contains=[f.collection])
    if f.media_type is not None:
        qs = qs.filter(media_type=f.media_type)
    if f.document_type is not None:
        qs = qs.filter(document_type=f.document_type)
    if f.tag is not None:
        qs = qs.filter(tags__contains=[f.tag])
    if f.creator is not None:
        qs = qs.filter(creator=f.creator)
    if f.place is not None:
        qs = qs.filter(subject_place=f.place)
    if f.decade is not None:
        qs = qs.filter(decades__contains=[f.decade])
    if f.dateless:
        qs = qs.filter(date_earliest__isnull=True)
    if f.has_files:
        qs = qs.exclude(file_counts={})
    if f.file_kind is not None:
        qs = qs.filter(file_counts__has_key=f.file_kind.value)
    if f.drafts_only:
        qs = qs.filter(is_draft=True)
    if f.templates_only:
        qs = qs.filter(is_template=True)
    return _apply_date_range(qs, f.date_from, f.date_to)


def _apply_date_range(
    qs: QuerySet[ArticleIndex],
    date_from: datetime.date | None,
    date_to: datetime.date | None,
) -> QuerySet[ArticleIndex]:
    if date_from is None and date_to is None:
        return qs
    # A dateless row (date_earliest IS NULL) can never overlap a date window — drop it whenever any
    # bound is given. (Its date_latest is NULL too, so it would otherwise sneak through the
    # open-upper-end branch below.)
    qs = qs.filter(date_earliest__isnull=False)
    if date_to is not None:
        qs = qs.filter(date_earliest__lte=date_to)
    if date_from is not None:
        # date_latest >= date_from, OR date_latest IS NULL = an open upper end (+infinity).
        qs = qs.filter(Q(date_latest__gte=date_from) | Q(date_latest__isnull=True))
    return qs


def _page_of_hits(
    qs: QuerySet[ArticleIndex],
    *,
    query: SearchQuery | None,
    ref_code_match: Q | None,
    viewer: Viewer,
    sort: SortOrder,
    descending: bool,
    page: int,
    page_size: int,
) -> tuple[SearchHit, ...]:
    ordered = _ordered(
        qs,
        query=query,
        ref_code_match=ref_code_match,
        viewer=viewer,
        sort=sort,
        descending=descending,
    )
    size = _clamp_page_size(page_size)
    start = max(page - 1, 0) * size
    # Our own index rows: the columns are the ones ``_HitRow`` names.
    rows = cast(list[_HitRow], list(ordered.values(*_HIT_COLUMNS)[start : start + size]))
    pages = _text_pages(query, [row["media_hashes"] for row in rows])
    return tuple(_hit(row, tp) for row, tp in zip(rows, pages, strict=True))


def _hit(row: _HitRow, text_pages: tuple[TextPage, ...]) -> SearchHit:
    return SearchHit(
        ulid=row["ulid"],
        title=row["title"],
        ref_code=row["ref_code"],
        date_edtf=row["date_edtf"],
        media_type=row["media_type"],
        document_type=row["document_type"],
        is_draft=row["is_draft"],
        collection_id=row["collection_id"],
        file_counts=_in_kind_order(row["file_counts"]),
        deleted_at=row["deleted_at"],
        deleted_by=row["deleted_by"],
        added_at=row["added_at"],
        is_template=row["is_template"],
        text_pages=text_pages,
    )


def _text_pages(query: SearchQuery | None, media: list[list[str]]) -> list[tuple[TextPage, ...]]:
    """Per hit, given its files' hashes, the pages of those files that match ``query``."""
    by_hash = _matching_page_numbers(query, {h for hashes in media for h in hashes})
    return [_pages_of(hashes, by_hash) for hashes in media]


def _matching_page_numbers(query: SearchQuery | None, hashes: set[str]) -> dict[str, list[int]]:
    """The numbers of the pages of ``hashes`` that match ``query``, per hash, in page order; ``{}``
    without a query."""
    if query is None:
        return {}
    found = (
        _matching_pages(query)
        .filter(content_hash__in=hashes)
        .order_by("content_hash", "page")
        .values_list("content_hash", "page")
    )
    return {h: [page for _, page in rows] for h, rows in groupby(found, key=itemgetter(0))}


def _pages_of(hashes: list[str], by_hash: Mapping[str, list[int]]) -> tuple[TextPage, ...]:
    """The matching pages of one hit's files, in media order then page order."""
    return tuple(TextPage(h, page) for h in dict.fromkeys(hashes) for page in by_hash.get(h, ()))


#: Where ts_headline marks a matched word. Control characters no field means to hold: the shell
#: strips them from the field first, so every one in an excerpt is a mark.
_MARK_START = "\x02"
_MARK_END = "\x03"
#: Stands in for "<" while ts_headline reads a field: its parser drops a tag-like word
#: ("<unleserlich>") from the excerpt, which then is no longer the field's text.
_LT = "\x04"
_MARKED_RUN = re.compile(f"{_MARK_START}(.*?){_MARK_END}", re.DOTALL)


def _with_headlines(
    filtered: QuerySet[ArticleIndex], query: SearchQuery, hits: tuple[SearchHit, ...]
) -> tuple[SearchHit, ...]:
    """``hits`` with their headlines: one query over the same scoped rows, the page's ulids only."""
    texts = {f"_text_{f}": _headline_text(f) for f in HEADLINE_FIELDS}
    marked = {
        f"_headline_{f}": SearchHeadline(
            _headline_text(f),
            query,
            config=_CONFIG,
            start_sel=_MARK_START,
            stop_sel=_MARK_END,
            max_words=14,
            min_words=6,
        )
        for f in HEADLINE_FIELDS
    }
    rows = (
        filtered.filter(ulid__in=[h.ulid for h in hits])
        .annotate(**texts, **marked)
        .values_list("ulid", *texts, *marked)
    )
    n = len(HEADLINE_FIELDS)
    by_ulid = {
        ulid: tuple(
            headline
            for f, text, excerpt in zip(HEADLINE_FIELDS, cols[:n], cols[n:], strict=True)
            if (headline := _headline(f, text, excerpt))
        )
        for ulid, *cols in rows
    }
    return tuple(replace(hit, headlines=by_ulid.get(hit.ulid, ())) for hit in hits)


def _headline_text(field: HeadlineField) -> Func:
    """The field's text as its headline reads it: the Schlagworte joined, the marks stripped,
    "<" stood in for."""
    column = (
        Func(F("tags"), Value(" · "), function="array_to_string", output_field=TextField())
        if field == "tags"
        else F(field)
    )
    return Func(
        Coalesce(column, Value("")),
        Value("<" + _MARK_START + _MARK_END + _LT),
        Value(_LT),
        function="translate",
        output_field=TextField(),
    )


def _headline(field: HeadlineField, text: str, excerpt: str) -> Headline | None:
    """The excerpt ts_headline cut from ``text`` as a ``Headline``, or ``None`` when it marks no
    word (the query matched elsewhere)."""
    text, excerpt = text.replace(_LT, "<"), excerpt.replace(_LT, "<")
    pieces = _MARKED_RUN.split(excerpt)
    if len(pieces) == 1:
        return None
    plain = "".join(pieces)
    return Headline(
        field=field,
        runs=tuple((piece, odd % 2 == 1) for odd, piece in enumerate(pieces) if piece),
        cut_start=not text.lstrip().startswith(plain.lstrip()),
        cut_end=not text.rstrip().endswith(plain.rstrip()),
    )


def _in_kind_order(counts: Mapping[str, int]) -> tuple[tuple[FileKind, int], ...]:
    """The stored ``file_counts`` as a hit carries them: (kind, count) in ``FileKind`` order."""
    return tuple((kind, counts[kind]) for kind in FileKind if kind in counts)


def _ordered(
    qs: QuerySet[ArticleIndex],
    *,
    query: SearchQuery | None,
    ref_code_match: Q | None,
    viewer: Viewer,
    sort: SortOrder,
    descending: bool = False,
) -> QuerySet[ArticleIndex]:
    """Every order ends on ``ulid`` so pages never shuffle."""
    match sort:
        case "relevance":
            if query is None or ref_code_match is None:
                return qs.order_by("ulid")
            exact = Case(When(ref_code_match, then=1), default=0, output_field=IntegerField())
            return qs.annotate(
                _exact=exact,
                _rank=SearchRank(_matched_vector(viewer), query),
                _t=Collate("title", _DE_NUMERIC),
            ).order_by("-_exact", "-_rank", "_t", "ulid")
        case "ref_code":
            rc = Collate("ref_code", _DE_NUMERIC)
            primary = (
                F("_rc").desc(nulls_last=True) if descending else F("_rc").asc(nulls_last=True)
            )
            return qs.annotate(_rc=rc).order_by(primary, "ulid")
        case "date":
            col = F("date_earliest")
            primary = col.desc(nulls_last=True) if descending else col.asc(nulls_last=True)
            return qs.order_by(primary, "ulid")
        case "title":
            primary = F("_t").desc() if descending else F("_t").asc()
            return qs.annotate(_t=Collate("title", _DE_NUMERIC)).order_by(primary, "ulid")
        case "added":
            return qs.order_by(F("added_at").desc(nulls_last=True), "ulid")
        case _ as unreachable:
            assert_never(unreachable)


def _clamp_page_size(page_size: int) -> int:
    return max(1, min(page_size, _MAX_PAGE_SIZE))


_SCALAR_FACETS: tuple[tuple[str, str], ...] = (
    ("media_type", "media_type"),
    ("document_type", "document_type"),
    ("creator", "creator"),
    ("place", "subject_place"),
)

# ``collection`` counts the whole subtree, matching the subtree filter (owner 2026-07-10).
_ARRAY_FACETS: tuple[tuple[str, str], ...] = (
    ("collection", "collection_ancestors"),
    ("tags", "tags"),
    ("decades", "decades"),
)


def _facets(
    matched: QuerySet[ArticleIndex], filters: SearchFilters, wanted: tuple[str, ...]
) -> Mapping[str, tuple[FacetCount, ...]]:
    """The ``wanted`` facets. ``matched`` is the scoped + text-matched queryset (facets DO reflect the
    text search and every filter EXCEPT the facet's own dimension). Each facet re-applies the
    other filters via ``_apply_filters`` over a per-facet copy of ``filters`` with its own
    dimension cleared, so the scope predicate rides along on every aggregate query."""
    scalar = {
        key: _scalar_facet(matched, column=column, filters=_without(filters, key))
        for key, column in _SCALAR_FACETS
        if key in wanted
    }
    if "file_kind" in wanted:
        scalar["file_kind"] = _file_kind_facet(matched, _without(filters, "file_kind"))
    array = {
        key: _array_facet(matched, column=column, filters=_without(filters, key))
        for key, column in _ARRAY_FACETS
        if key in wanted
    }
    return scalar | array


def _dateless_count(matched: QuerySet[ArticleIndex], filters: SearchFilters) -> int:
    """Clears the date range too: a range would zero the count by construction."""
    other = replace(filters, dateless=False, date_from=None, date_to=None)
    return _apply_filters(matched, other).filter(date_earliest__isnull=True).count()


def _file_kind_facet(
    matched: QuerySet[ArticleIndex], filters: SearchFilters
) -> tuple[FacetCount, ...]:
    """How many rows carry a file of each kind, in ``FileKind`` order, zero kinds left out: one
    aggregate over ``matched`` re-filtered by the other dimensions."""
    counts = _apply_filters(matched, filters).aggregate(
        **{k.value: Count("ulid", filter=Q(file_counts__has_key=k.value)) for k in FileKind}
    )
    return tuple(FacetCount(k.value, counts[k.value]) for k in FileKind if counts[k.value])


def _without(filters: SearchFilters, key: str) -> SearchFilters:
    field = {"tags": "tag", "decades": "decade"}.get(key, key)
    # ``field`` is always a nullable dimension, never a bool, so None is well-typed; ``Any`` keeps
    # ``replace`` from narrowing the value against the union of field types.
    kwargs: dict[str, Any] = {field: None}
    return replace(filters, **kwargs)


def _scalar_facet(
    matched: QuerySet[ArticleIndex], *, column: str, filters: SearchFilters
) -> tuple[FacetCount, ...]:
    rows = (
        _apply_filters(matched, filters)
        .exclude(**{f"{column}__isnull": True})
        .values(column)
        .annotate(_n=Count("ulid"))
        .order_by("-_n", column)
    )
    return tuple(FacetCount(value=str(row[column]), count=row["_n"]) for row in rows)


def _array_facet(
    matched: QuerySet[ArticleIndex], *, column: str, filters: SearchFilters
) -> tuple[FacetCount, ...]:
    rows = (
        _apply_filters(matched, filters)
        .annotate(_elem=Func(F(column), function="unnest"))
        .values("_elem")
        .annotate(_n=Count("ulid"))
        .order_by("-_n", "_elem")
    )
    return tuple(FacetCount(value=str(row["_elem"]), count=row["_n"]) for row in rows)
