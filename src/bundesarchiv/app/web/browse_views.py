"""The archivist workbench views (Part 4.5-MVP): search/browse + the 4.6 detail read view.

Thin by design. Every request resolves its viewer via ``viewer_of`` and reaches data ONLY through
``search`` (results are pre-scoped SearchHits — no ``can_view`` in the search path) or, for the
detail view, through ``article_auth.resolve_visible_detail`` (the one place ``can_view`` + ``project``
run here — one load, feeding the projected Article + the archivist CAS version). No visibility logic
and no business logic live in these views or the templates (plan §11): param parsing is the pure
``browse`` layer, scoping is the index layer, and the templates only render.

Progressive enhancement (BINDING, plan §4.5): a plain GET renders the whole page; an ``HX-Request``
GET renders only the results region (same data, same template partial), so the no-JS baseline and
the HTMX-enhanced path share one render. URL-as-state: the full state is the query string, so an
HTMX swap that pushes the URL and a shared/bookmarked link resolve to the identical page.

The workbench + the detail view are production routes (mounted in ``web.urls``). The detail view
(``article_detail``, Part 4.6) is the Lesesaal read page: one template fed a ``visible``-projected
Article, so archivist-only fields are floored before render — no member/archivist fork.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import render
from django.urls import reverse

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import browse, bulk, vocab
from bundesarchiv.app.web.article_auth import (
    DetailResolution,
    resolve_visible_article,
    resolve_visible_detail,
)
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.media_views import _not_found, media_url, thumbnail_url
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.access import preview
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.models import Article, Lifecycle
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index.query import FacetCount, SearchHit, search

#: The preview-pane selection param. NOT a search param — it is stripped from every search link so
#: a denied/absent/malformed value leaves the page byte-identical to no pane (existence-hiding).
_PANE_PARAM = "artikel"


def workbench(request: HttpRequest) -> HttpResponse:
    """``GET /`` — the workbench: search field, filter rail, results, "Neuer Artikel" button.

    Pipeline: parse the query string (pure ``browse``), resolve the viewer, run the viewer-scoped
    ``search``, resolve collection-facet ULIDs to Collection names for display, then render. On a
    plain ``HX-Request`` only the results region renders (same data, same partial) — the no-JS full
    page and the HTMX swap are one code path. A history-restore request (``HX-History-Restore-Request``;
    htmx 4 sends it without ``HX-Request``) gets the full page — htmx swaps the whole document on a
    Back-button restore."""
    parsed = browse.parse_query(request.GET)
    viewer = viewer_of(request)
    # Presentation-only chrome flag: the templates hide archivist affordances (the Entwurf mark,
    # Bearbeiten, the bulk selection, "+ Neu …") for non-Archivists. This is NOT scoping (§11) —
    # result visibility is decided exclusively by search()/can_view; the /artikel/neu ROUTE stays
    # independently Archivist-gated regardless of this flag.
    is_archivist = isinstance(viewer, Archivist)
    page = search(
        viewer,
        text=parsed.text,
        filters=parsed.filters,
        sort=parsed.sort,
        descending=parsed.descending,
        page=parsed.page,
        page_size=browse.PAGE_SIZE,  # explicit: the pager arithmetic reads the same constant
    )
    # The preview pane: ?artikel=<ulid> resolved fail-closed through the ONE render path. None when
    # absent/malformed/denied — the workbench then renders byte-identically (no existence oracle).
    pane = _resolve_pane(request, is_archivist=is_archivist)
    # Bulk-edit selection (archivist-only chrome, spec §2): the multi-valued ?auswahl= carries the
    # selected ulids across pages. Non-archivists never get the selection column/bar, so their
    # auswahl is dropped entirely (defence-in-depth — the POST route is independently gated too).
    auswahl = request.GET.getlist(browse.PARAM_AUSWAHL) if is_archivist else []
    context = _results_context(
        request,
        parsed,
        page,
        is_archivist=is_archivist,
        selected_ulid=pane.ulid if pane is not None else None,
        auswahl=auswahl,
    )
    context["is_archivist"] = is_archivist
    context["pane"] = pane
    # The active Bestand filter (if any) — the archivist's focused collection. Drives the workbench's
    # "Bestand bearbeiten" affordance (4.8): a rename entry point appears only when one Bestand is in
    # focus. Archivist-only chrome; the /bestand/<ulid>/bearbeiten route is independently gated.
    context["aktiver_bestand"] = parsed.filters.collection if is_archivist else None
    # body.vorschau adds the pane column (the pane switch, layouts.css); the ledger re-densifies by
    # itself, it is a size container (law C11).
    context["vorschau"] = pane is not None
    # A Back-button restore swaps the whole body, so it gets the full page. Checked first, so a
    # restore that also carries HX-Request (htmx 2 did) can never get the chrome-less partial.
    if request.headers.get("HX-History-Restore-Request"):
        return render_screen(request, "workbench/workbench.html", context)
    if request.headers.get("HX-Request"):
        # The filter rail sits outside the #results swap target, so the partial prepends its
        # out-of-band fragments (oob gates them: the full page renders the rail once).
        context["oob"] = True
        return render(request, "workbench/_results.html", context)
    return render_screen(request, "workbench/workbench.html", context)


@dataclass(frozen=True, slots=True)
class _FacetItem:
    """One clickable facet value, fully resolved for the template: its shown label, count, whether
    it is the currently-active selection, and the query string clicking it produces (add, or remove
    if already active). The template only prints — no link-building, no filter logic in HTML."""

    label: str
    count: int
    active: bool
    query: str


@dataclass(frozen=True, slots=True)
class _FacetGroup:
    """A filter-rail facet group (one ``<details>`` dropdown): its German heading and its items.
    Every group shows a bare right-aligned count (collection counts are subtree counts now — no
    "direkt:" hedge)."""

    heading: str
    items: tuple[_FacetItem, ...]
    open: bool = False


@dataclass(frozen=True, slots=True)
class _FilterChip:
    """One active filter as a rail chip (register row 3 inversion): its group heading, the active
    value's label, and the query string that REMOVES it (``browse.without_param`` — the chip ✕ and
    the dropdown's active row clear the same filter through the same link algebra)."""

    group: str
    label: str
    query: str


