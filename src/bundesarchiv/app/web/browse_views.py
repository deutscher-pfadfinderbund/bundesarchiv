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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import render
from django.urls import reverse

from bundesarchiv.app.web import browse, bulk, vocab
from bundesarchiv.app.web.article_auth import (
    DetailResolution,
    resolve_visible_article,
    resolve_visible_detail,
)
from bundesarchiv.app.web.media_views import _not_found, media_url, thumbnail_url
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.models import Article, Collection, Lifecycle, Ulid
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index import search
from bundesarchiv.index.query import FacetCount, SearchHit
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository

#: The web package's static/ dir. Production CSS/JS is served from here by WhiteNoise via
#: {% static %} (ADR 0016); ``_serve_static`` only reaches it now for the dev variant/layout
#: stylesheet routes (/_dev/static/*).
_STATIC_DIR = Path(__file__).parent / "static"

#: The preview-pane selection param. NOT a search param — it is stripped from every search link so
#: a denied/absent/malformed value leaves the page byte-identical to no pane (existence-hiding).
_PANE_PARAM = "artikel"

#: The shared per-request collection-names loader (a memoized zero-arg callable): built once in
#: ``_results_context`` and passed to both consumers, so the names load at most once per request —
#: and not at all on a page that resolves none (issue #2 P1).
type _NamesLoader = Callable[[], dict[Ulid, str]]

#: The bulk-edit Feld chooser options: (target, German label), DERIVED from bulk.FIELDS (the single
#: source) so labels/allowlist can never drift. Placeholder first (empty, server-rejected with
#: "Bitte ein Feld wählen."). audience/lifecycle/sichtbarkeit are absent by construction (spec §0.7).
_BULK_FELD_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", "— Feld wählen —"),
    *((f.target, f.label) for f in bulk.FIELDS),
)


def _bulk_collection_options(names: _NamesLoader) -> tuple[tuple[str, str], ...]:
    """The Sammlungsteil (collection) options for the bulk drawer: placeholder first, then every
    collection as ``(ulid, name)``. A value outside this set is server-rejected like an empty one."""
    return (("", "— Bestand wählen —"), *sorted(names().items(), key=lambda kv: kv[1]))


