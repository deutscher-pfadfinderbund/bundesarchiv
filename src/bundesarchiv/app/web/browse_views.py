"""No visibility logic lives here (plan §11): data comes from the viewer-scoped ``search``,
``resolve_visible_detail``, or, for the archivist-only Papierkorb, the canonical load.
"""

import datetime
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from bundesarchiv.app import legacy, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import Size
from bundesarchiv.app.web import browse, bulk, landing, ledger, reading, vocab
from bundesarchiv.app.web.article_auth import DetailResolution, resolve_visible_detail
from bundesarchiv.app.web.byline import BylineLink
from bundesarchiv.app.web.catalog import none_if_blank
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.media_urls import display_url, media_url, thumbnail_url
from bundesarchiv.app.web.media_views import not_found
from bundesarchiv.app.web.viewers import is_partial, render_screen, viewer_of
from bundesarchiv.domain.access import preview
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.models import ULID, Change, Lifecycle, MediaRef, Version
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index.indexer import file_kind, mime_type
from bundesarchiv.index.query import (
    Facet,
    FacetCount,
    FileKind,
    SearchFilters,
    SearchPage,
)
from bundesarchiv.persistence.errors import ArchiveError

#: The preview-pane selection param, not a search param. A denied, absent or malformed value shows
#: no pane and reveals nothing (the deny contract).
_PANE_PARAM = "article"


def workbench(request: HttpRequest) -> HttpResponse:
    """``GET /articles`` — the workbench."""
    state = browse.SearchState.parse(request.GET)
    viewer = viewer_of(request)
    # chrome only, not scoping (§11): search() decides visibility, archivist routes gate themselves
    is_archivist = isinstance(viewer, Archivist)
    page = state.search(viewer, facets=_sentence_facets(state.filters))
    archive = Archive.canonical()
    chooser = CollectionChooser.of(archive)
    pane = _resolve_pane(request, archive, chooser, is_archivist=is_archivist)
    # a bare ?selection= is selection mode with nothing ticked (spec §2)
    selecting = is_archivist and not state.reading and browse.PARAM_SELECTION in request.GET
    selection = [u for u in request.GET.getlist(browse.PARAM_SELECTION) if u] if selecting else []
    context = _results_context(
        request,
        state,
        page,
        is_archivist=is_archivist,
        selected_ulid=pane.ulid if pane is not None else None,
        selecting=selecting,
        selection=selection,
        chooser=chooser,
    )
    context["is_archivist"] = is_archivist
    context["pane"] = pane
    context["active_collection"] = state.filters.collection if is_archivist else None
    # body.preview adds the pane column (the pane switch, layouts.css); the ledger re-densifies by
    # itself, it is a size container (law C11).
    context["preview"] = pane is not None
    # A Back-button restore swaps the whole body, so only a partial gets the chrome-less region.
    if is_partial(request):
        # The search sentence sits outside the #results swap target, so the partial prepends its
        # out-of-band fragments (oob gates them: the full page renders the sentence once).
        context["oob"] = True
        return render_screen(request, "workbench/_results.html", context, chooser=chooser)
    return render_screen(request, "workbench/workbench.html", context, chooser=chooser)


def choose_columns(request: HttpRequest) -> HttpResponseBase:
    """``POST /columns`` — the "Spalten …" choice, kept in a cookie (ruling 2026-09-29)."""
    if request.method != "POST":
        return not_found()
    # the fixed path is the guard: whatever was posted can only ever be this list's query
    back = request.POST.get("back", "")
    response = HttpResponseRedirect(
        f"{reverse('workbench')}?{back}" if back else reverse("workbench")
    )
    response.set_cookie(
        ledger.COOKIE,
        ledger.cookie_value(request.POST.getlist("column")),
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
    """One slot of the search sentence (a2): its words, and its menu -- the entries that clear it
    (none while unset; a nested slot's first clears the slot it sits under), then the values the
    index counts."""

    label: str
    unset_label: str
    clears: tuple[_FacetItem, ...]
    items: tuple[_FacetItem, ...]


@dataclass(frozen=True, slots=True)
class _SetFilter:
    """A set filter no slot shows: its words, and the query without it (its link removes it)."""

    label: str
    query: str


#: The image types every browser draws: the article page leads with such an original, sharp at
#: any width, where the 480px thumbnail would be stretched. A TIFF is not among them.
_DRAWN = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})

