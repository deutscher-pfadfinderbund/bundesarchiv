"""Dev-only component library page (``/_dev/components/``).

Referenced ONLY from ``dev_urls`` (the switcher pattern): production settings never mount it, so
it is unreachable in prod by absence of a code path, not by a flag. It renders every design-system
component (``templates/components/``), each shown side-by-side in light and dark — the two columns
force ``color-scheme`` per container, and ``light-dark()`` resolves per element, so both modes
render in one document without JS.

ONE theme (owner ruling, 2026-08-06): design iterations happen ON the real components.

Doubles as developer documentation: every sample is annotated with its include path + params, and
a token-swatch section shows the monochrome ink/ground pairs and the lines with role names.
Page chrome is English (development-facing); the SAMPLE CONTENT inside atoms is German (product
UI copy). Sample data below is inert demo fixture data — no store, no index, no viewer.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.templatetags.static import static

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
#: carries a ref_code (lifecycle is decoupled from the sig slot) and its ENTWURF mark rides the
#: title (the SICHTBARKEIT column died, owner 2026-08-07 — quiet default: published shows nothing).
#: The sample Signaturen obey the domain fact (owner 2026-08-07): no spaces, 8 characters is the
#: practical ceiling — one row sits AT that ceiling so the storyboard shows the widest real code.
_ROW_CONTENT = (
    {
        "title": "Sommerfahrt 1962",
        "href": "#demo-detail",
        "ref_code": "F12",
        "datierung": "1962",
        "typ": "Foto",
        "draft": False,
    },
    {
        # The Signatur at the domain ceiling (owner 2026-08-07: no spaces, 8 characters is the
        # practical top) — the widest realistic code the sig column has to seat.
        "title": "Jahresbericht 1974",
        "href": "#demo-detail",
        "ref_code": "B3/1974a",
        "datierung": "1974",
        "typ": "Bericht",
        "draft": False,
    },
    {
        "title": "Vorstandsprotokoll März 1980",
        "href": "#demo-detail",
        "ref_code": "V7",
        "datierung": "1980-03",
        "typ": "Protokoll",
        "draft": False,
    },
    {
        # A draft WITH a Signatur: lifecycle (ENTWURF badge) is decoupled from the sig slot.
        "title": "Lagerchronik",
        "href": "#demo-detail",
        "ref_code": "C5",
        "datierung": "1984",
        "typ": "Chronik",
        "draft": True,
    },
    {
        # Absence renders as absence (no em-dash). Datierung present, Typ absent: in the narrow fold
        # this shows just "1990" with NO dangling separator.
        "title": "Undatierter Zugang",
        "href": "#demo-detail",
        "ref_code": "Z1",
        "datierung": "1990",
        "typ": "",
        "draft": False,
    },
    {
        # Typ present, Datierung absent: the fold shows just "Notiz" with NO leading separator.
        "title": "Lose Notiz",
        "href": "#demo-detail",
        "ref_code": "",
        "datierung": "",
        "typ": "Notiz",
        "draft": False,
    },
    {
        # Neither Datierung nor Typ: the narrow fold shows NO second line at all.
        "title": "Ohne Datierung und Typ",
        "href": "#demo-detail",
        "ref_code": "",
        "datierung": "",
        "typ": "",
        "draft": False,
    },
)

#: Shared action hrefs spliced once — content dicts above stay content-only.
_LEDGER_ROWS = tuple(
    {**row, "bearbeiten_href": "#demo-edit", "vorschau_href": "#demo-vorschau"}
    for row in _ROW_CONTENT
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

#: Token swatches: (background role, text role) pairs, then the line roles.
_SWATCH_PAIRS = (
    ("ground", "ink"),
    ("ground", "ink-2"),
    ("ground", "ink-3"),
    ("ink", "ground"),
    ("error", "ground"),
    ("band-ground", "band-ink"),
    ("band-ground", "band-ink-2"),
)
_SWATCH_LINES = ("rule", "edge", "faint")


def component_library(request: HttpRequest) -> HttpResponse:
    """GET: the component library — the ONE baseline stylesheet (components.css).

    Never mounted in production."""
    return render(
        request,
        "components_demo.html",
        {
            "stylesheet": static("components.css"),
            "modes": _MODES,
            "sort_options": _SORT_OPTIONS,
            "facet_items_bestand": _FACET_ITEMS_BESTAND,
            "swatch_pairs": _SWATCH_PAIRS,
            "swatch_lines": _SWATCH_LINES,
            "ledger_rows": _LEDGER_ROWS,
            "ledger_columns": _LEDGER_COLUMNS,
        },
    )