def workbench(request: HttpRequest) -> HttpResponse:
    """``GET /`` — the workbench: search field, results, facet sidebar, "Neuer Artikel" button.

    Pipeline: parse the query string (pure ``browse``), resolve the viewer, run the viewer-scoped
    ``search``, resolve collection-facet ULIDs to Collection names for display, then render. On a
    plain ``HX-Request`` only the results region renders (same data, same partial) — the no-JS full
    page and the HTMX swap are one code path. A history-restore request (``HX-Request`` PLUS
    ``HX-History-Restore-Request``) gets the full page — htmx swaps the whole document on a
    Back-button restore."""
    parsed = browse.parse_query(request.GET)
    viewer = viewer_of(request)
    # Presentation-only chrome flag: the templates hide archivist affordances (SICHTBARKEIT column,
    # ENTWURF badge, Bearbeiten, "Neuer Artikel") for non-Archivists. This is NOT scoping (§11) —
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
    # The ledger folds narrow while the pane is open (the split-narrow layout); the frame class
    # drives it (and the <1280px media query hides the pane + unfolds the ledger — css owns that).
    context["vorschau"] = pane is not None
    # History-restore requests carry BOTH HX-Request and HX-History-Restore-Request: htmx replaces
    # the whole document on a Back-button restore (a cache miss), so this branch must win over the
    # plain HX-Request check below — otherwise the restore renders the chrome-less results partial.
    if request.headers.get("HX-History-Restore-Request"):
        return render(request, "workbench/workbench.html", context)
    if request.headers.get("HX-Request"):
        return render(request, "workbench/_results.html", context)
    return render(request, "workbench/workbench.html", context)


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
    """A sidebar facet section: its German heading and its items. Every group shows a bare
    right-aligned count (collection counts are subtree counts now — no "direkt:" hedge)."""

    heading: str
    items: tuple[_FacetItem, ...]


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
    Bearbeiten href is archivist-only (empty otherwise); Öffnen points at the detail stub."""

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
    # Öffnen carries the current search back to the detail page via ?zurueck (search state only —
    # artikel + auswahl excluded), so its "Zurück zur Suche" restores this search (spec §2).
    search_params = {
        k: v for k, v in request.GET.dict().items() if k not in (_PANE_PARAM, browse.PARAM_AUSWAHL)
    }
    return _Pane(
        ulid=article.ulid,
        title=article.title,
        ref_code=article.ref_code or "",
        datierung=article.date.value if article.date is not None else "",
        typ=article.document_type or "",
        media=media,
        oeffnen_href=f"{reverse('artikel-detail', args=[article.ulid])}{_zurueck_suffix(search_params)}",
        # Bearbeiten target is the detail stub for now; 4.7 repoints it at the edit form.
        bearbeiten_href=reverse("artikel-detail", args=[article.ulid]) if is_archivist else "",
        close_href="?" + close_query if close_query else "?",
    )


def _zurueck_suffix(search_params: dict[str, str]) -> str:
    """The ``?zurueck=<encoded current search>`` suffix a detail link carries so the detail page's
    "Zurück zur Suche" restores this search (spec §2). ``search_params`` must already exclude the
    pane (artikel) + bulk (auswahl) keys — only search state travels. Empty string when there is no
    active search (the detail page then falls back to a bare "/")."""
    current = urlencode({k: v for k, v in search_params.items() if v != ""})
    return f"?{urlencode({'zurueck': current})}" if current else ""


# Which index facet key feeds which sidebar group: (facet key, param key, German heading). The
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
# SICHTBARKEIT + the action gutter are added by the ledger component. Presentation only — sort is
# browse.
_LEDGER_COLUMNS: tuple[tuple[str, str, str | None], ...] = (
    ("Sig", "sig", "signatur"),
    ("Titel", "titel", "titel"),
    ("Datierung", "datierung", "datierung"),
    ("Typ", "typ", None),
)


def _visibility_label(tier: str | None, groups: tuple[str, ...]) -> str:
    """Render a hit's STRUCTURED scope data (tier + group names) to the German Sichtbarkeit string.

    Presentation only — it maps the index scope columns the hit already carries; it does NOT
    re-derive visibility (that is search()/_viewer_scope). Only the archivist ledger renders this
    (the template gates it), and the data is leak-free on scoped rows by construction (SearchHit
    docstring). ``tier is None`` is an archivist-only row (a fail-closed row that is not a draft) —
    it has no ladder rung, so it shows nothing here. The rung captions come from the shared ``vocab``
    source (the index scope strings differ from the domain enum, so the mapping stays here)."""
    match tier:
        case "PUBLIC":
            return vocab.SICHTBARKEIT_PUBLIC
        case "MEMBERS":
            return vocab.SICHTBARKEIT_MEMBERS
        case "GROUPS":
            return vocab.groups_label(groups)
        case _:
            return ""


def _ledger_row(
    hit: SearchHit,
    *,
    is_archivist: bool,
    selected_ulid: str | None,
    auswahl: frozenset[str],
    zurueck: str,
) -> dict[str, object]:
    """One ledger row view-model from a SearchHit — a plain dict the ledger component prints (no
    logic in the template). The Sichtbarkeit string + ENTWURF flag + Bearbeiten action + bulk
    checkbox are archivist chrome: left EMPTY/False for non-archivists here (and the ledger component
    also omits those columns), so nothing rides in the DOM for them. ``selected_ulid`` marks the row
    shown in the pane; ``auswahl`` is the bulk-selected set (this row's checkbox is checked + the row
    inverts when its ulid is in it). ``zurueck`` is the encoded ``?zurueck=`` suffix carrying the
    current search so the detail page's "Zurück zur Suche" returns here (empty when no search)."""
    return {
        "title": hit.title,
        # BASELINE href = the canonical detail route: it works without JS on every viewport (below
        # 1280px the pane is CSS-hidden, so ?artikel would be a dead click for a no-JS narrow user).
        # ledger_pane.js progressively upgrades this to the ?artikel pane on wide viewports (see the
        # data-artikel hook). No-JS behavior: the detail link everywhere. ?zurueck carries the search
        # back so detail's "Zurück zur Suche" restores it (spec §2).
        "href": f"{reverse('artikel-detail', args=[hit.ulid])}{zurueck}",
        "artikel_ulid": hit.ulid,
        "ulid": hit.ulid,
        "ref_code": hit.ref_code or "",
        "datierung": hit.date_edtf or "",
        "typ": hit.document_type or "",
        "draft": hit.is_draft if is_archivist else False,
        "visibility": _visibility_label(hit.tier, hit.groups) if is_archivist else "",
        # Bearbeiten target is the detail stub for now; 4.7 repoints it at the edit form.
        "action_label": "Bearbeiten" if is_archivist else "",
        "action_href": reverse("artikel-detail", args=[hit.ulid]) if is_archivist else "",
        "selected": hit.ulid == selected_ulid,
        "gewaehlt": is_archivist and hit.ulid in auswahl,
    }


