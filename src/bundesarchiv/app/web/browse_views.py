"""The archivist workbench views (Part 4.5-MVP): search/browse + the detail/neu stubs.

Thin by design. Every request resolves its viewer via ``viewer_of`` and reaches data ONLY through
``search`` (results are pre-scoped SearchHits — no ``can_view`` in the search path) or, for the
detail stub, through ``article_auth.authorize_article`` (the one place ``can_view`` runs here). No
visibility logic and no business logic live in these views or the templates (plan §11): param
parsing is the pure ``browse`` layer, scoping is the index layer, and the templates only render.

Progressive enhancement (BINDING, plan §4.5): a plain GET renders the whole page; an ``HX-Request``
GET renders only the results region (same data, same template partial), so the no-JS baseline and
the HTMX-enhanced path share one render. URL-as-state: the full state is the query string, so an
HTMX swap that pushes the URL and a shared/bookmarked link resolve to the identical page.

The workbench is a production route (mounted in ``web.urls``); the detail + neu routes are STUBS for
4.6 / 4.7 — they register the stable URL names now and ship their visibility gate with the workbench
(a result link or the "Neuer Artikel" button must never leak past its gate before the real screen).
"""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app.web import browse
from bundesarchiv.app.web.article_auth import authorize_article, resolve_visible_article
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.models import Collection, Ulid
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index import search
from bundesarchiv.index.query import FacetCount, SearchHit
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository

#: The vendored htmx file (served by the dev static route; prod serves it via nginx/whitenoise).
_STATIC_DIR = Path(__file__).parent / "static"

#: The preview-pane selection param. NOT a search param — it is stripped from every search link so
#: a denied/absent/malformed value leaves the page byte-identical to no pane (existence-hiding).
_PANE_PARAM = "artikel"


def workbench(request: HttpRequest) -> HttpResponse:
    """``GET /`` — the workbench: search field, results, facet sidebar, "Neuer Artikel" button.

    Pipeline: parse the query string (pure ``browse``), resolve the viewer, run the viewer-scoped
    ``search``, resolve collection-facet ULIDs to Collection names for display, then render. On an
    ``HX-Request`` only the results region renders (same data, same partial) — the no-JS full page
    and the HTMX swap are one code path."""
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
    context = _results_context(
        request,
        parsed,
        page,
        is_archivist=is_archivist,
        selected_ulid=pane.ulid if pane is not None else None,
    )
    context["is_archivist"] = is_archivist
    context["pane"] = pane
    # The ledger folds narrow while the pane is open (the split-narrow layout); the frame class
    # drives it (and the <1280px media query hides the pane + unfolds the ledger — css owns that).
    context["vorschau"] = pane is not None
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
        _PaneMedia(
            caption=m.caption or "", thumb_url=f"/media/{article.ulid}/{m.content_hash}/thumb"
        )
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
        datierung=article.date.value if article.date is not None else "",
        typ=article.document_type or "",
        media=media,
        oeffnen_href=f"/artikel/{article.ulid}",
        # Bearbeiten target is the detail stub for now; 4.7 repoints it at the edit form.
        bearbeiten_href=f"/artikel/{article.ulid}" if is_archivist else "",
        close_href="?" + close_query if close_query else "?",
    )


# Which index facet key feeds which sidebar group: (facet key, param key, German heading). The
# collection group resolves ULIDs → names separately (below); the rest show the value verbatim.
_FACET_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("media_type", browse.PARAM_MEDIA_TYPE, "Medienart"),
    ("document_type", browse.PARAM_DOCUMENT_TYPE, "Dokumenttyp"),
    ("tags", browse.PARAM_TAG, "Schlagworte"),
    ("decades", browse.PARAM_DECADE, "Jahrzehnte"),
)

