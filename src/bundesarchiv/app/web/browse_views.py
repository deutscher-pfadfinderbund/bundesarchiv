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
from dataclasses import dataclass, replace
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import render
from django.urls import reverse

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import browse, bulk, ledger, vocab
from bundesarchiv.app.web.article_auth import (
    DetailResolution,
    resolve_visible_article,
    resolve_visible_detail,
)
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.media_views import media_url, not_found, thumbnail_url
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.access import preview
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.models import Article, Lifecycle
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index.query import FacetCount, SearchFilters, SearchPage, search

#: The preview-pane selection param. NOT a search param — it is stripped from every search link so
#: a denied/absent/malformed value leaves the page byte-identical to no pane (existence-hiding).
_PANE_PARAM = "artikel"


def workbench(request: HttpRequest) -> HttpResponse:
    """``GET /`` — the workbench: the search sentence, the results.

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
        facets=("collection", "decades", "document_type"),  # the sentence's three slots
    )
    # The preview pane: ?artikel=<ulid> resolved fail-closed through the ONE render path. None when
    # absent/malformed/denied — the workbench then renders byte-identically (no existence oracle).
    pane = _resolve_pane(request, is_archivist=is_archivist)
    # Bulk-edit selection (archivist-only chrome, spec §2): any ?auswahl= is selection mode
    # ("Auswählen"; a bare ``auswahl=`` is the mode with nothing ticked), and its values carry the
    # selected ulids across pages. Non-archivists never get the mode, so their auswahl is dropped
    # entirely (defence-in-depth — the POST route is independently gated too).
    waehlen = is_archivist and browse.PARAM_AUSWAHL in request.GET
    auswahl = [u for u in request.GET.getlist(browse.PARAM_AUSWAHL) if u] if waehlen else []
    bestand = BestandChooser.of(Archive.canonical())
    context = _results_context(
        request,
        parsed,
        page,
        is_archivist=is_archivist,
        selected_ulid=pane.ulid if pane is not None else None,
        waehlen=waehlen,
        auswahl=auswahl,
        bestand=bestand,
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
        return render_screen(request, "workbench/workbench.html", context, bestand=bestand)
    if request.headers.get("HX-Request"):
        # The search sentence sits outside the #results swap target, so the partial prepends its
        # out-of-band fragments (oob gates them: the full page renders the sentence once).
        context["oob"] = True
        return render(request, "workbench/_results.html", context)
    return render_screen(request, "workbench/workbench.html", context, bestand=bestand)


def choose_columns(request: HttpRequest) -> HttpResponseBase:
    """``POST /spalten`` — the "Spalten …" choice, kept in a cookie for whoever made it (ruling
    2026-09-29), then back to the SAME list (PRG), which works without JS. The way back is always the
    workbench path with the posted query after it, so no posted value can point it off the site;
    the cookie holds registry keys only (``ledger.cookie_value``). Any other method is the plain
    404."""
    if request.method != "POST":
        return not_found()
    # the fixed path is the guard: whatever was posted can only ever be this list's query
    back = request.POST.get("zurueck", "")
    response = HttpResponseRedirect(
        f"{reverse('workbench')}?{back}" if back else reverse("workbench")
    )
    response.set_cookie(
        ledger.COOKIE,
        ledger.cookie_value(request.POST.getlist("spalte")),
        max_age=ledger.COOKIE_MAX_AGE,
        httponly=True,
        # https-only wherever the CSRF cookie is: dev's plain http cannot carry a Secure cookie
        secure=settings.CSRF_COOKIE_SECURE,
        samesite="Lax",
    )
    return response


@dataclass(frozen=True, slots=True)
class _FacetItem:
    """One entry of a slot's menu or of "+ Filter": its words, its count (empty where none is
    shown), whether it is set, and the query clicking it produces (add, or remove when set). The
    template only prints."""

    label: str
    count: str
    active: bool
    query: str


@dataclass(frozen=True, slots=True)
class _Slot:
    """One slot of the search sentence (a2): its words, and its menu -- the entry that clears it
    (``unset_label`` and ``clear_query``, which is ``None`` while unset), then the values the index
    counts."""

    label: str
    unset_label: str
    clear_query: str | None
    items: tuple[_FacetItem, ...]
    open: bool = False


@dataclass(frozen=True, slots=True)
class _SetFilter:
    """A set filter no slot shows: its words, and the query without it (its link removes it)."""

    label: str
    query: str


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


#: The active-filter query params the search form echoes as hidden inputs (GH #21), in a fixed
#: render order: the ONE filter-dimension list (``browse.FILTER_PARAMS``, which the sentence's
#: clear-all clears) plus the sort. Every ``browse`` search-state key EXCEPT ``q`` (the form's own
#: live input, never duplicated as hidden) and ``seite`` (a new search deliberately resets to
#: page 1 — kept as-is).
_FORM_FILTER_PARAMS: tuple[str, ...] = (*browse.FILTER_PARAMS, browse.PARAM_SORT)


def _form_filters(params: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """The active filter params as ``(key, value)`` pairs for the search form's hidden inputs — read
    from the SAME ``params`` mapping the facet/sort/pagination links below build from, so the form
    and the sentence can never drift out of sync (GH #21: typing refines WITHIN the active filter
    scope). A blank or absent param is omitted entirely — never an empty-value hidden input."""
    return tuple((key, params[key]) for key in _FORM_FILTER_PARAMS if params.get(key))


def _results_context(
    request: HttpRequest,
    parsed: browse.ParsedQuery,
    page: SearchPage,
    *,
    is_archivist: bool,
    selected_ulid: str | None,
    waehlen: bool,
    auswahl: list[str],
    bestand: BestandChooser,
) -> dict[str, object]:
    """The template context shared by the full page and the results partial. Every link the
    sentence/pagination/ledger need is prebuilt in Python from the local ``params`` dict (the
    template calls no functions with args), so the raw query dict itself is never handed to the
    template. No visibility logic — that already happened in ``search``; the ledger's archivist
    chrome is a presentation gate off ``is_archivist``.

    ``artikel`` (pane) and ``auswahl`` (bulk selection) are STRIPPED from the link-building
    ``params``: neither is search state, so no facet/sort link may carry them. In selection mode
    (``waehlen``) the PAGINATION links re-attach a bare ``auswahl=`` plus every selected ulid, so
    paging keeps both the mode and the selection. Pane selection is tracked separately via
    ``selected_ulid``."""
    params = {
        k: v for k, v in request.GET.dict().items() if k not in (_PANE_PARAM, browse.PARAM_AUSWAHL)
    }
    total = page.total
    context: dict[str, object] = {
        "text": parsed.text or "",
        # The search form's hidden inputs (GH #21) — every active filter, so typing a new q keeps
        # refining WITHIN the current filter scope instead of silently dropping it.
        "filter_params": _form_filters(params),
        "page": page,
        "ledger": ledger.build(
            page.hits,
            columns=ledger.chosen(request.COOKIES.get(ledger.COOKIE)),
            parsed=parsed,
            params=params,
            auswahl=auswahl,
            is_archivist=is_archivist,
            selected_ulid=selected_ulid,
            bestand=bestand,
        ),
        "pager": _pager(parsed, page, params, ["", *auswahl] if waehlen else []) if total else None,
        # "Spalten …" returns to this very list, pane and selection included
        "spalten_zurueck": request.GET.urlencode(),
        "total": vocab.count(total),
        # When a zero-hit result is filtered ONLY by a Bestand (no text, no other facet), the empty
        # state is Bestand-specific ("Noch keine Artikel in diesem Bestand." + an archivist create
        # link pre-seeded with it) instead of the generic "remove filters" copy (4.8 item 3).
        "leerer_bestand": _only_bestand_filter(parsed) if total == 0 else None,
    }
    context.update(_sentence(params, parsed, page, bestand, is_archivist=is_archivist))
    if is_archivist:
        context.update(_bulk_bar_context(params, page, waehlen, auswahl, bestand))
    return context


@dataclass(frozen=True, slots=True)
class _Pager:
    """The pager (a2 rounds 9 and 10): the range between the two steps on a list of several pages,
    where a step that cannot move yet is disabled (``None``); a one-page list shows only its count
    and its ``noun``. ``shown`` is the range on this page from ``first``, empty past the last
    page."""

    stepped: bool
    prev_query: str | None
    next_query: str | None
    first: int
    shown: str
    total: int
    total_label: str
    noun: str


def _pager(
    parsed: browse.ParsedQuery, page: SearchPage, params: Mapping[str, str], auswahl: list[str]
) -> _Pager:
    """The pager's steps carry the selection (``auswahl``), so paging never drops it."""
    n, hits = parsed.page, len(page.hits)
    first = (n - 1) * browse.PAGE_SIZE + 1
    has_prev = n > 1
    has_next = browse.has_next_page(
        page=n, page_size=browse.PAGE_SIZE, hits_on_page=hits, total=page.total
    )
    shown = f"{vocab.count(first)}\N{EN DASH}{vocab.count(first + hits - 1)}" if hits else ""
    noun = "Artikel"
    if parsed.filters.drafts_only:
        noun = "Entwurf" if page.total == 1 else "Entwürfe"
    return _Pager(
        stepped=has_prev or has_next,
        prev_query=browse.page_query_with_auswahl(params, auswahl, n - 1) if has_prev else None,
        next_query=browse.page_query_with_auswahl(params, auswahl, n + 1) if has_next else None,
        first=first,
        shown=shown,
        total=page.total,
        total_label=vocab.count(page.total),
        noun=noun,
    )


