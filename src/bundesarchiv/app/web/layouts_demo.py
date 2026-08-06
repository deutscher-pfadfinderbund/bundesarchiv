"""Dev-only layout demo pages (``/_dev/layouts/<name>/``).

Referenced ONLY from ``dev_urls`` (the same discipline as the component library and the viewer
switcher): production settings never mount this, so it is unreachable in prod by absence of a code
path, not by a flag. Each page renders a FULL archivist-workbench layout composed from the REAL
partials (components/facet_group, components/ledger, workbench/_pane) over static German demo
context defined here — no store, no index, no viewer; lockstep with the live app by construction.
The layouts iterate the PAGE FRAME (header + facet sidebar + ledger + preview pane).

ONE layout, whitelisted (unknown name → 404, never a path interpolation):
- ``split-narrow`` — when the preview pane is open the facet sidebar stays full and the ledger
                     re-densifies by itself (it is a size container; owner's pick over the
                     rejected "split-rail", whose collapsed-rail state read as confusing).

Both pane states are SERVER-RENDERED, zero JS: ``?vorschau=1`` opens the pane, ``?vorschau=0``
(default) closes it; the demo chrome links switch them. Below 1280px a media query hides the pane
and returns the ledger to full/no-pane — the layout css owns that, the view does not branch on width.

The layout css is a dev experiment, so it is served by a dev-only whitelisted static route
(``/_dev/static/layouts.css``), never mounted in prod. Page chrome is English (development-facing);
the content inside the atoms is German product UI copy.
"""

from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app.web.browse_views import _serve_static

#: The layout whitelist: name → human label. An entry here is the ONLY way a layout becomes
#: routable. Unknown name → 404. One layout after the owner's review (split-rail rejected).
LAYOUTS: dict[str, str] = {
    "split-narrow": "Split narrow (ledger folds to two-line when the pane opens)",
}

#: The dev-only layout stylesheet (served by the whitelisted dev static route below).
LAYOUT_STYLESHEET = "layouts.css"

#: The known demo set plus extra plausible rows so the ledger scrolls. Each dict carries a
#: ledger_row's params. Two drafts demonstrate the sig/lifecycle decoupling: one WITH a ref_code
#: (code shows; ENTWURF is the only lifecycle signal) and one WITHOUT (hollow "ohne Signatur" slot).
_LEDGER_ROWS: tuple[dict[str, object], ...] = (
    {
        "title": "Sommerfahrt 1962",
        "href": "?artikel=sommerfahrt-1962",
        "ref_code": "F 12",
        "datierung": "1962",
        "typ": "Foto",
        "draft": False,
        "visibility": "Öffentlich",
    },
    {
        "title": "Jahresbericht 1974",
        "href": "?artikel=jahresbericht-1974",
        "ref_code": "B 3",
        "datierung": "1974",
        "typ": "Bericht",
        "draft": False,
        "visibility": "Alle Mitglieder",
    },
    {
        "title": "Vorstandsprotokoll März 1980",
        "href": "?artikel=vorstandsprotokoll-1980-03",
        "ref_code": "V 7",
        "datierung": "1980-03",
        "typ": "Protokoll",
        "draft": False,
        "visibility": "Gruppe: vorstand",
    },
    {
        # Draft WITH a Signatur: the ENTWURF badge is the only lifecycle signal; the sig shows.
        "title": "Lagerchronik",
        "href": "?artikel=lagerchronik",
        "ref_code": "C 5",
        "datierung": "1984",
        "typ": "Chronik",
        "draft": True,
        "visibility": "",
    },
    {
        "title": "Winterlager 1958",
        "href": "?artikel=winterlager-1958",
        "ref_code": "F 4",
        "datierung": "1958",
        "typ": "Foto",
        "draft": False,
        "visibility": "Öffentlich",
    },
    {
        "title": "Kassenbuch 1965-1969",
        "href": "?artikel=kassenbuch-1965-69",
        "ref_code": "K 2",
        "datierung": "1965/1969",
        "typ": "Buch",
        "draft": False,
        "visibility": "Gruppe: vorstand",
    },
    {
        "title": "Fahrtenbericht Norwegen 1971",
        "href": "?artikel=norwegen-1971",
        "ref_code": "B 9",
        "datierung": "1971",
        "typ": "Bericht",
        "draft": False,
        "visibility": "Alle Mitglieder",
    },
    {
        "title": "Liederbuch (2. Auflage)",
        "href": "?artikel=liederbuch-2",
        "ref_code": "D 1",
        "datierung": "1969",
        "typ": "Druck",
        "draft": False,
        "visibility": "Öffentlich",
    },
    {
        "title": "Gruppenfoto Pfingsten 1983",
        "href": "?artikel=pfingsten-1983",
        "ref_code": "F 21",
        "datierung": "1983-05",
        "typ": "Foto",
        "draft": False,
        "visibility": "Öffentlich",
    },
    {
        "title": "Satzung des Trägervereins",
        "href": "?artikel=satzung",
        "ref_code": "A 1",
        "datierung": "1955",
        "typ": "Urkunde",
        "draft": False,
        "visibility": "Öffentlich",
    },
    {
        # Draft WITHOUT a Signatur: the hollow slot means "ohne Signatur" (ref_code absent), a
        # separate axis from the ENTWURF lifecycle badge.
        "title": "Festschrift 60 Jahre",
        "href": "?artikel=festschrift-60",
        "ref_code": "",
        "datierung": "",
        "typ": "Druck",
        "draft": True,
        "visibility": "",
    },
    {
        "title": "Rundbrief Herbst 1977",
        "href": "?artikel=rundbrief-1977-h",
        "ref_code": "R 6",
        "datierung": "1977-10",
        "typ": "Rundbrief",
        "draft": False,
        "visibility": "Alle Mitglieder",
    },
)