# The ledger's column headers: (German label, css-modifier key, sortierung label or None). SIG /
# TITEL / DATIERUNG are sortable (their sortierung label mirrors browse.SORT_CHOICES minus relevanz,
# which has no column). TYP is NOT a sortable index column, so it is a plain header (None). SICHTBAR-
# KEIT + the action gutter are added by the ledger component. Presentation only — sort is browse.
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
    it has no ladder rung, so it shows nothing here."""
    match tier:
        case "PUBLIC":
            return "Öffentlich"
        case "MEMBERS":
            return "Alle Mitglieder"
        case "GROUPS":
            return "Gruppe: " + ", ".join(groups)
        case _:
            return ""


def _ledger_row(
    hit: SearchHit, *, is_archivist: bool, selected_ulid: str | None
) -> dict[str, object]:
    """One ledger row view-model from a SearchHit — a plain dict the ledger component prints (no
    logic in the template). The Sichtbarkeit string + ENTWURF flag + Bearbeiten action are archivist
    chrome: left EMPTY for non-archivists here (and the ledger component also omits those columns),
    so nothing rides in the DOM for them. ``selected_ulid`` marks the row shown in the pane."""
    return {
        "title": hit.title,
        # BASELINE href = the canonical detail route: it works without JS on every viewport (below
        # 1280px the pane is CSS-hidden, so ?artikel would be a dead click for a no-JS narrow user).
        # ledger_pane.js progressively upgrades this to the ?artikel pane on wide viewports (see the
        # data-artikel hook). No-JS behavior: the detail link everywhere.
        "href": f"/artikel/{hit.ulid}",
        "artikel_ulid": hit.ulid,
        "ref_code": hit.ref_code or "",
        "datierung": hit.date_edtf or "",
        "typ": hit.document_type or "",
        "draft": hit.is_draft if is_archivist else False,
        "visibility": _visibility_label(hit.tier, hit.groups) if is_archivist else "",
        # Bearbeiten target is the detail stub for now; 4.7 repoints it at the edit form.
        "action_label": "Bearbeiten" if is_archivist else "",
        "action_href": f"/artikel/{hit.ulid}" if is_archivist else "",
        "selected": hit.ulid == selected_ulid,
    }


def _ledger_rows(
    page: object, *, is_archivist: bool, selected_ulid: str | None
) -> tuple[dict[str, object], ...]:
    """The ledger row view-models for the page's SearchHits. The title link's BASELINE points at the
    canonical detail route ``/artikel/<ulid>`` (works with no JS, every viewport); ``ledger_pane.js``
    progressively upgrades it to the ``?artikel`` pane on wide viewports. No visibility logic — that
    already happened in ``search``; the archivist chrome is a presentation gate off ``is_archivist``."""
    hits: tuple[SearchHit, ...] = page.hits  # type: ignore[attr-defined]
    return tuple(
        _ledger_row(hit, is_archivist=is_archivist, selected_ulid=selected_ulid) for hit in hits
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


def _results_context(
    request: HttpRequest,
    parsed: browse.ParsedQuery,
    page: object,
    *,
    is_archivist: bool,
    selected_ulid: str | None,
) -> dict[str, object]:
    """The template context shared by the full page and the results partial. ``params`` is the raw
    query dict; every link the sidebar/chips/pagination/ledger need is prebuilt in Python (the
    template calls no functions with args). No visibility logic — that already happened in
    ``search``; the ledger's archivist chrome is a presentation gate off ``is_archivist``.

    ``artikel`` (the pane selection) is STRIPPED from the link-building params: it is pane state,
    not search state, so no facet/sort/chip/pager link may carry it. This is also the existence-
    hiding invariant — a denied/absent/malformed ``artikel`` must leave the page byte-identical to
    no pane, which it cannot if the raw value rode into every link. Pane selection is tracked
    separately via ``selected_ulid``."""
    params = {k: v for k, v in request.GET.dict().items() if k != _PANE_PARAM}
    total: int = page.total  # type: ignore[attr-defined]
    size = len(page.hits)  # type: ignore[attr-defined]
    return {
        "params": params,
        "text": parsed.text or "",
        "page": page,
        "facet_groups": _facet_groups(params, parsed, page),
        "ledger_rows": _ledger_rows(page, is_archivist=is_archivist, selected_ulid=selected_ulid),
        "ledger_columns": _ledger_columns(_sort_label(parsed.sort), parsed.descending, params),
        "current_page": parsed.page,
        "has_next": browse.has_next_page(
            page=parsed.page, page_size=browse.PAGE_SIZE, hits_on_page=size, total=total
        ),
        "has_prev": parsed.page > 1,
        "next_query": browse.page_query(params, parsed.page + 1),
        "prev_query": browse.page_query(params, parsed.page - 1),
        "total": total,
    }


def _facet_groups(
    params: dict[str, str], parsed: browse.ParsedQuery, page: object
) -> tuple[_FacetGroup, ...]:
    """Build every sidebar facet group + the "Ohne Datum" bucket as fully-resolved view-models. The
    collection group resolves ULID facet values to Collection names (via ``load_all``) and is marked
    ``direct``; the "Ohne Datum" bucket is a single toggle item."""
    facets = page.facets  # type: ignore[attr-defined]
    groups: list[_FacetGroup] = [_collection_group(params, facets.get("collection", ()))]
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


def _collection_group(params: dict[str, str], counts: tuple[FacetCount, ...]) -> _FacetGroup:
    """The Bestand facet: ULIDs resolved to Collection names. Counts are SUBTREE counts (the query
    facets over ``collection_ancestors``), so the number matches what clicking the (subtree) filter
    yields — a bare right-aligned count like every other group (the old "direkt:" hedge is gone).
    Empty ``counts`` yields an empty group (dropped by ``_facet_groups``)."""
    labels = _collection_names() if counts else {}
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


def article_detail_stub(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /artikel/<ulid>`` — STUB for 4.6. Applies the SAME visibility rule the real detail view
    will: load + resolve + ``can_view`` (``authorize_article``); any deny → the byte-identical 404.
    A permitted request returns a minimal German placeholder (the article's own fields are NOT
    emitted — 4.6 owns projection; the stub only proves the gate)."""
    if authorize_article(request, ulid) is None:
        return _not_found()
    return render(request, "workbench/stub_detail.html", {"ulid": ulid})