def _only_bestand_filter(parsed: browse.ParsedQuery) -> str | None:
    """The Bestand ulid when the search's ONLY constraint is that collection (no text, no other
    facet) — else ``None``. Used to pick the Bestand-specific empty state over the generic one."""
    f = parsed.filters
    others_empty = not parsed.text and replace(f, collection=None) == SearchFilters()
    return f.collection if f.collection is not None and others_empty else None


def _bulk_bar_context(
    params: dict[str, str],
    page: SearchPage,
    waehlen: bool,
    auswahl: list[str],
    bestand: BestandChooser,
) -> dict[str, object]:
    """The tool row's selection tools (spec §2 B/C, a2 rounds 2 and 11, owner 2026-09-30),
    archivist-only: "Auswählen" outside selection mode; in it "Abbrechen", the count and the Feld
    chooser. Both links keep the search (params already exclude auswahl and artikel): a bare "?"
    would wipe the filters.

    The client adds its live checkbox count to ``auswahl_offpage_count``, the part of the URL-borne
    selection NOT on this page, which it cannot otherwise see (learning G.25).
    """
    hits = page.hits
    if not hits:
        return {}
    search = [(k, v) for k, v in params.items() if v]
    if not waehlen:
        return {
            "waehlen": False,
            "auswaehlen_query": urlencode([*search, (browse.PARAM_AUSWAHL, "")]),
        }
    on_page = {h.ulid for h in hits}
    return {
        "waehlen": True,
        "auswahl_count": len(auswahl),
        "auswahl_offpage_count": sum(1 for u in auswahl if u not in on_page),
        "abbrechen_query": urlencode(search),
        **bulk.feldwahl_context(bestand),
    }