#: Sortable column headers for the ledger: (label, key matching the cell modifier, query stub,
#: active, order). Signatur is the active ascending sort in the demo.
_LEDGER_COLUMNS: tuple[dict[str, object], ...] = (
    {
        "label": "Sig",
        "key": "sig",
        "sortable": True,
        "query": "sort=signatur",
        "active": True,
        "order": "asc",
    },
    {
        "label": "Titel",
        "key": "titel",
        "sortable": True,
        "query": "sort=titel",
        "active": False,
        "order": "asc",
    },
    {
        "label": "Datierung",
        "key": "datierung",
        "sortable": True,
        "query": "sort=datierung",
        "active": False,
        "order": "asc",
    },
    {"label": "Typ", "key": "typ", "sortable": False},  # Typ is not a sortable index column
)

#: Facet sidebar groups; items match facet_group.html's contract (label, count, query, active).
#: ``open`` seeds each <details> group's initial expanded/collapsed state.
_FACET_GROUPS: tuple[dict[str, object], ...] = (
    {
        "heading": "Bestand",
        "open": True,
        "items": (
            {"label": "Fotografien", "count": 24, "query": "bestand=FOTOS", "active": False},
            {"label": "Aktenbestand", "count": 8, "query": "bestand=AKTEN", "active": True},
            {
                "label": "Vorstandsunterlagen",
                "count": 3,
                "query": "bestand=VORSTAND",
                "active": False,
            },
        ),
    },
    {
        "heading": "Dokumenttyp",
        "open": True,
        "items": (
            {"label": "Foto", "count": 31, "query": "typ=foto", "active": False},
            {"label": "Bericht", "count": 12, "query": "typ=bericht", "active": False},
            {"label": "Protokoll", "count": 7, "query": "typ=protokoll", "active": False},
        ),
    },
    {
        "heading": "Schlagworte",
        "open": False,
        "items": (
            {"label": "sommer", "count": 12, "query": "schlagwort=sommer", "active": True},
            {"label": "fahrt", "count": 7, "query": "schlagwort=fahrt", "active": False},
            {"label": "lager", "count": 5, "query": "schlagwort=lager", "active": False},
        ),
    },
    {
        "heading": "Jahrzehnte",
        "open": False,
        "items": (
            {"label": "1950er", "count": 6, "query": "jahrzehnt=1950", "active": False},
            {"label": "1960er", "count": 14, "query": "jahrzehnt=1960", "active": False},
            {"label": "1970er", "count": 11, "query": "jahrzehnt=1970", "active": False},
            {"label": "1980er", "count": 4, "query": "jahrzehnt=1980", "active": False},
        ),
    },
)

#: The static preview shown in the pane (the first result) — the REAL ``workbench/_pane.html``
#: renders it, so the keys mirror the pane view-model's contract (browse_views._Pane). No media →
#: the hollow placeholder.
_PREVIEW = {
    "title": "Sommerfahrt 1962",
    "ref_code": "F 12",
    "datierung": "1962",
    "typ": "Foto",
    "media": (),
    "close_href": "?vorschau=0",
    "oeffnen_href": "#demo-detail",
    "bearbeiten_href": "#demo-edit",
}


def layout_demo(request: HttpRequest, name: str) -> HttpResponse:
    """GET ``/_dev/layouts/<name>/`` — a full workbench layout demo. Unknown name → 404 (whitelist,
    never a path interpolation). ``?vorschau=1`` opens the preview pane; anything else closes it.
    Never mounted in production."""
    if name not in LAYOUTS:
        return HttpResponse(b"Unknown layout", status=404, content_type="text/plain")
    vorschau = request.GET.get("vorschau") == "1"
    # The two state-switch links keep every other param; here the only state is vorschau.
    return render(
        request,
        "layouts_demo.html",
        {
            "layout_name": name,
            "vorschau": vorschau,
            "stylesheet": f"/_dev/layouts/static/{LAYOUT_STYLESHEET}",
            "ledger_rows": _LEDGER_ROWS,
            "ledger_columns": _LEDGER_COLUMNS,
            "facet_groups": _FACET_GROUPS,
            "preview": _PREVIEW,
        },
    )


def serve_layout_stylesheet(request: HttpRequest, filename: str) -> HttpResponseBase:
    """``GET /_dev/static/<filename>`` for the layout stylesheet — a dev-only whitelisted route.
    The layout css is a design experiment; it never gets a production static route. Anything but the
    one whitelisted filename → 404, so this can never serve arbitrary static files."""
    if filename != LAYOUT_STYLESHEET:
        return HttpResponse(b"Unknown stylesheet", status=404, content_type="text/plain")
    return _serve_static(filename, "text/css")