def _ledger_rows(
    page: object,
    *,
    is_archivist: bool,
    selected_ulid: str | None,
    auswahl: frozenset[str],
    zurueck: str,
) -> tuple[dict[str, object], ...]:
    """The ledger row view-models for the page's SearchHits. The title link's BASELINE points at the
    canonical detail route ``/artikel/<ulid>`` (works with no JS, every viewport); ``ledger_pane.js``
    progressively upgrades it to the ``?artikel`` pane on wide viewports. No visibility logic — that
    already happened in ``search``; the archivist chrome is a presentation gate off ``is_archivist``.
    ``zurueck`` is the shared encoded return suffix (same for every row — the current search)."""
    hits: tuple[SearchHit, ...] = page.hits  # type: ignore[attr-defined]
    return tuple(
        _ledger_row(
            hit,
            is_archivist=is_archivist,
            selected_ulid=selected_ulid,
            auswahl=auswahl,
            zurueck=zurueck,
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
#: render order. Every ``browse`` search-state key EXCEPT ``q`` (the form's own live input, never
#: duplicated as hidden) and ``seite`` (a new search deliberately resets to page 1 — kept as-is).
_FORM_FILTER_PARAMS: tuple[str, ...] = (
    browse.PARAM_COLLECTION,
    browse.PARAM_MEDIA_TYPE,
    browse.PARAM_DOCUMENT_TYPE,
    browse.PARAM_TAG,
    browse.PARAM_DECADE,
    browse.PARAM_DATELESS,
    browse.PARAM_DATE_FROM,
    browse.PARAM_DATE_TO,
    browse.PARAM_SORT,
)


def _form_filters(params: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """The active filter params as ``(key, value)`` pairs for the search form's hidden inputs — read
    from the SAME ``params`` mapping the facet/sort/pagination links below build from, so the form
    and the sidebar can never drift out of sync (GH #21: typing refines WITHIN the active filter
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
    sidebar/pagination/ledger need is prebuilt in Python from the local ``params`` dict (the
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
    auswahl_set = frozenset(auswahl)
    # The ONE per-request collection-names load, memoized and shared by its two consumers (the
    # Bestand facet labels + the bulk drawer's options) — and LAZY: a page that resolves no names
    # (zero hits, no collection counts, non-archivist) never loads at all (issue #2 P1, pinned).
    names = cache(_collection_names)
    # The ?zurueck= suffix every detail link carries: the current search (params already excludes
    # artikel + auswahl), so the detail page's "Zurück zur Suche" restores it. Empty when no search.
    zurueck = _zurueck_suffix(params)
    context: dict[str, object] = {
        "text": parsed.text or "",
        # The search form's hidden inputs (GH #21) — every active filter, so typing a new q keeps
        # refining WITHIN the current filter scope instead of silently dropping it.
        "filter_params": _form_filters(params),
        "page": page,
        "facet_groups": _facet_groups(params, parsed, page, names),
        "ledger_rows": _ledger_rows(
            page,
            is_archivist=is_archivist,
            selected_ulid=selected_ulid,
            auswahl=auswahl_set,
            zurueck=zurueck,
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
        context.update(_bulk_bar_context(params, page, auswahl, names))
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
    names: _NamesLoader,
) -> dict[str, object]:
    """The sticky bulk bar + chooser drawer context (spec §2 B/C), archivist-only.

    The bar's AFFORDANCES render whenever there are hits (cold-start fix, #16): the "Änderung prüfen"
    submit (POSTs the checked boxes — a zero-check submit hits the existing "Keine Artikel
    ausgewählt." reject) and the "Alle auf dieser Seite" page-select link, so the feature is reachable
    with no prior selection. Signals-once still holds for STATUS: ``has_auswahl`` gates the
    "{n} ausgewählt" count + "Auswahl aufheben" so an empty selection shows no "0 ausgewählt".

    Bar suppressed only when there are no hits (nothing to select) — ``_results.html`` already gates
    the whole results block on ``page.hits``, so this returns the off flag defensively for that case.
    """
    hits: tuple[SearchHit, ...] = page.hits  # type: ignore[attr-defined]
    if not hits:
        return {"bulk_bar": False}
    page_ulids = [h.ulid for h in hits]
    context: dict[str, object] = {
        "auswahl": auswahl,
        "bulk_bar": True,
        "has_auswahl": bool(auswahl),
        "select_page_query": browse.select_page_query(params, auswahl, page_ulids),
        "bulk_feld_options": _BULK_FELD_OPTIONS,
        "bulk_media_type_options": vocab.media_type_options(),
        "bulk_document_type_groups": vocab.grouped_document_type_options(),
        "bulk_collection_options": _bulk_collection_options(names),
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
    names: _NamesLoader,
) -> tuple[_FacetGroup, ...]:
    """Build every sidebar facet group + the "Ohne Datum" bucket as fully-resolved view-models. The
    collection group resolves ULID facet values to Collection names (via ``names``, the shared
    per-request load) and is marked ``direct``; the "Ohne Datum" bucket is a single toggle item."""
    facets = page.facets  # type: ignore[attr-defined]
    groups: list[_FacetGroup] = [_collection_group(params, facets.get("collection", ()), names)]
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
    labels: dict[str, str] | None = None,
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
    names: _NamesLoader,
) -> _FacetGroup:
    """The Bestand facet: ULIDs resolved to Collection names. Counts are SUBTREE counts (the query
    facets over ``collection_ancestors``), so the number matches what clicking the (subtree) filter
    yields — a bare right-aligned count like every other group (the old "direkt:" hedge is gone).
    Empty ``counts`` yields an empty group (dropped by ``_facet_groups``) — and resolves no names,
    keeping the shared load lazy."""
    labels = names() if counts else {}
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


def _collection_names() -> dict[Ulid, str]:
    """A ULID→name map of every saved Collection (read-only, per request) for resolving the
    collection facet's ULID values to human names."""
    store = LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))
    collections: tuple[Collection, ...] = CollectionRepository(store).load_all()
    return {c.ulid: c.name for c in collections}


def article_detail(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /artikel/<ulid>`` — the 4.6 Lesesaal detail read view (spec §§3-4).

    ONE resolution path (``resolve_visible_detail``): load once, resolve chain, ``visible``-project,
    read the version — any deny/absence/malformed/broken-chain → the byte-identical 404 (existence-
    hiding). The template is a SINGLE file fed a projected Article, so archivist-only fields
    (Standort, Weitere Angaben) are floored to None/() before rendering and vanish through the same
    ``{% if value %}`` — there is no member-vs-archivist template fork (spec §4/§10). The action row
    + ENTWURF badge are presentation-gated on ``is_archivist``; the CAS version is surfaced only then.
    """
    resolution = resolve_visible_detail(request, ulid)
    if resolution is None:
        return _not_found()
    # The "Zurück zur Suche" target: the search the visitor came from, carried in ?zurueck= and
    # sanitized through the browse param whitelist (never echoed raw — no reflection/open-redirect,
    # spec §2). Falls back to a bare "/" when absent or nothing survives sanitizing.
    clean = browse.sanitize_query(request.GET.get("zurueck", ""))
    zurueck_href = f"{reverse('workbench')}?{clean}" if clean else reverse("workbench")
    return render(request, "workbench/detail.html", _detail_context(resolution, zurueck_href))


@dataclass(frozen=True, slots=True)
class _DetailMedia:
    """One plate in the filmstrip (or the cover): its caption, the gated thumb URL, and the full
    gated byte URL a click opens. The page never inlines bytes — both point at the /media routes,
    which re-authorize per request."""

    caption: str
    thumb_url: str
    file_url: str


@dataclass(frozen=True, slots=True)
class _DetailCrumb:
    """One Bestand breadcrumb hop: the collection name + the workbench link into its facet."""

    name: str
    href: str


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


def _detail_context(resolution: DetailResolution, zurueck_href: str) -> dict[str, object]:
    """The detail template context, built ONLY from the projected Article (no floored field can reach
    it) + the member-safe chain. Every value is `{% if %}`-gated in the template, so an absent field
    (or a floored archivist-only field) emits no row — no member/archivist fork, no "—" placeholders.
    The breadcrumb runs root→leaf (chain is leaf-first, so reversed); tags + Bestand link back into
    the workbench facets (the archive's browsing loop). Version is archivist-only CAS chrome.
    ``zurueck_href`` is the sanitized return-to-search link (built in the view from ?zurueck)."""
    article = resolution.article
    media = _detail_media(article)
    crumbs = tuple(
        _DetailCrumb(
            name=c.name,
            href=f"{reverse('workbench')}?{browse.with_param({}, browse.PARAM_COLLECTION, c.ulid)}",
        )
        for c in reversed(resolution.chain.collections)
    )
    tags = tuple(
        _DetailTag(
            label=t, href=f"{reverse('workbench')}?{browse.with_param({}, browse.PARAM_TAG, t)}"
        )
        for t in article.tags
    )
    return {
        "ulid": article.ulid,
        "is_archivist": resolution.is_archivist,
        "is_draft": article.lifecycle is Lifecycle.DRAFT,
        "version": resolution.version,
        "zurueck_href": zurueck_href,
        "title": article.title,
        "ref_code": article.ref_code or "",
        "datierung_prose": vocab.edtf_to_german(article.date),
        "datierung_mono": article.date.value if article.date is not None else "",
        "typ": article.document_type or article.media_type or "",
        "creator": article.creator or "",
        "ort": article.subject_place or "",
        # Beschreibung: split the Markdown body into paragraphs on blank lines and render each as an
        # escaped <p> (spec §3 — no Markdown dependency in this minimal slice; the template autoescapes,
        # so no markup is interpreted). Flagged to the owner as §11: rich Markdown rendering is a later
        # decision, not manufactured here.
        "body_paragraphs": _body_paragraphs(article.body),
        "crumbs": crumbs,
        "leaf_bestand": crumbs[-1] if crumbs else None,
        "tags": tags,
        "umfang": len(media),
        "cover": media[0] if media else None,
        "weitere": media[1:],
        "standort": article.physical_location or "",
        "custom": article.custom,
    }


def _serve_static(filename: str, content_type: str) -> HttpResponseBase:
    """One file from the web package's ``static/`` dir. Now used ONLY by the dev-only variant and
    layout stylesheet routes (``/_dev/static/*`` — see components_demo / layouts_demo): production
    CSS/JS is served by WhiteNoise via ``{% static %}`` (ADR 0016). Same-origin, self-contained."""
    path = _STATIC_DIR / filename
    if not path.is_file():
        return _not_found()
    return FileResponse(path.open("rb"), content_type=content_type)
