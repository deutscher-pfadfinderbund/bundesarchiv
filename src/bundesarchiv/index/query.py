"""The query layer — viewer-scoped ``search`` over the derived index (ADR 0003/0004).

``search``, its facets alone (``facet_counts``) and the tag suggestions, plus the frozen value
types they return. Everything ``search`` computes — text match, filters, facets, total, the page
window — derives from ONE base queryset:

    ArticleIndex.objects.filter(_viewer_scope(viewer), <the side of the Papierkorb>)

``_viewer_scope`` (``index.scope``) is the single visibility predicate; this module never writes
a tier / archivist_only comparison of its own. The ONE sanctioned exception is choosing which
tsvector(s) to search: an Archivist searches the archivist tsvector too, which is a per-viewer
decision the scope ``Q`` deliberately does not carry. That choice is a single ``match viewer``
with ``assert_never`` (``_matched_vector``), commented as the sanctioned exception.

No QuerySets or model instances cross the interface: ``search`` returns frozen dataclasses only,
and ``SearchHit`` carries exactly the member-visible identity/metadata columns — no
``physical_location``, ``custom`` or ``archivist_text`` (the domain field floor, by construction).

ORM-vs-raw outcome (brief decision point). The whole query is expressible in the Django ORM —
``SearchQuery``/``SearchRank`` for text+relevance, ``Collate`` for the ICU sort, array lookups
for the tag/decade/subtree filters, and per-facet aggregate queries. The tags/decades facets need
per-element counts over an array column; ``ArrayAgg``/``Count`` over ``Func('unnest', ...)`` in a
``.values().annotate()`` group-by does this without raw SQL. So this module is pure ORM — the
scope predicate is therefore always applied by Django as a real ``WHERE`` on every one of the
(1 + up to 5-facet) queries, never hand-rolled.
"""

import datetime
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Literal, assert_never

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVectorField
from django.db.models import Case, Count, F, Func, IntegerField, Q, QuerySet, TextField, Value, When
from django.db.models.functions import Collate, Lower

from bundesarchiv.domain.models import Ulid
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index.models import ArticleIndex
from bundesarchiv.index.scope import _viewer_scope

# The FTS config both the generated columns and the query parser use (ADR 0011). websearch is the
# query parser (``websearch_to_tsquery``): quoted phrases, ``-`` negation, bare AND. Part 4 adds the
# ADR-0011 recall mitigation: prefix (``:*``) matching on the trailing lexeme (``_prefix_tsquery``),
# which lifts the corpus spot-check from 9/12 to 12/12 (a leading part like ``Bundes`` then matches
# ``Bundeslager``). No ``ts_headline`` in v1.
_CONFIG = "bundesarchiv_german"

# page_size cap. A page is a human-facing result window; 200 is a generous ceiling that still
# bounds the row count and the per-hit work. Anything larger is clamped (not rejected) so a
# caller passing a huge value gets a full-but-bounded page rather than an error.
_MAX_PAGE_SIZE = 200

# ICU numeric collation for ``ref_code`` / ``title`` ordering (ADR 0011): "B 10" sorts after
# "B 2", "Ä 3" sorts with A. Used by both the ref_code and title sorts.
_DE_NUMERIC = "de_numeric"

type SortOrder = Literal["relevance", "ref_code", "date", "title", "added"]