def _filter_chips(
    params: dict[str, str], parsed: browse.ParsedQuery, bestand: BestandChooser
) -> tuple[_FilterChip, ...]:
    """Every active filter as a rail chip, derived from the PARSED URL state — not from the facet
    counts. The distinction matters exactly on the zero-hit page: a filter that matches nothing
    vanishes from the recomputed counts (so the dropdown shows no active row), but its chip must
    stay — the empty state says "Entferne einzelne Filter", and the chip ✕ is that affordance.
    Labels mirror the dropdowns' (collection ULIDs resolve to names; the Datum bounds/toggle
    reuse the group's own spellings); headings mirror the group headings."""
    f = parsed.filters
    chips: list[_FilterChip] = []

    def chip(param: str, group: str, label: str) -> None:
        chips.append(
            _FilterChip(group=group, label=label, query=browse.without_param(params, param))
        )

    if f.collection is not None:
        chip(browse.PARAM_COLLECTION, "Bestand", bestand.name_of(f.collection) or f.collection)
    if f.media_type is not None:
        chip(browse.PARAM_MEDIA_TYPE, "Medienart", f.media_type)
    if f.document_type is not None:
        chip(browse.PARAM_DOCUMENT_TYPE, "Dokumenttyp", f.document_type)
    if f.tag is not None:
        chip(browse.PARAM_TAG, "Schlagworte", f.tag)
    if f.decade is not None:
        chip(browse.PARAM_DECADE, "Jahrzehnte", str(f.decade))
    if f.date_from is not None:
        chip(browse.PARAM_DATE_FROM, "Datum", f"von: {f.date_from.isoformat()}")
    if f.date_to is not None:
        chip(browse.PARAM_DATE_TO, "Datum", f"bis: {f.date_to.isoformat()}")
    if f.dateless:
        chip(browse.PARAM_DATELESS, "Datum", "Ohne Datum")
    return tuple(chips)


@dataclass(frozen=True, slots=True)
class _PaneMedia:
    """One media entry in the preview pane: its caption (may be empty) and the gated thumbnail URL.
    The URL points at the existing /media/<ulid>/<hash>/thumb route, which re-authorizes on its own
    (a thumbnail leaks the image) — the pane never inlines bytes."""

    caption: str
    thumb_url: str