#: The icon a file without a thumbnail shows in its tile.
_GLYPHS = {FileKind.VIDEO: "video-file", FileKind.AUDIO: "audio-file"}


@dataclass(frozen=True, slots=True)
class MediaTile:
    """Every URL is gated and re-authorizes per request (a page never inlines bytes); an empty URL
    means that version is not offered."""

    kind: str
    glyph: str  # a components/icon.html name
    name: str
    caption: str
    file_url: str
    full_url: str
    thumb_url: str
    display_url: str = ""
    aspect: tuple[int, int] | None = None
    size: str = ""  # the original's size in words ("1,8 MB"), empty when unknown
    slot: int = -1  # an image's place in the article page's lightbox (-1: not in it)
    alt: str = ""  # an image's accessible name: its description, else caption, else file name

    @property
    def is_image(self) -> bool:
        """The file gets a display version and enters the lightbox."""
        return bool(self.display_url)

    @property
    def breakable_name(self) -> SafeString:
        """The escaped file name with a ``<wbr>`` after each ".", "_" and "-": a tile too narrow
        for it wraps it there, not mid-word."""
        return mark_safe(re.sub(r"([._-])", r"\1<wbr>", escape(self.name)))  # noqa: S308


def media_tiles(ulid: ULID, media: tuple[MediaRef, ...]) -> tuple[MediaTile, ...]:
    """``media`` as tiles, in its order (cover first, ADR 0015). One tile header read per file: the
    thumbnail cache is local (ADR 0017)."""
    root = Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
    return tuple(_tile(ulid, ref, thumbnails.tile_size(root, ref.content_hash)) for ref in media)


def _tile(ulid: ULID, ref: MediaRef, aspect: tuple[int, int] | None) -> MediaTile:
    image = thumbnails.renders(ref, Size.DISPLAY)
    caption = none_if_blank(ref.caption or "") or ""
    kind = file_kind(ref)
    return MediaTile(
        kind=vocab.file_word(kind),
        glyph=_GLYPHS.get(kind, "file-present"),
        name=ref.filename,
        size=vocab.human_size(ref.byte_size),
        caption=caption,
        alt=(image and none_if_blank(ref.alt or "")) or caption or ref.filename,
        file_url=media_url(ulid, ref.content_hash),
        full_url=media_url(ulid, ref.content_hash) if mime_type(ref) in _DRAWN else "",
        display_url=(display_url(ulid, ref.content_hash) if image else ""),
        thumb_url=thumbnail_url(ulid, ref.content_hash) if aspect else "",
        aspect=aspect,
    )


@dataclass(frozen=True, slots=True)
class _Pane:
    """Built only from a ``visible``-projected Article."""

    ulid: ULID
    title: str
    ref_code: str
    date: str
    doc_type: str
    media: tuple[MediaTile, ...]
    open_href: str
    edit_href: str
    close_href: str


def _resolve_pane(
    request: HttpRequest, archive: Archive, chooser: CollectionChooser, *, is_archivist: bool
) -> _Pane | None:
    """The ``?article`` pane, or ``None`` when absent, malformed, denied or in the Papierkorb — all
    alike, so the workbench shows no pane (no existence oracle)."""
    ulid = request.GET.get(_PANE_PARAM)
    if not ulid:
        return None
    resolution = resolve_visible_detail(request, ulid, archive, chooser)
    article = resolution.article if resolution is not None else None
    if article is None or article.deleted is not None:
        return None
    # closing keeps the search: only the pane param goes (a bare "?" would drop it)
    close_params = {k: v for k, v in request.GET.dict().items() if k != _PANE_PARAM}
    close_query = urlencode(close_params)
    return _Pane(
        ulid=article.ulid,
        title=article.title,
        ref_code=article.ref_code or "",
        date=vocab.date_mono(article.date),
        doc_type=article.document_type or "",
        media=media_tiles(article.ulid, article.media),
        open_href=reverse("article-detail", args=[article.ulid]),
        edit_href=reverse("article-edit", args=[article.ulid]) if is_archivist else "",
        close_href="?" + close_query if close_query else "?",
    )