def _sentence(
    params: dict[str, str],
    parsed: browse.ParsedQuery,
    page: SearchPage,
    bestand: BestandChooser,
    *,
    is_archivist: bool,
) -> dict[str, object]:
    """The search sentence's parts: its three slots (Bestand, Jahrzehnt, Typ), every set filter no
    slot shows, the "+ Filter" checks (Entwürfe for archivists only), and the query that clears
    every filter once two or more are set (else ``None``)."""
    f = parsed.filters
    facets = page.facets
    names = bestand.names()
    decade_menu = _facet_items(
        params, browse.PARAM_DECADE, facets.get("decades", ()), label=lambda d: f"{d}er"
    )
    if page.dateless_count or f.dateless:
        decade_menu += (
            _toggle(params, browse.PARAM_DATELESS, "ohne Datum", f.dateless, page.dateless_count),
        )
    slots = (
        _slot(
            params,
            browse.PARAM_COLLECTION,
            f.collection and names.get(f.collection, f.collection),
            "allen Beständen",
            _facet_items(
                params,
                browse.PARAM_COLLECTION,
                facets.get("collection", ()),
                label=lambda u: names.get(u, u),
            ),
        ),
        _slot(
            params,
            browse.PARAM_DECADE,
            None if f.decade is None else f"{f.decade}er",
            "alle Jahrzehnte",
            decade_menu,
        ),
        _slot(
            params,
            browse.PARAM_DOCUMENT_TYPE,
            f.document_type,
            "jeder Typ",
            _facet_items(params, browse.PARAM_DOCUMENT_TYPE, facets.get("document_type", ())),
        ),
    )
    unslotted = (
        (browse.PARAM_MEDIA_TYPE, f.media_type and f"Medienart: {f.media_type}"),
        (browse.PARAM_TAG, f.tag and f"Schlagwort: {f.tag}"),
        (browse.PARAM_DATE_FROM, f"ab {f.date_from.isoformat()}" if f.date_from else None),
        (browse.PARAM_DATE_TO, f"bis {f.date_to.isoformat()}" if f.date_to else None),
        (browse.PARAM_DATELESS, "ohne Datum" if f.dateless else None),
        (browse.PARAM_DIGITAL, "digital" if f.has_files else None),
        (browse.PARAM_DRAFTS, "Entwürfe" if f.drafts_only else None),
    )
    checks = [_toggle(params, browse.PARAM_DIGITAL, "Digital (mit Dateien)", f.has_files)]
    if is_archivist:
        checks.append(_toggle(params, browse.PARAM_DRAFTS, "Entwürfe", f.drafts_only))
    set_filters = tuple(
        _SetFilter(label, browse.without_param(params, param))
        for param, label in unslotted
        if label
    )
    set_count = len(set_filters) + sum(slot.clear_query is not None for slot in slots)
    return {
        "slots": slots,
        "set_filters": set_filters,
        "filter_checks": tuple(checks),
        # two or more set filters clear together (owner 2026-09-30); q and the sort stay
        "clear_all_query": browse.clear_filters_query(params) if set_count >= 2 else None,
    }


