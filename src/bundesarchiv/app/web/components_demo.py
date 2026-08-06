"""Dev-only component library page (``/_dev/components/``).

Referenced ONLY from ``dev_urls`` (the switcher pattern): production settings never mount it, so
it is unreachable in prod by absence of a code path, not by a flag. It renders every design-system
component (``templates/components/``), each shown side-by-side in light and dark — the two columns
force ``color-scheme`` per container, and ``light-dark()`` resolves per element, so both modes
render in one document without JS.

ONE theme (owner ruling, 2026-08-06): the papier variant file and the variant toggle are gone —
the papier recipe (sheet material) was promoted into the baseline as cue-register row 8
(``docs/design/design-review-law.md``). Design iterations happen ON the real components.

Doubles as developer documentation: every sample is annotated with its include path + params, and
a token-swatch section shows the surface ramp and the primary/draft/error pairs with role names.
Page chrome is English (development-facing); the SAMPLE CONTENT inside atoms is German (product
UI copy). Sample data below is inert demo fixture data — no store, no index, no viewer.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

#: Both color-scheme values, in render order — the template's per-sample column loop.
_MODES = ("light", "dark")

_SORT_OPTIONS = (
    ("relevanz", "Relevanz"),
    ("signatur", "Signatur"),
    ("datierung", "Datierung"),
    ("titel", "Titel"),
)

_FACET_ITEMS_BESTAND = (
    {"label": "Fotografien", "count": 24, "query": "bestand=FOTOS", "active": False},
    {"label": "Aktenbestand", "count": 8, "query": "bestand=AKTEN", "active": True},
    {"label": "Vorstandsunterlagen", "count": 3, "query": "bestand=VORSTAND", "active": False},
)

#: Ledger sample rows — the known demo set. Each dict carries a ledger_row's params; the draft row
#: carries a ref_code (lifecycle is decoupled from the sig slot) and shows the ENTWURF badge as its
#: sole SICHTBARKEIT signal.
_LEDGER_ROWS = (
    {
        "title": "Sommerfahrt 1962",
        "href": "#demo-detail",
        "ref_code": "F 12",
        "datierung": "1962",
        "typ": "Foto",
        "draft": False,
        "visibility": "Öffentlich",
        "action_label": "Bearbeiten",
        "action_href": "#demo-edit",
    },
    {
        "title": "Jahresbericht 1974",
        "href": "#demo-detail",
        "ref_code": "B 3",
        "datierung": "1974",
        "typ": "Bericht",
        "draft": False,
        "visibility": "Alle Mitglieder",
        "action_label": "Bearbeiten",
        "action_href": "#demo-edit",
    },
    {
        "title": "Vorstandsprotokoll März 1980",
        "href": "#demo-detail",
        "ref_code": "V 7",
        "datierung": "1980-03",
        "typ": "Protokoll",
        "draft": False,
        "visibility": "Gruppe: vorstand",
        "action_label": "Bearbeiten",
        "action_href": "#demo-edit",
    },
    {
        # A draft WITH a Signatur: lifecycle (ENTWURF badge) is decoupled from the sig slot.
        "title": "Lagerchronik",
        "href": "#demo-detail",
        "ref_code": "C 5",
        "datierung": "1984",
        "typ": "Chronik",
        "draft": True,
        "visibility": "",
        "action_label": "Bearbeiten",
        "action_href": "#demo-edit",
    },
    {
        # Absence renders as absence (no em-dash). Datierung present, Typ absent: in the narrow fold
        # this shows just "1990" with NO dangling separator.
        "title": "Undatierter Zugang",
        "href": "#demo-detail",
        "ref_code": "Z 1",
        "datierung": "1990",
        "typ": "",
        "draft": False,
        "visibility": "Öffentlich",
        "action_label": "Bearbeiten",
        "action_href": "#demo-edit",
    },
    {
        # Typ present, Datierung absent: the fold shows just "Notiz" with NO leading separator.
        "title": "Lose Notiz",
        "href": "#demo-detail",
        "ref_code": "",
        "datierung": "",
        "typ": "Notiz",
        "draft": False,
        "visibility": "Öffentlich",
        "action_label": "Bearbeiten",
        "action_href": "#demo-edit",
    },
    {
        # Neither Datierung nor Typ: the narrow fold shows NO second line at all.
        "title": "Ohne Datierung und Typ",
        "href": "#demo-detail",
        "ref_code": "",
        "datierung": "",
        "typ": "",
        "draft": False,
        "visibility": "Öffentlich",
        "action_label": "Bearbeiten",
        "action_href": "#demo-edit",
    },
)

#: Sortable column headers for the ledger demo: (label, key matching the cell modifier, query stub,
#: active, order). "signatur" is shown as the active ascending sort.
_LEDGER_COLUMNS = (
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

#: Token swatch sections: (section label, tuple of (background role, text role)).
_SWATCH_SURFACE_RAMP = (
    ("surface", "on-surface"),
    ("surface-container-lowest", "on-surface"),
    ("surface-container-low", "on-surface"),
    ("surface-container-mid", "on-surface"),
    ("surface-container-high", "on-surface"),
)
_SWATCH_SHEETS = (
    ("sheet-lowest", "on-surface"),
    ("sheet", "on-surface"),
    ("sheet-high", "on-surface"),
    ("sheet-hover", "on-surface"),
)
_SWATCH_PAIRS = (
    ("primary", "on-primary"),
    ("primary-container", "on-primary-container"),
    ("draft", "on-draft"),
    ("error", "on-error"),
)


def component_library(request: HttpRequest) -> HttpResponse:
    """GET: the component library — the ONE baseline stylesheet (components.css).

    Never mounted in production."""
    return render(
        request,
        "components_demo.html",
        {
            "stylesheet": "/static/components.css",
            "modes": _MODES,
            "sort_options": _SORT_OPTIONS,
            "facet_items_bestand": _FACET_ITEMS_BESTAND,
            "swatch_surface_ramp": _SWATCH_SURFACE_RAMP,
            "swatch_sheets": _SWATCH_SHEETS,
            "swatch_pairs": _SWATCH_PAIRS,
            "ledger_rows": _LEDGER_ROWS,
            "ledger_columns": _LEDGER_COLUMNS,
        },
    )
