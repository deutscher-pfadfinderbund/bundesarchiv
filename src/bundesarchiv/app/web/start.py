"""The start page (``GET /``): areas on one neutral grid, each a preset of the one list.

An area is a function ``(viewer, request, counts, bestand) -> context`` plus one template partial
(``start/_<area>.html``). It builds its data from ``counts``, the page's ONE viewer-scoped
``facet_counts`` call, and its links are list presets (``preset_url``). The grid places what an area's
root declares (``data-span``, ``data-absent``) and knows nothing else about it. Which areas a role
gets, in which order, is the role's tuple below and nowhere else.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import takewhile

from django.http import HttpRequest, HttpResponse, HttpResponsePermanentRedirect
from django.urls import reverse

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import browse, vocab
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.browse_views import preset_url
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.viewer import Archivist, Viewer
from bundesarchiv.index.query import (
    Facet,
    FacetCount,
    SearchFilters,
    dateless_count,
    facet_counts,
    search,
)

type Counts = Mapping[str, tuple[FacetCount, ...]]
type Build = Callable[[Viewer, HttpRequest, Counts, BestandChooser], Mapping[str, object]]

#: Every facet any area reads, so the page asks the index once.
_FACETS: tuple[Facet, ...] = ("collection", "media_type", "decades")


@dataclass(frozen=True, slots=True)
class Area:
    """One area: its partial and the function that builds the partial's ``area`` context."""

    partial: str
    build: Build


@dataclass(frozen=True, slots=True)
class Tile:
    """One link of a tile list: its words, its count (raw and spelled) and the list preset."""

    label: str
    count: int
    count_label: str
    href: str


#: How many titles "Weiter bearbeiten" names before it folds the rest into "und n weitere".
_RESUME_TITLES = 3
#: How many Medienarten "Nach Art" names.
_MEDIA_TYPES = 7
#: How many Articles "Zuletzt hinzugefügt" lists.
_RECENT = 5


def search_area(
    viewer: Viewer, _request: HttpRequest, _counts: Counts, _bestand: BestandChooser
) -> Mapping[str, object]:
    """The list's own search field, without its filter slots: it submits to the list. For an
    Archivist it carries "Weiter bearbeiten" under it: every draft, newest ``added_at`` first (the
    index has no "changed at"). At most three titles; more than three: two and "und n weitere"."""
    if not isinstance(viewer, Archivist):
        return {}
    page = search(
        viewer,
        filters=SearchFilters(drafts_only=True),
        sort="added",
        page_size=_RESUME_TITLES + 1,
        facets=(),
    )
    shown = page.hits if page.total <= _RESUME_TITLES else page.hits[: _RESUME_TITLES - 1]
    return {
        "drafts": tuple((h.title, reverse("artikel-bearbeiten", args=[h.ulid])) for h in shown),
        "more": page.total - len(shown),
        "more_href": preset_url(browse.PARAM_DRAFTS, "1"),
    }


def bestaende(
    _viewer: Viewer, _request: HttpRequest, counts: Counts, bestand: BestandChooser
) -> Mapping[str, object]:
    """The top-level Bestände the viewer has Articles in, most first. ``counts`` is already
    viewer-scoped, and a Bestand it does not count is not named."""
    top = {c.ulid: c.name for c in bestand.by_ulid().values() if c.parent_id is None}
    tiles = sorted(
        (
            Tile(
                top[fc.value],
                fc.count,
                vocab.count(fc.count),
                preset_url(browse.PARAM_COLLECTION, fc.value),
            )
            for fc in counts["collection"]
            if fc.value in top
        ),
        key=lambda t: (-t.count, t.label),
    )
    return {"tiles": tuple(tiles)}


def nach_art(
    _viewer: Viewer, _request: HttpRequest, counts: Counts, _bestand: BestandChooser
) -> Mapping[str, object]:
    """The most-used Medienarten as tiles (``counts`` is viewer-scoped, most first). The rest get
    no row: the list has no Medienart slot, so a catch-all could only open the whole list."""
    tiles = tuple(
        Tile(
            fc.value,
            fc.count,
            vocab.count(fc.count),
            preset_url(browse.PARAM_MEDIA_TYPE, fc.value),
        )
        for fc in counts["media_type"][:_MEDIA_TYPES]
    )
    return {"tiles": tiles}


@dataclass(frozen=True, slots=True)
class Row:
    """One row of the Zeitleiste: a ``Tile``; its bar is the tile's count out of ``top``."""

    tile: Tile
    top: int
    apart: bool = False


#: A leading decade under this share of the largest folds into one "bis …" row (two at least).
_SPARSE_SHARE = 50


