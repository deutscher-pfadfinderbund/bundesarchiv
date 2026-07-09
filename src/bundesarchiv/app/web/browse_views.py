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

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app.web import browse
from bundesarchiv.app.web.article_auth import authorize_article
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.models import Collection, Ulid
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index import search
from bundesarchiv.index.query import FacetCount
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository

#: The vendored htmx file (served by the dev static route; prod serves it via nginx/whitenoise).
_STATIC_DIR = Path(__file__).parent / "static"


def workbench(request: HttpRequest) -> HttpResponse:
    """``GET /`` — the workbench: search field, results, facet sidebar, "Neuer Artikel" button.

    Pipeline: parse the query string (pure ``browse``), resolve the viewer, run the viewer-scoped
    ``search``, resolve collection-facet ULIDs to Collection names for display, then render. On an
    ``HX-Request`` only the results region renders (same data, same partial) — the no-JS full page
    and the HTMX swap are one code path."""
    parsed = browse.parse_query(request.GET)
    viewer = viewer_of(request)
    page = search(
        viewer,
        text=parsed.text,
        filters=parsed.filters,
        sort=parsed.sort,
        page=parsed.page,
        page_size=browse.PAGE_SIZE,  # explicit: the pager arithmetic reads the same constant
    )
    context = _results_context(request, parsed, page)
    # Presentation-only chrome flag: the template hides the "Neuer Artikel" button for
    # non-Archivists so an anonymous viewer never sees an admin affordance that 404s. This is NOT
    # scoping (§11) — result visibility is decided exclusively by search()/can_view; the
    # /artikel/neu ROUTE stays independently Archivist-gated regardless of this flag.
    context["is_archivist"] = isinstance(viewer, Archivist)
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
    """A sidebar facet section: its German heading and its items. ``direct`` marks the collection
    group so the template can label its counts "direkt: N" (facet counts DIRECT membership while the
    filter is subtree — query.py's documented divergence, surfaced honestly)."""

    heading: str
    items: tuple[_FacetItem, ...]
    direct: bool = False


# Which index facet key feeds which sidebar group: (facet key, param key, German heading). The
# collection group resolves ULIDs → names separately (below); the rest show the value verbatim.
_FACET_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("media_type", browse.PARAM_MEDIA_TYPE, "Medienart"),
    ("document_type", browse.PARAM_DOCUMENT_TYPE, "Dokumenttyp"),
    ("tags", browse.PARAM_TAG, "Schlagworte"),
    ("decades", browse.PARAM_DECADE, "Jahrzehnte"),
)


def _results_context(
    request: HttpRequest, parsed: browse.ParsedQuery, page: object
) -> dict[str, object]:
    """The template context shared by the full page and the results partial. ``params`` is the raw
    query dict; every link the sidebar/chips/pagination need is prebuilt in Python (the template
    calls no functions with args). No visibility logic — that already happened in ``search``."""
    params = request.GET.dict()
    total: int = page.total  # type: ignore[attr-defined]
    size = len(page.hits)  # type: ignore[attr-defined]
    return {
        "params": params,
        "text": parsed.text or "",
        "page": page,
        "sort_value": _sort_label(parsed.sort),
        "sort_choices": browse.SORT_CHOICES,
        "chips": browse.active_chips(params),
        "facet_groups": _facet_groups(params, parsed, page),
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
    groups.append(_dateless_group(params, parsed, page))
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
    """The Bestand facet: ULIDs resolved to Collection names, counts labeled "direkt" by the
    template. Empty ``counts`` yields an empty group (dropped by ``_facet_groups``)."""
    labels = _collection_names() if counts else {}
    return _FacetGroup(
        "Bestand",
        _facet_items(params, browse.PARAM_COLLECTION, counts, labels=labels),
        direct=True,
    )


def _dateless_group(
    params: dict[str, str], parsed: browse.ParsedQuery, page: object
) -> _FacetGroup:
    """The "Ohne Datum" bucket (data honesty, ideas §1.3): a single toggle item counting in-scope
    rows with no date. Shown only when there ARE dateless rows OR the filter is already on (so it can
    be turned off). Active → query removes it; inactive → query adds ``ohne_datum=1``."""
    count: int = page.dateless_count  # type: ignore[attr-defined]
    active = parsed.filters.dateless
    if count == 0 and not active:
        return _FacetGroup("Datum", ())
    query = (
        browse.without_param(params, browse.PARAM_DATELESS)
        if active
        else browse.with_param(params, browse.PARAM_DATELESS, "1")
    )
    item = _FacetItem(label="Ohne Datum", count=count, active=active, query=query)
    return _FacetGroup("Datum", (item,))


def _sort_label(sort: str) -> str:
    """The German label for the active sort (so the ``<select>`` marks the right option)."""
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


def serve_stylesheet(request: HttpRequest) -> HttpResponseBase:
    """``GET /static/workbench.css`` — the self-contained workbench stylesheet (design tokens as
    CSS custom properties; no webfonts, no external requests)."""
    return _serve_static("workbench.css", "text/css")


def serve_tokens(request: HttpRequest) -> HttpResponseBase:
    """``GET /static/tokens.css`` — the design-system token layers (docs/design/design-system.md):
    seed, reference ramps, roles + non-color tokens. Self-contained; gated by the contrast test."""
    return _serve_static("tokens.css", "text/css")