def _form_filters(state: browse.SearchState) -> tuple[tuple[str, str], ...]:
    """The set filters, sort, view and page size as hidden inputs, so typing a new ``q`` refines
    within them; ``q`` is the form's own input, and a new search starts on page 1."""
    return tuple(replace(state, text=None, page=1).params().items())


def _results_context(
    request: HttpRequest,
    state: browse.SearchState,
    page: SearchPage,
    *,
    is_archivist: bool,
    selected_ulid: str | None,
    selecting: bool,
    selection: list[str],
    chooser: CollectionChooser,
) -> dict[str, object]:
    here = request.GET.copy()
    for key in landing.FLAG_KEYS:
        here.pop(key, None)
    total = page.total
    context: dict[str, object] = {
        "text": state.text or "",
        "filter_params": _form_filters(state),
        "page": page,
        "reading": state.reading,
        "reading_rows": reading.rows(
            page.hits, state=state, is_archivist=is_archivist, chooser=chooser
        )
        if state.reading
        else (),
        "ledger": None
        if state.reading
        else ledger.build(
            page.hits,
            columns=ledger.chosen(request.COOKIES.get(ledger.COOKIE)),
            state=state,
            selection=selection,
            is_archivist=is_archivist,
            selected_ulid=selected_ulid,
            chooser=chooser,
        ),
        # the view switch, with a query only: without one the list is the table
        "views": _views(state) if state.text else (),
        "pager": _pager(state, page, ["", *selection] if selecting else [], sizes=True)
        if total
        else None,
        # "Spalten …" returns to this very list, pane and selection included
        "columns_back": here.urlencode(),
        "total": vocab.count(total),
        "empty_collection": _only_collection_filter(state) if total == 0 else None,
    }
    context.update(sentence(state, page, chooser, is_archivist=is_archivist))
    if is_archivist and not state.reading:
        context.update(_bulk_bar_context(state, page, selecting, selection, chooser))
    return context


@dataclass(frozen=True, slots=True)
class _View:
    """One entry of the view switch: its word, the query showing the same search in it, and
    whether it is the view on screen."""

    label: str
    query: str
    current: bool


def _views(state: browse.SearchState) -> tuple[_View, ...]:
    return (
        _View("Lesesaal", replace(state, table=False).query(), state.reading),
        _View("Tabelle", replace(state, table=True).query(), not state.reading),
    )


@dataclass(frozen=True, slots=True)
class _PageSize:
    """``query`` is ``None`` for the size on screen."""

    label: str
    query: str | None


@dataclass(frozen=True, slots=True)
class _Pager:
    """A step that cannot move is ``None``; ``shown`` is empty past the last page."""

    stepped: bool
    prev_query: str | None
    next_query: str | None
    first: int
    shown: str
    total: int
    total_label: str
    sizes: tuple[_PageSize, ...] = ()


def _pager(
    state: browse.SearchState, page: SearchPage, selection: list[str], *, sizes: bool = False
) -> _Pager:
    """The pager's links carry the selection (``selection``), so paging never drops it; ``sizes``
    brings the page-size chooser."""
    choices = (
        tuple(
            _PageSize(
                str(size),
                None
                if size == state.page_size
                else replace(state, page_size=size, page=1).query(selection),
            )
            for size in browse.PAGE_SIZES
        )
        if sizes
        else ()
    )
    n, hits, page_size = state.page, len(page.hits), state.page_size
    first = (n - 1) * page_size + 1
    has_prev = n > 1
    has_next = browse.has_next_page(
        page=n, page_size=page_size, hits_on_page=hits, total=page.total
    )
    shown = f"{vocab.count(first)}\N{EN DASH}{vocab.count(first + hits - 1)}" if hits else ""
    return _Pager(
        stepped=has_prev or has_next,
        prev_query=replace(state, page=n - 1).query(selection) if has_prev else None,
        next_query=replace(state, page=n + 1).query(selection) if has_next else None,
        first=first,
        shown=shown,
        total=page.total,
        total_label=vocab.count(page.total),
        sizes=choices,
    )