@dataclass(frozen=True, slots=True)
class _Pane:
    """The preview pane view-model, built ONLY from a ``visible``-projected Article (so no floored
    field can reach it). ``media`` is cover-first (the tuple's order is meaning, ADR 0015). The
    Bearbeiten href is archivist-only (empty otherwise) and points at the edit form; Öffnen goes
    to the detail read view."""

    ulid: str
    title: str
    ref_code: str
    datierung: str
    typ: str
    media: tuple[_PaneMedia, ...]
    oeffnen_href: str
    bearbeiten_href: str
    close_href: str


def _resolve_pane(request: HttpRequest, *, is_archivist: bool) -> _Pane | None:
    """Resolve the ``?artikel`` param to a preview-pane view-model, or ``None`` when there is no
    pane to show. Fail-closed by delegating to the ONE render-resolution path
    (``resolve_visible_article`` = load + chain + ``visible``): a malformed, absent, or DENIED ulid
    all return ``None`` here, so the caller renders the byte-identical no-pane workbench (no
    existence oracle). An absent ``artikel`` param is simply no pane."""
    ulid = request.GET.get(_PANE_PARAM)
    if not ulid:
        return None
    article = resolve_visible_article(request, ulid)
    if article is None:
        return None  # malformed / absent / denied — all indistinguishable, no pane
    media = tuple(
        _PaneMedia(caption=m.caption or "", thumb_url=thumbnail_url(article.ulid, m.content_hash))
        for m in article.media
    )
    # The ✕ close target: the SAME search minus only the pane selection (artikel). Strip artikel like
    # _results_context does — keep text/facets/sort/page — so closing the pane never blows away the
    # query (a bare "?" would). artikel is pane state, not search state.
    close_params = {k: v for k, v in request.GET.dict().items() if k != _PANE_PARAM}
    close_query = urlencode(close_params)
    return _Pane(
        ulid=article.ulid,
        title=article.title,
        ref_code=article.ref_code or "",
        datierung=vocab.datierung_mono(article.date),
        typ=article.document_type or "",
        media=media,
        oeffnen_href=reverse("artikel-detail", args=[article.ulid]),
        # Bearbeiten goes straight to the 4.7 edit form (userflows flow 1: PANE → Bearbeiten → EDIT).
        bearbeiten_href=reverse("artikel-bearbeiten", args=[article.ulid]) if is_archivist else "",
        close_href="?" + close_query if close_query else "?",
    )


# Which index facet key feeds which rail facet group: (facet key, param key, German heading). The
# collection group resolves ULIDs → names separately (below); the rest show the value verbatim.
_FACET_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("media_type", browse.PARAM_MEDIA_TYPE, "Medienart"),
    ("document_type", browse.PARAM_DOCUMENT_TYPE, "Dokumenttyp"),
    ("tags", browse.PARAM_TAG, "Schlagworte"),
    ("decades", browse.PARAM_DECADE, "Jahrzehnte"),
)

# The ledger's column headers: (German label, css-modifier key, sortierung label or None). SIG /
# TITEL / DATIERUNG are sortable (their sortierung label is a key in browse._SORT_BY_LABEL minus
# relevanz, which has no column). TYP is NOT a sortable index column, so it is a plain header (None).
# The action gutter is added by the ledger component. This IS the whole column anatomy (owner
# 2026-08-07): the SICHTBARKEIT column died — visibility strings render nowhere in the ledger, and
# the ENTWURF deviation rides with the title. Presentation only — sort is browse.
_LEDGER_COLUMNS: tuple[tuple[str, str, str | None], ...] = (
    ("Sig", "sig", "signatur"),
    ("Titel", "titel", "titel"),
    ("Datierung", "datierung", "datierung"),
    ("Typ", "typ", None),
)


