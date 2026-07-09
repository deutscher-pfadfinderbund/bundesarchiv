"""Dev-only component library page (``/_dev/components/``).

Referenced ONLY from ``dev_urls`` (the switcher pattern): production settings never mount it, so
it is unreachable in prod by absence of a code path, not by a flag. It renders every design-system
atom (``templates/components/``) in all its variants, each shown side-by-side in light and dark —
the two columns force ``color-scheme`` per container, and ``light-dark()`` resolves per element,
so both modes render in one document without JS.

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

_FACET_ITEMS_SCHLAGWORTE = (
    {"label": "sommer", "count": 12, "query": "schlagwort=sommer", "active": False},
    {"label": "fahrt", "count": 7, "query": "schlagwort=fahrt", "active": False},
)

#: Token swatch sections: (section label, tuple of (background role, text role)).
_SWATCH_SURFACE_RAMP = (
    ("surface", "on-surface"),
    ("surface-container-lowest", "on-surface"),
    ("surface-container-low", "on-surface"),
    ("surface-container-mid", "on-surface"),
    ("surface-container-high", "on-surface"),
)
_SWATCH_PAIRS = (
    ("primary", "on-primary"),
    ("primary-container", "on-primary-container"),
    ("draft", "on-draft"),
    ("error", "on-error"),
)


def component_library(request: HttpRequest) -> HttpResponse:
    """GET: the component library. Static demo data only; never mounted in production."""
    return render(
        request,
        "components_demo.html",
        {
            "modes": _MODES,
            "sort_options": _SORT_OPTIONS,
            "facet_items_bestand": _FACET_ITEMS_BESTAND,
            "facet_items_schlagworte": _FACET_ITEMS_SCHLAGWORTE,
            "swatch_surface_ramp": _SWATCH_SURFACE_RAMP,
            "swatch_pairs": _SWATCH_PAIRS,
            "card_meta": ("Signatur F 12", "Datierung 1962-22", "Foto"),
        },
    )