def _only_collection_filter(state: browse.SearchState) -> str | None:
    f = state.filters
    others_empty = not state.text and replace(f, collection=None) == SearchFilters()
    return f.collection if f.collection is not None and others_empty else None


def _bulk_bar_context(
    state: browse.SearchState,
    page: SearchPage,
    selecting: bool,
    selection: list[str],
    chooser: CollectionChooser,
) -> dict[str, object]:
    """Both links keep the search (a bare "?" would wipe the filters);
    ``selection_offpage_count`` feeds the client's live count (catalog_bulk.js)."""
    hits = page.hits
    if not hits:
        return {}
    if not selecting:
        return {"selecting": False, "select_query": state.query([""])}
    on_page = {h.ulid for h in hits}
    return {
        "selecting": True,
        "selection_count": len(selection),
        "selection_offpage_count": sum(1 for u in selection if u not in on_page),
        "cancel_query": state.query(),
        **bulk.field_picker_context(chooser),
    }


def sentence(
    state: browse.SearchState,
    page: SearchPage,
    chooser: CollectionChooser,
    *,
    is_archivist: bool,
) -> dict[str, object]:
    """The search sentence's parts: its slots (Collection, Jahrzehnt, Medienart, and under
    Schrifttum the Dokumenttyp), every set filter no slot shows, the "+ Filter" checks (Entwürfe
    for archivists only), and the query that clears every filter once two or more are set (else
    ``None``)."""
    f = state.filters
    facets = page.facets
    names = chooser.names()
    decade_menu = _facet_items(
        state,
        browse.PARAM_DECADE,
        # in time order, as the start page's Zeitleiste reads (the index counts most first)
        tuple(sorted(facets.get("decades", ()), key=lambda fc: int(fc.value))),
        label=lambda d: f"{d}er",
    )
    if page.dateless_count or f.dateless:
        decade_menu += (
            _toggle(state, browse.PARAM_DATELESS, vocab.UNDATED, f.dateless, page.dateless_count),
        )
    undated_slot = f.dateless and f.decade is None  # set beside a decade, it stays a set filter
    any_medienart = "jede Medienart"
    typed = _typed(f)
    slots = (
        _slot(
            state,
            browse.PARAM_COLLECTION,
            f.collection and names.get(f.collection, f.collection),
            "allen Sammlungsteilen",
            _facet_items(
                state,
                browse.PARAM_COLLECTION,
                facets.get("collection", ()),
                label=lambda u: names.get(u, u),
            ),
        ),
        # the undated are the decade slot's own value, as the start page's Zeitleiste names them
        _slot(
            state,
            browse.PARAM_DATELESS if undated_slot else browse.PARAM_DECADE,
            vocab.UNDATED if undated_slot else (None if f.decade is None else f"{f.decade}er"),
            "alle Jahrzehnte",
            decade_menu,
        ),
        _slot(
            state,
            browse.PARAM_MEDIA_TYPE,
            f.media_type,
            any_medienart,
            _facet_items(state, browse.PARAM_MEDIA_TYPE, facets.get("media_type", ())),
        ),
        *(
            (
                _slot(
                    state,
                    browse.PARAM_DOCUMENT_TYPE,
                    f.document_type,
                    "jeder Dokumenttyp",
                    _facet_items(
                        state, browse.PARAM_DOCUMENT_TYPE, facets.get("document_type", ())
                    ),
                    under=((browse.PARAM_MEDIA_TYPE, any_medienart),),
                ),
            )
            if typed
            else ()
        ),
    )
    unslotted = (
        # without Schrifttum (an old link) it has no slot, but must stay removable
        (
            browse.PARAM_DOCUMENT_TYPE,
            None if typed else f.document_type and f"Dokumenttyp: {f.document_type}",
        ),
        (browse.PARAM_TAG, f.tag and f"Schlagwort: {f.tag}"),
        (browse.PARAM_CREATOR, f.creator and f"Urheber: {f.creator}"),
        (browse.PARAM_PLACE, f.place and f"Ort: {f.place}"),
        (browse.PARAM_DATE_FROM, f"ab {_bound(f.date_from, (1, 1))}" if f.date_from else None),
        (browse.PARAM_DATE_TO, f"bis {_bound(f.date_to, (12, 31))}" if f.date_to else None),
        # set beside a decade (a hand-made URL) it has no slot left, but must stay removable
        (browse.PARAM_DATELESS, vocab.UNDATED if f.dateless and not undated_slot else None),
        (browse.PARAM_DIGITAL, "mit Dateien" if f.has_files else None),
        (browse.PARAM_FILE, f.file_kind and vocab.FILE_FILTER_LABELS[f.file_kind]),
        (browse.PARAM_DRAFTS, "Entwürfe" if f.drafts_only else None),
        (browse.PARAM_TEMPLATES, "Vorlagen" if f.templates_only else None),
    )
    checks = [_toggle(state, browse.PARAM_DIGITAL, "mit Dateien", f.has_files)]
    checks += _facet_items(
        state,
        browse.PARAM_FILE,
        facets.get("file_kind", ()),
        label=lambda kind: vocab.FILE_FILTER_LABELS[FileKind(kind)],
    )
    if is_archivist:
        checks.append(_toggle(state, browse.PARAM_DRAFTS, "Entwürfe", f.drafts_only))
        checks.append(_toggle(state, browse.PARAM_TEMPLATES, "Vorlagen", f.templates_only))
    set_filters = tuple(
        _SetFilter(label, state.without(param).query()) for param, label in unslotted if label
    )
    set_count = len(set_filters) + sum(bool(slot.clears) for slot in slots)
    order = _order(state)
    return {
        "slots": slots,
        "set_filters": (*set_filters, order) if order else set_filters,
        "filter_checks": tuple(checks),
        # two or more set filters clear together (owner 2026-09-30); q and the sort stay
        "clear_all_query": state.without_filters().query() if set_count >= 2 else None,
        "any_filter_set": set_count > 0,
    }