def _ledger_row(
    hit: SearchHit,
    *,
    is_archivist: bool,
    selected_ulid: str | None,
    vorschau_prefix: str,
    auswahl: frozenset[str],
) -> dict[str, object]:
    """One ledger row view-model from a SearchHit — a plain dict the ledger component prints (no
    logic in the template). The ENTWURF flag + Bearbeiten href + bulk checkbox are archivist
    chrome: left EMPTY/False for non-archivists here (and the ledger component renders no control
    without them), so nothing rides in the DOM for them. ``selected_ulid`` marks the row shown in
    the pane; ``auswahl`` is the bulk selection as a set (this row's checkbox is checked + the row
    inverts when its ulid is in it). ``vorschau_prefix`` is the row-invariant encoded pane-link
    prefix (``browse.pane_query_prefix`` — search state + the whole selection), computed once per
    page; only the trailing ``artikel=<ulid>`` differs per row."""
    return {
        "title": hit.title,
        # ONE-CLICK ENTRY (owner 2026-08-07): the Titel IS the canonical detail navigation — no
        # pane interception; the way back to the search is browser Back.
        "href": reverse("artikel-detail", args=[hit.ulid]),
        "ulid": hit.ulid,
        "ref_code": hit.ref_code or "",
        "datierung": hit.date_edtf or "",
        "typ": hit.document_type or "",
        "draft": hit.is_draft if is_archivist else False,
        "bearbeiten_href": reverse("artikel-bearbeiten", args=[hit.ulid]) if is_archivist else "",
        # The explicit pane affordance for EVERY viewer (the pane itself re-authorizes
        # fail-closed): a plain GET link, keeping search + selection state. ULIDs are
        # Crockford base32, so the one per-row pair needs no encoding.
        "vorschau_href": (
            f"?{vorschau_prefix}&{_PANE_PARAM}={hit.ulid}"
            if vorschau_prefix
            else f"?{_PANE_PARAM}={hit.ulid}"
        ),
        "selected": hit.ulid == selected_ulid,
        "gewaehlt": is_archivist and hit.ulid in auswahl,
    }


def _ledger_rows(
    page: object,
    *,
    is_archivist: bool,
    selected_ulid: str | None,
    vorschau_prefix: str,
    auswahl: frozenset[str],
) -> tuple[dict[str, object], ...]:
    """The ledger row view-models for the page's SearchHits. The title link points at the
    canonical detail route ``/artikel/<ulid>`` (plain navigation, works with no JS on every
    viewport); the pane opens via each row's explicit Vorschau link. No visibility logic — that
    already happened in ``search``; the archivist chrome is a presentation gate off
    ``is_archivist``."""
    hits: tuple[SearchHit, ...] = page.hits  # type: ignore[attr-defined]
    return tuple(
        _ledger_row(
            hit,
            is_archivist=is_archivist,
            selected_ulid=selected_ulid,
            vorschau_prefix=vorschau_prefix,
            auswahl=auswahl,
        )
        for hit in hits
    )


def _ledger_columns(
    active_label: str, descending: bool, params: dict[str, str]
) -> tuple[dict[str, object], ...]:
    """The ledger's column headers. SIG / TITEL / DATIERUNG are the sort control (the select is gone):
    clicking cycles asc → desc → default. The link a header points at is its NEXT state:
      inactive        -> ?sortierung=<label>        (ascending)
      active ascending -> ?sortierung=-<label>       (descending)
      active descending -> clear sortierung          (back to default / Relevanz)
    The active column shows ▲ (asc) or ▼ (desc). TYP is not a sortable index column, so it is a plain
    header (sortable False, no query). Every header keeps its label-role treatment; presentation
    only — the sort itself is browse/search. The browse link algebra preserves other params + resets
    the page."""
    cols: list[dict[str, object]] = []
    for label, key, sort_key in _LEDGER_COLUMNS:
        if sort_key is None:  # TYP — plain, non-sortable header
            cols.append({"label": label, "key": key, "sortable": False})
            continue
        active = active_label == sort_key
        if not active:
            query = browse.with_param(params, browse.PARAM_SORT, sort_key)  # -> ascending
        elif not descending:
            query = browse.with_param(params, browse.PARAM_SORT, f"-{sort_key}")  # -> descending
        else:
            query = browse.without_param(params, browse.PARAM_SORT)  # -> default (clear)
        cols.append(
            {
                "label": label,
                "key": key,
                "sortable": True,
                "query": query,
                "active": active,
                "order": "desc" if (active and descending) else "asc",
            }
        )
    return tuple(cols)