def _slot(
    params: dict[str, str],
    param: str,
    value_label: str | None,
    unset_label: str,
    items: tuple[_FacetItem, ...],
) -> _Slot:
    """A slot reads its set value's words, else ``unset_label``; its menu clears it when set."""
    return _Slot(
        label=value_label or unset_label,
        unset_label=unset_label,
        clear_query=browse.without_param(params, param) if value_label is not None else None,
        items=items,
    )


def _toggle(
    params: dict[str, str], param: str, label: str, active: bool, count: int | None = None
) -> _FacetItem:
    """A boolean filter's entry: set, it removes the filter; unset, it adds ``param=1``."""
    query = browse.without_param(params, param) if active else browse.with_param(params, param, "1")
    return _FacetItem(label, "" if count is None else vocab.count(count), active, query)


def _facet_items(
    params: dict[str, str],
    param: str,
    counts: tuple[FacetCount, ...],
    *,
    label: Callable[[str], str] = str,
) -> tuple[_FacetItem, ...]:
    """A facet's values as menu entries, named by ``label``. The value that is set removes its
    filter when clicked; every other one sets it."""
    active_value = params.get(param, "")
    return tuple(
        _FacetItem(
            label=label(fc.value),
            count=vocab.count(fc.count),
            active=fc.value == active_value,
            query=browse.without_param(params, param)
            if fc.value == active_value
            else browse.with_param(params, param, fc.value),
        )
        for fc in counts
    )


def article_detail(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /artikel/<ulid>`` — the 4.6 Lesesaal detail read view (spec §§3-4).

    ONE resolution path (``resolve_visible_detail``): load once, resolve chain, ``visible``-project —
    any deny/absence/malformed/broken-chain → the plain 404 (existence-hiding). The template
    is a SINGLE file fed a projected Article, so archivist-only fields (Standort, Weitere Angaben) are
    floored to None/() before rendering and vanish through the same ``{% if value %}`` — there is no
    member-vs-archivist template fork (spec §4/§10). The archivist's tools are presentation-gated
    on ``is_archivist``."""
    resolution = resolve_visible_detail(request, ulid)
    if resolution is None:
        return not_found()
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
        "loeschen": vocab.delete_confirm(len(media)),
        "cover": media[0] if media else None,
        "weitere": media[1:],
        "standort": article.physical_location or "",
        "custom": article.custom,
    }
