"""The query layer — viewer-scoped ``search`` over the derived index (ADR 0003/0004).

One public function, ``search``, plus the frozen value types it returns. Everything it computes
— text match, filters, facets, total, the page window — derives from ONE base queryset:

    ArticleIndex.objects.filter(_viewer_scope(viewer))

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
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, assert_never

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVectorField
from django.db.models import Count, F, Func, Q, QuerySet
from django.db.models.functions import Collate

from bundesarchiv.domain.models import Ulid
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index.models import ArticleIndex
from bundesarchiv.index.scope import _viewer_scope

# The FTS config both the generated columns and the query parser use (ADR 0011). websearch is the
# query parser (``websearch_to_tsquery``): quoted phrases, ``-`` negation, bare AND. Part 4 adds the
# ADR-0011 recall mitigation: prefix (``:*``) matching on the trailing lexeme (``_prefix_tsquery``),
# which lifts the corpus spot-check from 9/12 to 12/12 (a compound head like ``Lager`` then matches
# ``Bundeslager``). No ``ts_headline`` in v1.
_CONFIG = "bundesarchiv_german"

# page_size cap. A page is a human-facing result window; 200 is a generous ceiling that still
# bounds the row count and the per-hit work. Anything larger is clamped (not rejected) so a
# caller passing a huge value gets a full-but-bounded page rather than an error.
_MAX_PAGE_SIZE = 200

# ICU numeric collation for ``ref_code`` / ``title`` ordering (ADR 0011): "B 10" sorts after
# "B 2", "Ä 3" sorts with A. Used by both the ref_code and title sorts.
_DE_NUMERIC = "de_numeric"

type SortOrder = Literal["relevance", "ref_code", "date", "title"]


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
    """

    collection: Ulid | None = None
    media_type: str | None = None
    document_type: str | None = None
    tag: str | None = None
    decade: int | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    dateless: bool = False


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One result row, floor-safe by construction: the member-visible identity + metadata columns
    plus the STRUCTURED scope data the archivist ledger chrome renders (SICHTBARKEIT column +
    ENTWURF badge). No ``physical_location`` / ``custom`` / ``archivist_text`` (the floored fields)
    ever appear here.

    ``is_draft`` / ``tier`` / ``groups`` carry NO cross-tier leak by construction: ``_viewer_scope``
    already restricts the returned rows to those the viewer may see, so a row's ``groups`` are only
    ever groups a viewer in that GROUPS rung holds (public/members rows carry ``groups=()``), never
    another tier's names; ``is_draft`` rows (archivist_only) are never returned to a non-archivist at
    all. The human-German SICHTBARKEIT string is rendered in the view/template from this structured
    data, and the TEMPLATE additionally gates it to the archivist — this dataclass only carries the
    facts, it never decides visibility."""

    ulid: str
    title: str
    ref_code: str | None
    date_edtf: str | None
    media_type: str | None
    document_type: str | None
    is_draft: bool
    tier: str | None  # "PUBLIC" | "MEMBERS" | "GROUPS"; None iff an archivist-only row
    groups: tuple[str, ...]


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
# floored columns (physical_location/custom/archivist_text) are simply never named here. is_draft/
# tier/groups are archivist-chrome scope data (see SearchHit) — safe on scoped rows by construction.
_HIT_COLUMNS = (
    "ulid",
    "title",
    "ref_code",
    "date_edtf",
    "media_type",
    "document_type",
    "is_draft",
    "tier",
    "groups",
)


def search(
    viewer: Viewer,
    *,
    text: str | None = None,
    filters: SearchFilters | None = None,
    sort: SortOrder = "relevance",
    page: int = 1,
    page_size: int = 50,
) -> SearchPage:
    """Viewer-scoped search over the derived index.

    Pipeline: scope the queryset (``_viewer_scope`` — always first), apply the text match, apply
    the filters, then derive total / facets / the ordered, paginated hits from that one scoped +
    filtered queryset. Returns frozen dataclasses only; no QuerySet or model instance escapes.
    """
    filters = filters or SearchFilters()
    query = _search_query(text)

    base = ArticleIndex.objects.filter(_viewer_scope(viewer))
    matched = _apply_text(base, query, viewer)
    filtered = _apply_filters(matched, filters)

    total = filtered.count()
    hits = _page_of_hits(
        filtered, query=query, viewer=viewer, sort=sort, page=page, page_size=page_size
    )
    facets = _facets(matched, filters)
    dateless_count = _dateless_count(matched, filters)
    return SearchPage(hits=hits, total=total, facets=facets, dateless_count=dateless_count)


# ---------------------------------------------------------------------------
# Text match + relevance
# ---------------------------------------------------------------------------


def _search_query(text: str | None) -> SearchQuery | None:
    """The parsed tsquery for ``text``, or ``None`` for a browse (no text). A blank / whitespace-only
    string is treated as no text — an all-match browse, not an empty query.

    ADR-0011 recall mitigation: the query is prefix-augmented — the trailing lexeme is given the
    ``:*`` prefix form so a compound head (``Lager``) matches the whole compound (``Bundeslager``),
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
    qs: QuerySet[ArticleIndex], query: SearchQuery | None, viewer: Viewer
) -> QuerySet[ArticleIndex]:
    """Restrict ``qs`` to rows whose matched vector matches ``query``. A ``None`` query is a
    browse — the queryset is returned unchanged (all in-scope rows)."""
    if query is None:
        return qs
    return qs.annotate(_vector=_matched_vector(viewer)).filter(_vector=query)


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
    viewer: Viewer,
    sort: SortOrder,
    page: int,
    page_size: int,
) -> tuple[SearchHit, ...]:
    """Order ``qs``, slice the page window, and project to floor-safe ``SearchHit``s.

    Uses ``.values(*_HIT_COLUMNS)`` so no model instance is built — only the six member-visible
    columns leave the ORM, and they map 1:1 onto ``SearchHit``.
    """
    ordered = _ordered(qs, query=query, viewer=viewer, sort=sort)
    size = _clamp_page_size(page_size)
    start = max(page - 1, 0) * size
    rows = ordered.values(*_HIT_COLUMNS)[start : start + size]
    # ``groups`` comes back as a list from the ArrayField; SearchHit is frozen/hashable, so coerce
    # to a tuple. Every other column maps 1:1.
    return tuple(SearchHit(**{**row, "groups": tuple(row["groups"])}) for row in rows)