#: The active-filter query params the search form echoes as hidden inputs (GH #21), in a fixed
#: render order: the ONE filter-dimension list (``browse.FILTER_PARAMS``, which the rail's
#: clear-all clears) plus the sort. Every ``browse`` search-state key EXCEPT ``q`` (the form's own
#: live input, never duplicated as hidden) and ``seite`` (a new search deliberately resets to
#: page 1 — kept as-is).
_FORM_FILTER_PARAMS: tuple[str, ...] = (*browse.FILTER_PARAMS, browse.PARAM_SORT)


def _form_filters(params: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """The active filter params as ``(key, value)`` pairs for the search form's hidden inputs — read
    from the SAME ``params`` mapping the facet/sort/pagination links below build from, so the form
    and the rail can never drift out of sync (GH #21: typing refines WITHIN the active filter
    scope). A blank or absent param is omitted entirely — never an empty-value hidden input."""
    return tuple((key, params[key]) for key in _FORM_FILTER_PARAMS if params.get(key))


def _results_context(
    request: HttpRequest,
    parsed: browse.ParsedQuery,
    page: object,
    *,
    is_archivist: bool,
    selected_ulid: str | None,
    auswahl: list[str],
) -> dict[str, object]:
    """The template context shared by the full page and the results partial. Every link the
    rail/pagination/ledger need is prebuilt in Python from the local ``params`` dict (the
    template calls no functions with args), so the raw query dict itself is never handed to the
    template. No visibility logic — that already happened in ``search``; the ledger's archivist
    chrome is a presentation gate off ``is_archivist``.

    ``artikel`` (pane) and ``auswahl`` (bulk selection) are STRIPPED from the link-building
    ``params``: neither is search state, so no facet/sort link may carry them. The PAGINATION links
    re-attach the full multi-valued ``auswahl`` (so paging never drops the selection), and the
    "Alle auf dieser Seite" link appends this page's ulids — both via the auswahl-preserving
    helpers. Pane selection is tracked separately via ``selected_ulid``."""
    params = {
        k: v for k, v in request.GET.dict().items() if k not in (_PANE_PARAM, browse.PARAM_AUSWAHL)
    }
    total: int = page.total  # type: ignore[attr-defined]
    size = len(page.hits)  # type: ignore[attr-defined]
    bestand = BestandChooser.of(Archive.canonical())
    context: dict[str, object] = {
        "text": parsed.text or "",
        # The search form's hidden inputs (GH #21) — every active filter, so typing a new q keeps
        # refining WITHIN the current filter scope instead of silently dropping it.
        "filter_params": _form_filters(params),
        "page": page,
        "facet_groups": _facet_groups(params, parsed, page, bestand),
        # The rail's active-filter chips — from the parsed URL state, so a zero-hit filter keeps
        # its removal affordance even after it vanishes from the recomputed facet counts.
        "filter_chips": _filter_chips(params, parsed, bestand),
        # "Alle Filter entfernen" at the END of the chip row (owner 2026-08-07, rail round 2):
        # drops every filter param, keeps q + sort. The template renders it only alongside chips.
        "clear_filters_query": browse.clear_filters_query(params),
        "ledger_rows": _ledger_rows(
            page,
            is_archivist=is_archivist,
            selected_ulid=selected_ulid,
            # both row-invariant: encoded once here, not once per row
            vorschau_prefix=browse.pane_query_prefix(params, auswahl),
            auswahl=frozenset(auswahl),
        ),
        "ledger_columns": _ledger_columns(_sort_label(parsed.sort), parsed.descending, params),
        "current_page": parsed.page,
        "has_next": browse.has_next_page(
            page=parsed.page, page_size=browse.PAGE_SIZE, hits_on_page=size, total=total
        ),
        "has_prev": parsed.page > 1,
        "next_query": browse.page_query_with_auswahl(params, auswahl, parsed.page + 1),
        "prev_query": browse.page_query_with_auswahl(params, auswahl, parsed.page - 1),
        "total": total,
        # When a zero-hit result is filtered ONLY by a Bestand (no text, no other facet), the empty
        # state is Bestand-specific ("Noch keine Artikel in diesem Bestand." + an archivist create
        # link pre-seeded with it) instead of the generic "remove filters" copy (4.8 item 3).
        "leerer_bestand": _only_bestand_filter(parsed) if total == 0 else None,
    }
    if is_archivist:
        context.update(_bulk_bar_context(params, page, auswahl, bestand))
    return context


def _only_bestand_filter(parsed: browse.ParsedQuery) -> str | None:
    """The Bestand ulid when the search's ONLY constraint is that collection (no text, no other
    facet) — else ``None``. Used to pick the Bestand-specific empty state over the generic one."""
    f = parsed.filters
    others_empty = (
        not parsed.text
        and f.media_type is None
        and f.document_type is None
        and f.tag is None
        and f.decade is None
        and f.date_from is None
        and f.date_to is None
        and not f.dateless
    )
    return f.collection if f.collection is not None and others_empty else None


def _bulk_bar_context(
    params: dict[str, str],
    page: object,
    auswahl: list[str],
    bestand: BestandChooser,
) -> dict[str, object]:
    """The sticky bulk bar + chooser drawer context (spec §2 B/C), archivist-only.

    The bar's AFFORDANCES render whenever there are hits: the "Änderung prüfen" submit (POSTs the
    checked boxes — a zero-check submit hits the existing "Keine Artikel ausgewählt." reject) and
    the "Alle auf dieser Seite" page-select link, so the NO-JS path reaches the feature with no
    prior selection. Visibility is PROGRESSIVE (owner 2026-08-07, reverses the #16 cold-start
    ruling): the server always renders the disclosure visible; catalog_bulk.js hides it while the
    live selection count is 0 and reveals it on the first tick. Signals-once still holds for
    STATUS: ``has_auswahl`` gates the "{n} ausgewählt" count + "Auswahl aufheben" so an empty
    selection shows no "0 ausgewählt".

    The client can only hide what it fully accounts for (learning G.25): ``auswahl_offpage_count``
    is the part of the URL-borne selection that is NOT on this page, so the enhancement can add its
    own live checkbox count to a number it cannot otherwise see. Without it the JS counted this
    page's boxes alone and hid a live cross-page selection — the archivist on page 2 could neither
    see, clear nor apply it.

    Bar suppressed only when there are no hits (nothing to select) — ``_results.html`` already gates
    the whole results block on ``page.hits``, so this returns the off flag defensively for that case.
    """
    hits: tuple[SearchHit, ...] = page.hits  # type: ignore[attr-defined]
    if not hits:
        return {"bulk_bar": False}
    page_ulids = [h.ulid for h in hits]
    on_page = set(page_ulids)
    context: dict[str, object] = {
        "bulk_bar": True,
        "has_auswahl": bool(auswahl),
        "auswahl_offpage_count": sum(1 for u in auswahl if u not in on_page),
        "select_page_query": browse.select_page_query(params, auswahl, page_ulids),
        **bulk.feldwahl_context(bestand),
    }
    if auswahl:
        context["auswahl_count"] = len(auswahl)
        # "Auswahl aufheben" drops the selection but KEEPS the active search (params already exclude
        # auswahl + artikel) — a bare "?" would wipe the filters (design-gate MED finding).
        context["clear_auswahl_query"] = urlencode({k: v for k, v in params.items() if v})
    return context


def _facet_groups(
    params: dict[str, str],
    parsed: browse.ParsedQuery,
    page: object,
    bestand: BestandChooser,
) -> tuple[_FacetGroup, ...]:
    """Build every rail facet group + the "Ohne Datum" bucket as fully-resolved view-models. The
    collection group resolves ULID facet values to Collection names (via ``bestand``, the shared
    per-request load) and is marked ``direct``; the "Ohne Datum" bucket is a single toggle item."""
    facets = page.facets  # type: ignore[attr-defined]
    groups: list[_FacetGroup] = [_collection_group(params, facets.get("collection", ()), bestand)]
    groups += [
        _FacetGroup(heading, _facet_items(params, param, facets.get(key, ())))
        for key, param, heading in _FACET_GROUPS
    ]
    groups.append(_datum_group(params, parsed, page))
    return tuple(g for g in groups if g.items)


def _facet_items(
    params: dict[str, str],
    param: str,
    counts: tuple[FacetCount, ...],
    *,
    labels: Mapping[str, str] | None = None,
) -> tuple[_FacetItem, ...]:
    """Turn a facet's ``FacetCount``s into clickable items. ``labels`` optionally maps the raw value
    to a display name (used for collection ULIDs). An item whose value is the current selection is
    marked active and its query REMOVES it (click-to-toggle); otherwise the query ADDS it."""
    active_value = params.get(param, "")
    items = []
    for fc in counts:
        is_active = fc.value == active_value
        query = (
            browse.without_param(params, param)
            if is_active
            else browse.with_param(params, param, fc.value)
        )
        label = (labels or {}).get(fc.value, fc.value)
        items.append(_FacetItem(label=label, count=fc.count, active=is_active, query=query))
    return tuple(items)


def _collection_group(
    params: dict[str, str],
    counts: tuple[FacetCount, ...],
    bestand: BestandChooser,
) -> _FacetGroup:
    """The Bestand facet: ULIDs resolved to Collection names. Counts are SUBTREE counts (the query
    facets over ``collection_ancestors``), so the number matches what clicking the (subtree) filter
    yields — a bare right-aligned count like every other group (the old "direkt:" hedge is gone).
    Empty ``counts`` yields an empty group (dropped by ``_facet_groups``) — and resolves no names,
    keeping the shared load lazy."""
    labels = bestand.names() if counts else {}
    return _FacetGroup(
        "Bestand",
        _facet_items(params, browse.PARAM_COLLECTION, counts, labels=labels),
    )


def _datum_group(params: dict[str, str], parsed: browse.ParsedQuery, page: object) -> _FacetGroup:
    """The DATUM group: the "Ohne Datum" toggle PLUS any active von/bis range, each as a removable
    row (the chips row died — active date filters are removed here, like every other facet).

    "Ohne Datum" (data honesty, ideas §1.3): a toggle counting in-scope dateless rows; shown when
    there ARE dateless rows OR it is already on. Active → removes it; inactive → adds ``ohne_datum``.
    von/bis: an active bound shows as an active row (count 0 — a bound is a state, not a bucket) whose
    query removes just that bound. Order: von, bis, then Ohne Datum."""
    items: list[_FacetItem] = []
    for param, label in ((browse.PARAM_DATE_FROM, "von"), (browse.PARAM_DATE_TO, "bis")):
        raw = params.get(param)
        if raw:
            items.append(
                _FacetItem(
                    label=f"{label}: {raw}",
                    count=0,
                    active=True,
                    query=browse.without_param(params, param),
                )
            )
    count: int = page.dateless_count  # type: ignore[attr-defined]
    active = parsed.filters.dateless
    if count > 0 or active:
        query = (
            browse.without_param(params, browse.PARAM_DATELESS)
            if active
            else browse.with_param(params, browse.PARAM_DATELESS, "1")
        )
        items.append(_FacetItem(label="Ohne Datum", count=count, active=active, query=query))
    return _FacetGroup("Datum", tuple(items))


def _sort_label(sort: str) -> str:
    """The German sort label for the active ``SortOrder`` — the inverse of ``browse._SORT_BY_LABEL``.
    Feeds ``_ledger_columns`` active-column detection (the sort <select> is gone; the column headers
    are the sort control): a header is active when its ``sort_key`` equals this label. Falls to
    "relevanz" (the default, which has no sortable column)."""
    return next(
        (label for label, order in browse._SORT_BY_LABEL.items() if order == sort), "relevanz"
    )


def article_detail(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /artikel/<ulid>`` — the 4.6 Lesesaal detail read view (spec §§3-4).

    ONE resolution path (``resolve_visible_detail``): load once, resolve chain, ``visible``-project —
    any deny/absence/malformed/broken-chain → the byte-identical 404 (existence-hiding). The template
    is a SINGLE file fed a projected Article, so archivist-only fields (Standort, Weitere Angaben) are
    floored to None/() before rendering and vanish through the same ``{% if value %}`` — there is no
    member-vs-archivist template fork (spec §4/§10). The archivist's tools are presentation-gated
    on ``is_archivist``."""
    resolution = resolve_visible_detail(request, ulid)
    if resolution is None:
        return _not_found()
    return render_screen(request, "workbench/detail.html", _detail_context(resolution))


@dataclass(frozen=True, slots=True)
class _DetailMedia:
    """One plate in the filmstrip (or the cover): its caption, the gated thumb URL, and the full
    gated byte URL a click opens. The page never inlines bytes — both point at the /media routes,
    which re-authorize per request."""

    caption: str
    thumb_url: str
    file_url: str


@dataclass(frozen=True, slots=True)
class BestandCrumb:
    """One Bestand breadcrumb hop: the collection name + the workbench link into its facet."""

    name: str
    href: str


def bestand_crumbs(chain: ResolvedChain) -> tuple[BestandCrumb, ...]:
    """The chain as crumbs, root first (the chain is leaf-first), each opening the scoped list."""
    return tuple(
        BestandCrumb(
            name=c.name,
            href=f"{reverse('workbench')}?{browse.with_param({}, browse.PARAM_COLLECTION, c.ulid)}",
        )
        for c in reversed(chain.collections)
    )


@dataclass(frozen=True, slots=True)
class _DetailTag:
    """One Schlagwort: the tag text + the workbench link into the tag facet."""

    label: str
    href: str


def _body_paragraphs(body: str) -> tuple[str, ...]:
    """Split the Markdown ``body`` into paragraphs on blank lines (spec §3). No Markdown rendering in
    this minimal slice — each paragraph is emitted as an autoescaped ``<p>``, so no markup is
    interpreted (rich rendering is a later owner decision, §11). Empty/whitespace body → ()."""
    return tuple(block.strip() for block in body.split("\n\n") if block.strip())


def _detail_media(article: Article) -> tuple[_DetailMedia, ...]:
    """The article's media as filmstrip view-models, cover-first (the tuple order is meaning). Thumb
    + full-byte URLs point at the gated /media routes (never inline bytes)."""
    return tuple(
        _DetailMedia(
            caption=m.caption or "",
            thumb_url=thumbnail_url(article.ulid, m.content_hash),
            file_url=media_url(article.ulid, m.content_hash),
        )
        for m in article.media
    )


def _detail_context(resolution: DetailResolution) -> dict[str, object]:
    """The detail template context, built ONLY from the projected Article (no floored field can reach
    it) + the member-safe chain. Every value is `{% if %}`-gated in the template, so an absent field
    (or a floored archivist-only field) renders nothing — no member/archivist fork, no "—"
    placeholders. The crumbs run root→leaf; tags + crumbs link back into the workbench facets (the
    archive's browsing loop)."""
    article = resolution.article
    is_draft = article.lifecycle is Lifecycle.DRAFT
    media = _detail_media(article)
    tags = tuple(
        _DetailTag(
            label=t, href=f"{reverse('workbench')}?{browse.with_param({}, browse.PARAM_TAG, t)}"
        )
        for t in article.tags
    )
    return {
        "ulid": article.ulid,
        "is_draft": is_draft,
        "version": resolution.version,
        # preview() names groups and ignores the lifecycle: archivists only (part-4-web.md)
        "publish_statement": (
            vocab.publish_statement(preview(article, resolution.chain))
            if resolution.is_archivist and is_draft
            else ""
        ),
        "title": article.title,
        "ref_code": article.ref_code or "",
        "datierung": vocab.datierung_parts(article.date),
        "typ": article.document_type or article.media_type or "",
        "creator": article.creator or "",
        "ort": article.subject_place or "",
        # Beschreibung: split the Markdown body into paragraphs on blank lines and render each as an
        # escaped <p> (spec §3 — no Markdown dependency in this minimal slice; the template autoescapes,
        # so no markup is interpreted). Flagged to the owner as §11: rich Markdown rendering is a later
        # decision, not manufactured here.
        "body_paragraphs": _body_paragraphs(article.body),
        "crumbs": bestand_crumbs(resolution.chain),
        "tags": tags,
        "umfang": len(media),
        "cover": media[0] if media else None,
        "weitere": media[1:],
        "standort": article.physical_location or "",
        "custom": article.custom,
    }