def _order(state: browse.SearchState) -> _SetFilter | None:
    """The sort as a set filter where no column head shows it, its link back to relevance: the
    start page's "Alle ansehen" order, and in the Lesesaal any sort (owner, 2026-10-18). It is no filter: "alle entfernen" keeps it."""
    if state.sort == "added":
        label = "neueste zuerst"
    elif state.reading and state.sort != "relevance":
        label = f"sortiert nach {ledger.SORT_LABELS[state.sort]}"
        label += ", absteigend" if state.descending else ""
    else:
        return None
    return _SetFilter(label, state.without(browse.PARAM_SORT).query())


def _bound(day: datetime.date, year_edge: tuple[int, int]) -> str:
    """A date bound's words: the year alone when it sits on the year's edge ("bis 1919")."""
    return str(day.year) if (day.month, day.day) == year_edge else day.isoformat()


def _sentence_facets(filters: SearchFilters) -> tuple[Facet, ...]:
    """The facets ``sentence`` reads: its slots' and the file types of "+ Filter"."""
    return (
        "collection",
        "decades",
        "media_type",
        *(("document_type",) if _typed(filters) else ()),
        "file_kind",
    )


def _typed(filters: SearchFilters) -> bool:
    """Does the sentence offer the Dokumenttyp slot (a Medienart that carries one is set)?"""
    return filters.media_type == vocab.DOCUMENT_TYPE_MEDIA_TYPE


def _slot(
    state: browse.SearchState,
    param: str,
    value_label: str | None,
    unset_label: str,
    items: tuple[_FacetItem, ...],
    *,
    under: tuple[tuple[str, str], ...] = (),
) -> _Slot:
    """A slot reads its set value's words, else ``unset_label``; its menu clears it when set, after
    the slots it sits ``under`` (param, unset label), whose clearing takes it along."""
    clears = (*under, (param, unset_label)) if value_label is not None else ()
    return _Slot(
        label=value_label or unset_label,
        unset_label=unset_label,
        clears=tuple(
            _FacetItem(label=label, count="", active=False, query=state.without(p).query())
            for p, label in clears
        ),
        items=items,
    )