def fold_sparse(decades: Sequence[FacetCount]) -> tuple[FacetCount, ...]:
    """The decades (oldest first) with a sparse leading run, two decades or more, folded into one
    "bis <year before the first dense decade>" count. An archive of only sparse decades keeps them."""
    limit = max((fc.count for fc in decades), default=0) / _SPARSE_SHARE
    lead = tuple(takewhile(lambda fc: fc.count < limit, decades))
    if len(lead) < 2 or len(lead) == len(decades):
        return tuple(decades)
    last_year = int(decades[len(lead)].value) - 1
    return (FacetCount(f"bis {last_year}", sum(fc.count for fc in lead)), *decades[len(lead) :])


def zeitleiste(
    viewer: Viewer, _request: HttpRequest, counts: Counts, _bestand: BestandChooser
) -> Mapping[str, object]:
    """The decades, oldest first (a sparse start folded, ``fold_sparse``), then "Unbekannt" (the
    undated Articles) set apart. Bars are proportional to the largest row."""
    decades = fold_sparse(sorted(counts["decades"], key=lambda fc: int(fc.value)))
    undated = dateless_count(viewer)
    tiles = [
        Tile(fc.value, fc.count, vocab.count(fc.count), _date_to_preset(fc.value))
        if fc.value.startswith("bis ")
        else Tile(
            f"{fc.value}er",
            fc.count,
            vocab.count(fc.count),
            preset_url(browse.PARAM_DECADE, fc.value),
        )
        for fc in decades
    ]
    if undated:
        tiles.append(
            Tile("Unbekannt", undated, vocab.count(undated), preset_url(browse.PARAM_DATELESS, "1"))
        )
    top = max((t.count for t in tiles), default=1)
    return {"rows": tuple(Row(t, top, apart=t.label == "Unbekannt") for t in tiles)}


def _date_to_preset(label: str) -> str:
    """The list up to the end of the year a folded "bis <year>" row names."""
    return preset_url(browse.PARAM_DATE_TO, f"{label.removeprefix('bis ')}-12-31")


def zuletzt_hinzugefuegt(
    viewer: Viewer, _request: HttpRequest, _counts: Counts, bestand: BestandChooser
) -> Mapping[str, object]:
    """The newest Articles by ``added_at`` the viewer may see: the day added, title, Bestand."""
    hits = search(viewer, sort="added", page_size=_RECENT, facets=()).hits
    known = bestand.by_ulid()
    days = [vocab.day(h.added_at) if h.added_at else "" for h in hits]
    return {
        "rows": tuple(
            (
                day if day != previous else "",  # a repeated day printed once, as a ditto
                h.title,
                reverse("artikel-detail", args=[h.ulid]),
                known[h.collection_id].name if h.collection_id in known else "",
            )
            for h, day, previous in zip(hits, days, ["", *days], strict=False)
        ),
        "all_href": preset_url(browse.PARAM_SORT, browse.sort_label("added")),
    }


_SEARCH = Area("start/_search.html", search_area)
_BESTAENDE = Area("start/_bestaende.html", bestaende)
_NACH_ART = Area("start/_nach_art.html", nach_art)
_ZEITLEISTE = Area("start/_zeitleiste.html", zeitleiste)
_ZULETZT = Area("start/_zuletzt.html", zuletzt_hinzugefuegt)

ARCHIVIST: tuple[Area, ...] = (_SEARCH, _BESTAENDE, _NACH_ART, _ZEITLEISTE, _ZULETZT)
MEMBER: tuple[Area, ...] = (_SEARCH, _BESTAENDE, _NACH_ART, _ZEITLEISTE, _ZULETZT)


def start(request: HttpRequest) -> HttpResponse:
    """``GET /`` — the start page. With a query string it redirects to the list with that query:
    the list lived here until 2026-10-01, and its links stay valid (owner-interview-2026-08.md). A
    redirect, not an alias: the list's links are relative (``?…``), so an empty query on ``/``
    would land here."""
    if query := request.META.get("QUERY_STRING"):
        return HttpResponsePermanentRedirect(f"{reverse('workbench')}?{query}")
    viewer = viewer_of(request)
    counts = facet_counts(viewer, _FACETS)
    bestand = BestandChooser.of(Archive.canonical())
    areas = ARCHIVIST if isinstance(viewer, Archivist) else MEMBER
    context: dict[str, object] = {
        "areas": tuple((a.partial, a.build(viewer, request, counts, bestand)) for a in areas)
    }
    return render_screen(request, "start/start.html", context, bestand=bestand)
