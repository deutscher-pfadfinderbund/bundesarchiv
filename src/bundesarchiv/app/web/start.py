"""The start page (``GET /``): areas on one neutral grid, each a preset of the one list.

An area is a function ``(viewer, request, counts, bestand) -> context`` plus one template partial
(``start/_<area>.html``). It builds its data from ``counts``, the page's ONE viewer-scoped
``facet_counts`` call, and its links are list presets (``preset_url``). The grid places what an area's
root declares (``data-span``, ``data-absent``) and knows nothing else about it. Which areas a role
gets, in which order, is the role's tuple below and nowhere else.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from django.http import HttpRequest, HttpResponse, HttpResponsePermanentRedirect
from django.urls import reverse

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import browse, vocab
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.browse_views import preset_url
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.viewer import Archivist, Viewer
from bundesarchiv.index.query import Facet, FacetCount, facet_counts

type Counts = Mapping[str, tuple[FacetCount, ...]]
type Build = Callable[[Viewer, HttpRequest, Counts, BestandChooser], Mapping[str, object]]

#: Every facet any area reads, so the page asks the index once.
_FACETS: tuple[Facet, ...] = ("collection",)


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


def search_area(
    _viewer: Viewer, _request: HttpRequest, _counts: Counts, _bestand: BestandChooser
) -> Mapping[str, object]:
    """The list's own search sentence, without its filter slots: it submits to the list."""
    return {}


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


_SEARCH = Area("start/_search.html", search_area)
_BESTAENDE = Area("start/_bestaende.html", bestaende)

ARCHIVIST: tuple[Area, ...] = (_SEARCH, _BESTAENDE)
MEMBER: tuple[Area, ...] = (_SEARCH, _BESTAENDE)


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