def _toggle(
    state: browse.SearchState, param: str, label: str, active: bool, count: int | None = None
) -> _FacetItem:
    """A boolean filter's entry: set, it removes the filter; unset, it adds ``param=1``."""
    query = (state.without(param) if active else state.with_(param, "1")).query()
    return _FacetItem(label, "" if count is None else vocab.count(count), active, query)


def _facet_items(
    state: browse.SearchState,
    param: str,
    counts: tuple[FacetCount, ...],
    *,
    label: Callable[[str], str] = str,
) -> tuple[_FacetItem, ...]:
    """A facet's values as menu entries, named by ``label``. The value that is set removes its
    filter when clicked; every other one sets it."""
    active_value = state.value(param)
    return tuple(
        _FacetItem(
            label=label(fc.value),
            count=vocab.count(fc.count),
            active=fc.value == active_value,
            query=(
                state.without(param) if fc.value == active_value else state.with_(param, fc.value)
            ).query(),
        )
        for fc in counts
    )


def article_detail(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /articles/<ulid>`` — the Lesesaal read page: one template for every viewer, fed the
    ``visible`` projection (spec §4/§10)."""
    archive = Archive.canonical()
    chooser = CollectionChooser.of(archive)
    resolution = resolve_visible_detail(request, ulid, archive, chooser)
    if resolution is None:
        return not_found()
    return render_screen(
        request, "workbench/detail.html", _detail_context(resolution), chooser=chooser
    )


def list_url(state: browse.SearchState) -> str:
    """The list showing ``state``: where a start-page area or a suggestion leads."""
    return f"{reverse('workbench')}?{state.query()}"


def preset_url(param: str, value: str, within: browse.SearchState | None = None) -> str:
    """The list with ``param`` set to ``value``. ``within`` (a list's state) keeps what its search
    form carries besides ``q``."""
    kept = replace(within, text=None) if within else browse.SearchState()
    return list_url(kept.with_(param, value))


@dataclass(frozen=True, slots=True)
class CollectionCrumb:
    """One Collection breadcrumb hop: the collection name + the workbench link into its facet."""

    name: str
    href: str


def collection_crumbs(chain: ResolvedChain) -> tuple[CollectionCrumb, ...]:
    """The chain as crumbs, root first (the chain is leaf-first), each opening the scoped list."""
    return tuple(
        CollectionCrumb(
            name=c.name,
            href=preset_url(browse.PARAM_COLLECTION, c.ulid),
        )
        for c in reversed(chain.collections)
    )


def _body_paragraphs(body: str) -> tuple[str, ...]:
    """No Markdown is rendered; the template escapes each paragraph (spec §3, §11)."""
    return tuple(block.strip() for block in body.split("\n\n") if block.strip())


def _detail_context(resolution: DetailResolution) -> dict[str, object]:
    """Built only from the projected Article and the member-safe chain."""
    article = resolution.article
    is_draft = article.lifecycle is Lifecycle.DRAFT
    slots = iter(range(len(article.media)))
    media = tuple(
        replace(tile, slot=next(slots)) if tile.is_image else tile
        for tile in media_tiles(article.ulid, article.media)
    )
    tags = tuple(BylineLink(label=t, href=preset_url(browse.PARAM_TAG, t)) for t in article.tags)
    # the first file leads as the cover only with a picture to show; otherwise it joins the rows
    cover = media[0] if media and (media[0].full_url or media[0].thumb_url) else None
    mark = article.deleted
    return {
        "ulid": article.ulid,
        "is_draft": is_draft,
        "is_template": article.template,
        # only an Archivist reaches a marked Article (ADR 0022): its page shows the Papierkorb state
        "deleted": None if mark is None else {"at": vocab.day(mark.at), "by": mark.by},
        # a Papierkorb mark already is the last change
        "last_change": None if mark is not None else _change(resolution.change),
        "versions": _versions(resolution.versions()),
        "version": resolution.version,
        # preview() names groups and ignores the lifecycle: archivists only (part-4-web.md)
        "publish_statement": (
            vocab.publish_statement(preview(article, resolution.chain))
            if resolution.is_archivist and is_draft
            else ""
        ),
        "title": article.title,
        "ref_code": article.ref_code or "",
        "date": vocab.date_parts(article.date),
        "doc_type": article.document_type or article.media_type or "",
        "creator": article.creator or "",
        "place": article.subject_place or "",
        "body_paragraphs": _body_paragraphs(article.body),
        # a marked Article's place is the Papierkorb
        "crumbs": (
            collection_crumbs(resolution.chain)
            if mark is None
            else (CollectionCrumb("Papierkorb", reverse("trash")),)
        ),
        "tags": tags,
        "delete_confirm": vocab.TRASH_CONFIRM
        if mark is None
        else vocab.delete_permanently_confirm(len(media)),
        "cover": cover,
        "more_media": media[1:] if cover else media,
        "lightbox": tuple(tile for tile in media if tile.is_image),
        "plates_heading": (
            vocab.FILES
            if cover is None
            else vocab.FURTHER_IMAGES
            if all(file_kind(ref) is FileKind.IMAGE for ref in article.media)
            else vocab.FURTHER_FILES
        ),
        "location": article.physical_location or "",
        "custom": article.custom,
    }


def _change(change: Change | None) -> dict[str, object] | None:
    if change is None:
        return None
    return {
        "day": vocab.day(change.at),
        "datetime": change.at.isoformat(),
        "moment": vocab.day_and_time(change.at),
        "by": change.by,
        "imported": change.by == legacy.CHANGED_BY,
    }


def _versions(versions: tuple[tuple[Version, Change | None], ...]) -> tuple[dict[str, object], ...]:
    """Newest first. One version alone would only repeat the last-change line: no list then."""
    if len(versions) < 2:
        return ()
    return tuple(
        {"number": number, "change": _change(change)} for number, change in reversed(versions)
    )


#: The Papierkorb's one search: the marked Articles by title. ``deleted`` prints no param, so its
#: pager prints a state that holds the page alone.
_PAPIERKORB = browse.SearchState(filters=SearchFilters(deleted=True), sort="title")


def trash(request: HttpRequest) -> HttpResponseBase:
    """``GET /trash`` — the Papierkorb (ADR 0022): the marked Articles by title, each with
    Wiederherstellen and "Endgültig löschen …". Archivist-only, GET-only; else the plain 404."""
    viewer = viewer_of(request)
    if not isinstance(viewer, Archivist) or request.method != "GET":
        return not_found()
    paging = browse.SearchState(page=browse.SearchState.parse(request.GET).page)
    page = replace(_PAPIERKORB, page=paging.page).search(viewer, facets=())
    archive = Archive.canonical()
    chooser = CollectionChooser.of(archive)
    rows = tuple(row for hit in page.hits if (row := _trash_row(archive, hit.ulid, chooser)))
    context: dict[str, object] = {
        "rows": rows,
        "pager": _pager(paging, page, []) if page.total else None,
    }
    return render_screen(request, "workbench/trash.html", context, chooser=chooser)


@dataclass(frozen=True, slots=True)
class _TrashRow:
    """One Papierkorb row, read from the canonical record: the index carries no CAS version."""

    ulid: ULID
    title: str
    ref_code: str
    collection: str
    deleted_at: str
    deleted_by: str
    version: Version


def _trash_row(archive: Archive, ulid: ULID, chooser: CollectionChooser) -> _TrashRow | None:
    """The row for ``ulid``, or ``None`` once it has left the Papierkorb since the index was
    written (restored, or deleted for good)."""
    try:
        stored = archive.articles.load(ulid)
    except ArchiveError:
        return None
    article, mark = stored.article, stored.article.deleted
    if mark is None:
        return None
    return _TrashRow(
        ulid=ulid,
        title=article.title,
        ref_code=article.ref_code or "",
        collection=chooser.name_of(article.collection_id) or "",
        deleted_at=vocab.day(mark.at),
        deleted_by=mark.by,
        version=stored.version,
    )
