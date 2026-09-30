"""Dev-only layout demo page (``/_dev/layouts/split-narrow/``).

Referenced ONLY from ``dev_urls`` (the same discipline as the component library and the viewer
switcher): production settings never mount this, so it is unreachable in prod by absence of a code
path, not by a flag. It renders a FULL archivist-workbench layout composed from the REAL
partials (workbench/_suchsatz, components/ledger, workbench/_pane) over static German demo
context defined here — no store, no index, no viewer; lockstep with the live app by construction.
The layout iterates the PAGE FRAME (header + search sentence + ledger + preview pane).

``split-narrow``: the search sentence spans the top (a2); when the preview pane is open the ledger
re-densifies by itself (it is a size container).

Both pane states are SERVER-RENDERED, zero JS: ``?vorschau=1`` opens the pane, ``?vorschau=0``
(default) closes it; the demo chrome links switch them. Below 1280px a media query hides the pane
and returns the ledger to full/no-pane — the layout css owns that, the view does not branch on width.

Page chrome is English (development-facing); the content inside the atoms is German product UI copy.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from bundesarchiv.app.web import browse, ledger
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.index.query import FileKind, SearchHit

#: The known demo set plus extra plausible rows so the ledger scrolls, printed through the REAL
#: ``ledger.build``. Two drafts: one with a Signatur, one without (lifecycle and Signatur are two
#: axes). The Kassenbuch Signatur sits at the domain ceiling (owner 2026-08-07: no spaces, 8
#: characters).
_ROWS: tuple[tuple[str, str, str, str, bool, tuple[tuple[FileKind, int], ...]], ...] = (
    ("Sommerfahrt 1962", "F12", "1962", "Fahrtenbericht", False, ((FileKind.IMAGE, 2),)),
    ("Jahresbericht 1974", "B3", "1974", "Chronik / Dokumentation", False, ()),
    ("Vorstandsprotokoll März 1980", "V7", "1980-03", "Protokoll", False, ((FileKind.PDF, 1),)),
    ("Lagerchronik", "C5", "1984", "Lagerheft", True, ()),
    ("Winterlager 1958", "F4", "1958", "Fahrtenbericht", False, ((FileKind.IMAGE, 1),)),
    ("Kassenbuch 1965-1969", "K2/65-69", "1965/1969", "Sonstiges", False, ()),
    ("Fahrtenbericht Norwegen 1971", "B9", "1971", "Fahrtenbericht", False, ()),
    ("Liederbuch (2. Auflage)", "D1", "1969", "Liederbuch", False, ((FileKind.PDF, 1),)),
    ("Gruppenfoto Pfingsten 1983", "F21", "1983-05", "Sonstiges", False, ((FileKind.IMAGE, 1),)),
    ("Satzung des Trägervereins", "A1", "1955", "Ordnung", False, ()),
    ("Festschrift 60 Jahre", "", "", "Sonstiges", True, ()),
)
_HITS = tuple(
    SearchHit(
        ulid=f"01KDEML0000000000000000{n:03d}",
        title=title,
        ref_code=ref or None,
        date_edtf=date or None,
        media_type=None,
        document_type=typ or None,
        is_draft=draft,
        tier="PUBLIC",
        groups=(),
        collection_id="",
        file_counts=files,
    )
    for n, (title, ref, date, typ, draft, files) in enumerate(_ROWS)
)

#: The demo ledger is sorted by Signatur, ascending, so one head shows its direction.
_LEDGER_QUERY = {"sortierung": "signatur"}


#: The search sentence's parts -- the demo mirror of browse_views._sentence: a set Bestand, two
#: open slots, one set filter no slot shows, and "+ Filter" (the archivist's two checks).
_SLOTS: tuple[dict[str, object], ...] = (
    {
        "label": "Aktenbestand",
        "unset_label": "allen Beständen",
        "clear_query": "schlagwort=sommer",
        "items": (
            {"label": "Fotografien", "count": "24", "query": "bestand=FOTOS", "active": False},
            {"label": "Aktenbestand", "count": "8", "query": "", "active": True},
        ),
    },
    {
        "label": "alle Jahrzehnte",
        "unset_label": "alle Jahrzehnte",
        "clear_query": None,
        "items": (
            {"label": "1950er", "count": "6", "query": "jahrzehnt=1950", "active": False},
            {"label": "1960er", "count": "14", "query": "jahrzehnt=1960", "active": False},
        ),
    },
    {
        "label": "jeder Typ",
        "unset_label": "jeder Typ",
        "clear_query": None,
        "items": (
            {"label": "Bericht", "count": "12", "query": "dokumenttyp=Bericht", "active": False},
        ),
    },
)
_SET_FILTERS = ({"label": "Schlagwort: sommer", "query": "bestand=AKTEN"},)
_FILTER_CHECKS = (
    {"label": "Digital (mit Dateien)", "count": "", "query": "digital=1", "active": False},
    {"label": "Entwürfe", "count": "", "query": "entwuerfe=1", "active": False},
)

#: The static preview shown in the pane (the first result) — the REAL ``workbench/_pane.html``
#: renders it, so the keys mirror the pane view-model's contract (browse_views._Pane). No media →
#: the hollow placeholder.
_PREVIEW = {
    "title": "Sommerfahrt 1962",
    "ref_code": "F12",
    "datierung": "1962",
    "typ": "Foto",
    "media": (),
    "close_href": "?vorschau=0",
    "oeffnen_href": "#demo-detail",
    "bearbeiten_href": "#demo-edit",
}


def layout_demo(request: HttpRequest) -> HttpResponse:
    """GET ``/_dev/layouts/split-narrow/`` — the full workbench layout demo. ``?vorschau=1`` opens
    the preview pane; anything else closes it. Never mounted in production."""
    vorschau = request.GET.get("vorschau") == "1"
    # The two state-switch links keep every other param; here the only state is vorschau.
    return render(
        request,
        "layouts_demo.html",
        {
            "vorschau": vorschau,
            "ledger": ledger.build(
                _HITS,
                columns=ledger.DEFAULT_COLUMNS,
                parsed=browse.parse_query(_LEDGER_QUERY),
                params=_LEDGER_QUERY,
                auswahl=(),
                is_archivist=True,
                selected_ulid=None,
                bestand=BestandChooser(lambda: ()),
            ),
            "slots": _SLOTS,
            "set_filters": _SET_FILTERS,
            "filter_checks": _FILTER_CHECKS,
            # the pager holds the count; a one-page list shows it alone (a2 rounds 9 and 10)
            "pager": {
                "stepped": False,
                "total": len(_HITS),
                "total_label": str(len(_HITS)),
                "noun": "Artikel",
            },
            "preview": _PREVIEW,
        },
    )