def _ordered(
    qs: QuerySet[ArticleIndex], *, query: SearchQuery | None, viewer: Viewer, sort: SortOrder
) -> QuerySet[ArticleIndex]:
    """Apply the requested sort. Every order ends with ``ulid`` as a deterministic tiebreaker so
    pages never shuffle between calls. ``relevance`` with no text falls back to ``ulid`` (a stable,
    unique browse order — the index has no intrinsic "recency", so the PK is the honest default).
    """
    match sort:
        case "relevance":
            if query is None:
                return qs.order_by("ulid")  # browse: deterministic, no rank to sort by
            # rank desc, over the viewer's matched vector (combined for an Archivist, general_tsv
            # otherwise — same expression the @@ match used), ``ulid`` breaking ties.
            return qs.annotate(_rank=SearchRank(_matched_vector(viewer), query)).order_by(
                "-_rank", "ulid"
            )
        case "ref_code":
            return qs.annotate(_rc=Collate("ref_code", _DE_NUMERIC)).order_by(
                F("_rc").asc(nulls_last=True), "ulid"
            )
        case "date":
            return qs.order_by(F("date_earliest").asc(nulls_last=True), "ulid")
        case "title":
            return qs.annotate(_t=Collate("title", _DE_NUMERIC)).order_by("_t", "ulid")
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
    matched: QuerySet[ArticleIndex], filters: SearchFilters
) -> Mapping[str, tuple[FacetCount, ...]]:
    """All five facets. ``matched`` is the scoped + text-matched queryset (facets DO reflect the
    text search and every filter EXCEPT the facet's own dimension). Each facet re-applies the
    other filters via ``_apply_filters`` over a per-facet copy of ``filters`` with its own
    dimension cleared, so the scope predicate rides along on every aggregate query."""
    scalar = {
        key: _scalar_facet(matched, column=column, filters=_without(filters, key))
        for key, column in _SCALAR_FACETS
    }
    array = {
        key: _array_facet(matched, column=column, filters=_without(filters, key))
        for key, column in _ARRAY_FACETS
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