type Facet = Literal["collection", "tags", "decades", "media_type", "document_type", "file_kind"]
_ALL_FACETS: tuple[Facet, ...] = (
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
    """Facet/filter selection. All optional; ``None`` means "no constraint on this dimension".

    ``collection`` matches the whole subtree (any row whose ``collection_ancestors`` contains the
    ulid — leaf, mid or root). ``date_from``/``date_to`` are an interval-overlap constraint (see
    ``_apply_date_range``); a row with no date is excluded from any date-range-filtered result.

    ``dateless`` (Part 4, "Ohne Datum" facet — data honesty per the ideas doc) narrows to rows with
    NO date at all (``date_earliest IS NULL``). It is the exact complement of the date-range filter's
    NULL exclusion, and mutually exclusive with a date range in practice (a dateless row can never
    overlap a window): if ``dateless`` and a range are both given, the two ``date_earliest`` clauses
    (IS NULL vs IS NOT NULL) conjoin to the empty set — the honest, non-crashing outcome.

    ``has_files`` keeps rows with at least one file (the fact ``SearchHit.file_counts`` reports);
    ``file_kind`` keeps rows with at least one file of that kind;
    ``drafts_only`` keeps drafts, so it narrows a non-Archivist's scope to nothing.

    ``deleted`` picks the side of the Papierkorb (ADR 0022): False (the default) leaves every
    marked row out, True keeps only marked rows. Marked rows are archivist-only, so True narrows a
    non-Archivist's scope to nothing.
    """

    collection: Ulid | None = None
    media_type: str | None = None
    document_type: str | None = None
    tag: str | None = None
    decade: int | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    dateless: bool = False
    has_files: bool = False
    file_kind: FileKind | None = None
    drafts_only: bool = False
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One result row, floor-safe by construction: the member-visible identity + metadata columns
    plus ``is_draft`` for the archivist's Entwurf mark. No ``physical_location`` / ``custom`` /
    ``archivist_text`` (the floored fields) ever appear here.

    ``is_draft`` carries no cross-tier leak: ``_viewer_scope`` restricts the returned rows to those
    the viewer may see, and draft rows (archivist_only) never reach a non-archivist."""

    ulid: str
    title: str
    ref_code: str | None
    date_edtf: str | None
    media_type: str | None
    document_type: str | None
    is_draft: bool
    collection_id: Ulid  # the Bestand the Article sits in; names no Bestand on a fail-closed row
    # (kind, count) in FileKind order, zero kinds left out; () = no files.
    file_counts: tuple[tuple[FileKind, int], ...]
    # The Papierkorb mark (ADR 0022); None on a live row. Only archivist_only rows carry one.
    deleted_at: datetime.datetime | None = None
    deleted_by: str | None = None
    added_at: datetime.datetime | None = None  # None = unknown


@dataclass(frozen=True, slots=True)
class FacetCount:
    """One facet value and how many in-scope, in-filter rows carry it. ``value`` is always a
    string (decade ints are stringified) so every facet is uniform for the caller/UI."""

    value: str
    count: int


@dataclass(frozen=True, slots=True)
class SearchPage:
    """A page of hits with the total (pre-pagination, scoped+filtered count) and the facets.

    ``dateless_count`` is the "Ohne Datum" facet bucket (Part 4): how many in-scope, in-filter rows
    carry NO date. Own-dimension-excluded like every other facet (computed with the ``dateless``
    filter cleared) so it always reads as "how many you'd get by switching this filter on", never
    collapsed by the current selection. It is a scalar (not a ``FacetCount``) because it has one
    value — present-or-not — not a set of values to choose among.
    """

    hits: tuple[SearchHit, ...]
    total: int
    facets: Mapping[str, tuple[FacetCount, ...]]
    dateless_count: int


# The columns ``SearchHit`` reads, pulled with ``.values(...)`` so no model instance is built or
# leaked. Exactly the SearchHit fields — the floor is enforced by this projection being narrow: the
# floored columns (physical_location/custom/archivist_text) are simply never named here.
_HIT_COLUMNS = (
    "ulid",
    "title",
    "ref_code",
    "date_edtf",
    "media_type",
    "document_type",
    "is_draft",
    "collection_id",
    "file_counts",
    "deleted_at",
    "deleted_by",
    "added_at",
)


def search(
    viewer: Viewer,
    *,
    text: str | None = None,
    filters: SearchFilters | None = None,
    sort: SortOrder = "relevance",
    descending: bool = False,
    page: int = 1,
    page_size: int = 50,
    facets: tuple[Facet, ...] = _ALL_FACETS,
) -> SearchPage:
    """Viewer-scoped search over the derived index.

    Pipeline: scope the queryset (``_viewer_scope`` — always first), apply the text match, apply
    the filters, then derive total / facets / the ordered, paginated hits from that one scoped +
    filtered queryset. Returns frozen dataclasses only; no QuerySet or model instance escapes.

    ``descending`` reverses a COLUMN sort's primary key (the workbench header cycle asc→desc); it is
    a no-op for ``relevance`` (always best-first). ``facets`` names the facets to compute; the
    page's ``facets`` mapping holds exactly those.
    """
    filters = filters or SearchFilters()
    query = _search_query(text)

    base = _scoped(viewer, deleted=filters.deleted)
    signatur = _signatur_hit(text)
    if signatur is not None:
        base = base.annotate(_signatur_key=_SIGNATUR_KEY)
    matched = _apply_text(base, query, viewer, signatur)
    filtered = _apply_filters(matched, filters)

    total = filtered.count()
    hits = _page_of_hits(
        filtered,
        query=query,
        signatur=signatur,
        viewer=viewer,
        sort=sort,
        descending=descending,
        page=page,
        page_size=page_size,
    )
    return SearchPage(
        hits=hits,
        total=total,
        facets=_facets(matched, filters, facets),
        dateless_count=_dateless_count(matched, filters),
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
    """The Schlagworte of ``viewer``'s Articles outside the Papierkorb that contain ``text``,
    ignoring case: the ones starting with it first, each part by how many Articles use the tag,
    then alphabetically. At most ten, none in ``exclude`` (ignoring case); a blank ``text`` suggests nothing."""
    needle = text.strip().casefold()
    if not needle:
        return ()
    # ponytail: every distinct tag per call (~3,400 in the corpus); match in SQL if that grows tenfold
    rows = (
        _scoped(viewer, deleted=False)
        .annotate(_elem=Func(F("tags"), function="unnest"))
        .values("_elem")
        .annotate(_n=Count("ulid"))
        .order_by("-_n", Collate("_elem", _DE_NUMERIC))
    )
    taken = {tag.casefold() for tag in exclude}
    matches = [
        tag
        for row in rows
        if needle in (folded := (tag := row["_elem"]).casefold()) and folded not in taken
    ]
    ranked = sorted(matches, key=lambda tag: not tag.casefold().startswith(needle))
    return tuple(ranked[:_MAX_SUGGESTIONS])


# ---------------------------------------------------------------------------
# Text match + relevance
# ---------------------------------------------------------------------------


def _search_query(text: str | None) -> SearchQuery | None:
    """The parsed tsquery for ``text``, or ``None`` for a browse (no text). A blank / whitespace-only
    string is treated as no text — an all-match browse, not an empty query.

    ADR-0011 recall mitigation: the query is prefix-augmented — the trailing lexeme is given the
    ``:*`` prefix form so a leading part (``Bundes``) matches the whole compound (``Bundeslager``),
    recovering the recall the missing German decomposition would otherwise lose. See
    ``_PrefixWebSearchQuery``.
    """
    if text is None or not text.strip():
        return None
    return _PrefixWebSearchQuery(text, config=_CONFIG)


class _PrefixWebSearchQuery(SearchQuery):
    """A ``websearch_to_tsquery`` with ``:*`` appended to its trailing lexeme (ADR 0011).

    Postgres has no inline ``:*`` in ``websearch_to_tsquery``, so the ADR's verified pattern is
    applied at the SQL level: parse with ``websearch_to_tsquery``, cast to text, append ``':*'``, and
    re-parse with ``to_tsquery`` — which reparses cleanly (``websearch_to_tsquery('Berliner
    Lieder')::text || ':*'`` → ``'berlin' & 'lied':*``). The ``NULLIF(..., '')`` guard makes an
    all-stopword query (empty tsquery, whose text is ``''``) fall to ``to_tsquery(config, NULL)`` =
    the empty tsquery again, instead of the invalid ``':*'``. Subclassing ``SearchQuery`` (not a bare
    ``Func``) keeps it a first-class query expression usable by both ``@@`` and ``ts_rank``.
    """

    def as_sql(  # type: ignore[override]
        self,
        compiler: object,
        connection: object,
        function: str | None = None,
        template: str | None = None,
    ) -> tuple[str, list[object]]:
        # ``params`` carries [config, text] for a websearch SearchQuery; we rebuild the SQL around
        # the same two params so the config is applied to BOTH the websearch parse and the reparse.
        sql, params = super().as_sql(compiler, connection, function, template)  # type: ignore[arg-type]
        # ``sql`` is ``websearch_to_tsquery(%s::regconfig, %s)`` (Django's rendering). Wrap it:
        # to_tsquery(config, NULLIF(<that>::text, '') || ':*') — but the config param is consumed
        # once by the inner call, so re-supply it for the outer to_tsquery too. The first param is
        # always the config (a websearch SearchQuery always renders config + term).
        config_param = next(iter(params))
        wrapped = f"to_tsquery(%s::regconfig, NULLIF(({sql})::text, '') || ':*')"
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
            # general_tsv || archivist_tsv — Postgres tsvector concatenation (merges lexemes).
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
    qs: QuerySet[ArticleIndex], query: SearchQuery | None, viewer: Viewer, signatur: Q | None
) -> QuerySet[ArticleIndex]:
    """Restrict ``qs`` to rows whose matched vector matches ``query``, or whose Signatur equals the
    text (``signatur``). A ``None`` query is a browse — the queryset is returned unchanged."""
    if query is None:
        return qs
    hit = Q(_vector=query) | signatur if signatur else Q(_vector=query)
    return qs.annotate(_vector=_matched_vector(viewer)).filter(hit)


# ``ref_code`` with case and whitespace removed: "BA 10", "ba10" and "BA10" share one key. A
# sequential scan over the scoped rows; an expression index only pays at far more than the corpus.
_SIGNATUR_KEY = Lower(
    Func(
        F("ref_code"),
        Value(r"\s+"),
        Value(""),
        Value("g"),
        function="regexp_replace",
        output_field=TextField(),
    )
)


def _signatur_hit(text: str | None) -> Q | None:
    """The predicate "this row's Signatur is what the user typed", or ``None`` for a blank text.
    The row side needs the ``_signatur_key`` annotation (see ``_SIGNATUR_KEY``)."""
    key = "".join((text or "").split()).lower()
    return Q(_signatur_key=key) if key else None


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _apply_filters(qs: QuerySet[ArticleIndex], f: SearchFilters) -> QuerySet[ArticleIndex]:
    """All filters except date-range, each a plain column/array constraint over the scoped set.
    Date-range is separate (``_apply_date_range``) because it spans two columns with NULL rules."""
    if f.collection is not None:
        # Subtree membership: any row whose ancestry chain contains this collection ulid.
        qs = qs.filter(collection_ancestors__contains=[f.collection])
    if f.media_type is not None:
        qs = qs.filter(media_type=f.media_type)
    if f.document_type is not None:
        qs = qs.filter(document_type=f.document_type)
    if f.tag is not None:
        qs = qs.filter(tags__contains=[f.tag])
    if f.decade is not None:
        qs = qs.filter(decades__contains=[f.decade])
    if f.dateless:
        # "Ohne Datum": rows with NO date at all. Same column, same NULL rule the date-range filter
        # uses to EXCLUDE dateless rows — here we SELECT them. Applied over the already-scoped set,
        # so the scope WHERE rides along (no visibility re-derivation).
        qs = qs.filter(date_earliest__isnull=True)
    if f.has_files:
        qs = qs.exclude(file_counts={})
    if f.file_kind is not None:
        qs = qs.filter(file_counts__has_key=f.file_kind.value)
    if f.drafts_only:
        qs = qs.filter(is_draft=True)
    return _apply_date_range(qs, f.date_from, f.date_to)


def _apply_date_range(
    qs: QuerySet[ArticleIndex],
    date_from: datetime.date | None,
    date_to: datetime.date | None,
) -> QuerySet[ArticleIndex]:
    """Interval-overlap filter over ``[date_earliest, date_latest]``.

    A row overlaps the query window ``[date_from, date_to]`` iff ``date_earliest <= date_to`` AND
    ``date_latest >= date_from``. NULL handling:

    - ``date_latest IS NULL`` means an OPEN upper end (an open-ended EDTF interval, e.g. 1970/..):
      treated as ``+infinity``, so the ``date_latest >= date_from`` half is satisfied unless the
      row is excluded by its earliest bound.
    - ``date_earliest IS NULL`` means the row has NO date at all: it is EXCLUDED from any
      date-range-filtered result (a dateless row cannot be said to overlap a date window).

    Applied only when at least one bound is given; each bound half is independent so ``date_from``
    alone (open upper query) and ``date_to`` alone (open lower query) both work.
    """
    if date_from is None and date_to is None:
        return qs
    # A dateless row (date_earliest IS NULL) can never overlap a date window — drop it whenever any
    # bound is given. (Its date_latest is NULL too, so it would otherwise sneak through the
    # open-upper-end branch below.)
    qs = qs.filter(date_earliest__isnull=False)
    if date_to is not None:
        # date_earliest <= date_to: the row starts on or before the window's end.
        qs = qs.filter(date_earliest__lte=date_to)
    if date_from is not None:
        # date_latest >= date_from, OR date_latest IS NULL = an open upper end (+infinity).
        qs = qs.filter(Q(date_latest__gte=date_from) | Q(date_latest__isnull=True))
    return qs


# ---------------------------------------------------------------------------
# Sort + pagination
# ---------------------------------------------------------------------------


def _page_of_hits(
    qs: QuerySet[ArticleIndex],
    *,
    query: SearchQuery | None,
    signatur: Q | None,
    viewer: Viewer,
    sort: SortOrder,
    descending: bool,
    page: int,
    page_size: int,
) -> tuple[SearchHit, ...]:
    """Order ``qs``, slice the page window, and project to floor-safe ``SearchHit``s.

    Uses ``.values(*_HIT_COLUMNS)`` so no model instance is built — only the member-visible
    columns leave the ORM, and they map 1:1 onto ``SearchHit``.
    """
    ordered = _ordered(
        qs, query=query, signatur=signatur, viewer=viewer, sort=sort, descending=descending
    )
    size = _clamp_page_size(page_size)
    start = max(page - 1, 0) * size
    rows = ordered.values(*_HIT_COLUMNS)[start : start + size]
    return tuple(
        SearchHit(**{**row, "file_counts": _in_kind_order(row["file_counts"])}) for row in rows
    )


def _in_kind_order(counts: Mapping[str, int]) -> tuple[tuple[FileKind, int], ...]:
    """The stored ``file_counts`` as a hit carries them: (kind, count) in ``FileKind`` order."""
    return tuple((kind, counts[kind]) for kind in FileKind if kind in counts)


def _ordered(
    qs: QuerySet[ArticleIndex],
    *,
    query: SearchQuery | None,
    signatur: Q | None,
    viewer: Viewer,
    sort: SortOrder,
    descending: bool = False,
) -> QuerySet[ArticleIndex]:
    """Apply the requested sort. Every order ends with ``ulid`` as a deterministic tiebreaker so
    pages never shuffle between calls. ``relevance`` with no text falls back to ``ulid`` (a stable,
    unique browse order — the index has no intrinsic "recency", so the PK is the honest default).

    ``descending`` reverses the PRIMARY key of a COLUMN sort (ref_code / date / title) — the
    workbench's header cycle asc→desc; the ``ulid`` tiebreaker stays ascending so pages remain
    deterministic within a key value. It does not apply to ``relevance`` (rank is always best-first;
    relevance is never a column header), so a descending relevance is a no-op. ``added`` is newest
    first with unknown dates last; it is a preset, not a column header, so ``descending`` is a no-op
    there too.
    """
    match sort:
        case "relevance":
            if query is None or signatur is None:
                return qs.order_by("ulid")  # browse: deterministic, no rank to sort by
            # rank desc, over the viewer's matched vector (combined for an Archivist, general_tsv
            # otherwise — same expression the @@ match used); equal ranks read in numeric title
            # order (a run of issues: Nr. 1, 2, 10), ``ulid`` last. An exact Signatur hit outranks
            # every text rank.
            exact = Case(When(signatur, then=1), default=0, output_field=IntegerField())
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
    """Clamp ``page_size`` into ``[1, _MAX_PAGE_SIZE]`` — a non-positive value becomes 1, an
    over-large value is capped, so a page is always a bounded, non-empty-capacity window."""
    return max(1, min(page_size, _MAX_PAGE_SIZE))


# ---------------------------------------------------------------------------
# Facets — one aggregate per key, each excluding its own filter dimension
# ---------------------------------------------------------------------------

# Scalar facets: (facet key, model column). Each is a group-by count over the scoped+filtered set
# with THIS facet's own filter removed (standard faceting), so the counts show what a user could
# switch to, not just what the current selection already narrowed to.
_SCALAR_FACETS: tuple[tuple[str, str], ...] = (
    ("media_type", "media_type"),
    ("document_type", "document_type"),
)

# Array facets: (facet key, array column) — counted per-element via unnest.
#
# COLLECTION counts the SUBTREE (owner, 2026-07-10): it unnests ``collection_ancestors`` (each row's
# leaf→root chain), so every row contributes to each of its ancestors and a parent Collection's
# count is the size of its whole subtree — exactly the set selecting it as the (subtree) FILTER
# returns (``collection_ancestors__contains``). This replaces the old direct-membership group-by on
# ``collection_id`` (the confusing "direkt: N" hedge): facet count now matches what clicking yields.
# Still per-tier scoped — the aggregate runs over the ``_viewer_scope``'d ``matched`` set — and a
# fail-closed row carries no ancestors, so it never inflates any collection's count.
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
    """The "Ohne Datum" facet count: how many in-scope, text-matched, other-filtered rows have NO
    date (``date_earliest IS NULL``). Own-dimension-excluded like the scalar/array facets — computed
    over ``matched`` re-filtered by every OTHER dimension (the ``dateless`` and date-range clauses
    cleared), so it reports what switching the bucket on would yield, and the scope ``WHERE`` rides
    along from ``matched`` (never re-derived). Date-range is cleared alongside ``dateless`` because a
    range and "no date" are mutually exclusive dimensions of the same column — leaving a range on
    would zero this count by construction, which is not the facet's question."""
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
    """A copy of ``filters`` with the facet ``key``'s own dimension cleared (standard faceting).
    The facet key maps to the filter field it excludes: ``collection`` -> collection,
    ``tags`` -> tag, ``decades`` -> decade, and the scalar keys to themselves."""
    field = {"tags": "tag", "decades": "decade"}.get(key, key)
    # ``field`` is always a nullable facet dimension (collection/media_type/document_type/tag/decade)
    # — never the bool ``dateless`` — so clearing it to None is well-typed; ``Any`` keeps ``replace``
    # from narrowing the kwarg value against the union of field types (the same shape it had before
    # ``dateless`` joined the dataclass).
    kwargs: dict[str, Any] = {field: None}
    return replace(filters, **kwargs)


def _scalar_facet(
    matched: QuerySet[ArticleIndex], *, column: str, filters: SearchFilters
) -> tuple[FacetCount, ...]:
    """Group-by count over a scalar column, NULLs dropped, ordered by count desc then value.
    Runs over ``matched`` re-filtered by the other dimensions — the scope ``WHERE`` is inherited
    from ``matched``, so no visibility logic is re-derived here."""
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
    """Per-element count over an array column via ``unnest``: unnest the array, group by the
    element, count. Runs over ``matched`` re-filtered by the other dimensions. ``value`` is
    stringified (so integer decades become strings, uniform with the scalar facets)."""
    rows = (
        _apply_filters(matched, filters)
        .annotate(_elem=Func(F(column), function="unnest"))
        .values("_elem")
        .annotate(_n=Count("ulid"))
        .order_by("-_n", "_elem")
    )
    return tuple(FacetCount(value=str(row["_elem"]), count=row["_n"]) for row in rows)