def article_new_stub(request: HttpRequest) -> HttpResponseBase:
    """``GET /artikel/neu`` — STUB for 4.7 (the "Neuer Artikel" target). Archivist-only: a
    non-Archivist gets the media route's byte-identical 404 (existence-hiding — the cataloging entry
    point must not even be discoverable). Archivist gets a German "kommt in 4.7" placeholder."""
    if not isinstance(viewer_of(request), Archivist):
        return _not_found()
    return render(request, "workbench/stub_new.html", {})


def _serve_static(filename: str, content_type: str) -> HttpResponseBase:
    """One vendored static file from the web package's ``static/`` dir, for dev/no-CDN serving.
    Prod serves these via nginx; this keeps ``runserver`` self-contained. Same-origin only — the
    stylesheet/script are self-contained by design (no external requests, dormancy rule)."""
    path = _STATIC_DIR / filename
    if not path.is_file():
        return _not_found()
    return FileResponse(path.open("rb"), content_type=content_type)


def serve_htmx(request: HttpRequest) -> HttpResponseBase:
    """``GET /static/htmx.min.js`` — the vendored htmx (the enhancement layer degrades to the
    no-JS baseline if the file is ever unavailable, so this is best-effort)."""
    return _serve_static("htmx.min.js", "application/javascript")


def serve_ledger_pane_js(request: HttpRequest) -> HttpResponseBase:
    """``GET /static/ledger_pane.js`` — the ledger-row pane enhancement: on viewports ≥1280px a
    plain click on a row title opens the ?artikel pane in place (preserving the other query params)
    instead of the detail page. Best-effort: the no-JS baseline is the canonical /artikel detail
    link, so if this file is unavailable rows still navigate correctly."""
    return _serve_static("ledger_pane.js", "application/javascript")


def serve_layouts_css(request: HttpRequest) -> HttpResponseBase:
    """``GET /static/layouts.css`` — the workbench LAYOUT stylesheet (the page frame: grid, header,
    sidebar, ledger density, pane). Consumes role tokens only (load tokens.css + components.css
    first); graduated from the dev layout demo into production. Self-contained, no external requests;
    raw-color-free by test."""
    return _serve_static("layouts.css", "text/css")


def serve_tokens(request: HttpRequest) -> HttpResponseBase:
    """``GET /static/tokens.css`` — the design-system token layers (docs/design/design-system.md):
    seed, reference ramps, roles + non-color tokens. Self-contained; gated by the contrast test."""
    return _serve_static("tokens.css", "text/css")


def serve_components_css(request: HttpRequest) -> HttpResponseBase:
    """``GET /static/components.css`` — the atom component styles (templates/components/), role
    tokens only (load tokens.css first). Pinned raw-color-free by test."""
    return _serve_static("components.css", "text/css")
