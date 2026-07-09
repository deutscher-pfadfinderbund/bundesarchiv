"""Dev-only component library page (``/_dev/components/`` + ``/_dev/components/<variant>/``).

Referenced ONLY from ``dev_urls`` (the switcher pattern): production settings never mount it, so
it is unreachable in prod by absence of a code path, not by a flag. It renders every design-system
atom (``templates/components/``) in all its variants, each shown side-by-side in light and dark —
the two columns force ``color-scheme`` per container, and ``light-dark()`` resolves per element,
so both modes render in one document without JS.

DESIGN-VARIANT ROUTES (owner process, 2026-07-10): design iterations happen ON the real atoms.
``/_dev/components/`` renders the baseline stylesheet (components.css); ``/_dev/components/
<variant>/`` renders the SAME page with a variant stylesheet from the explicit ``VARIANTS``
whitelist. Unknown variant → 404. Variant stylesheets are dev experiments, so they are served by
a dev-only route (``/_dev/static/<filename>``), never mounted in prod.

Doubles as developer documentation: every sample is annotated with its include path + params, and
a token-swatch section shows the surface ramp and the primary/draft/error pairs with role names.
Page chrome is English (development-facing); the SAMPLE CONTENT inside atoms is German (product
UI copy). Sample data below is inert demo fixture data — no store, no index, no viewer.
"""

from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app.web.browse_views import _serve_static

#: The design-variant whitelist: variant name -> stylesheet filename under ``static/``. An entry
#: here is the ONLY way a variant becomes routable (both the page and its stylesheet). Baseline
#: (components.css) is not an entry — it is the no-variant route.
VARIANTS: dict[str, str] = {
    "stamp": "components-stamp.css",
    "papier": "components-papier.css",
}

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


def component_library(request: HttpRequest, variant: str | None = None) -> HttpResponse:
    """GET: the component library — baseline (no variant) or a whitelisted design variant.

    The variant only swaps the STYLESHEET the page links; template and sample data are identical,
    so what iterates is the design system itself. Unknown variant → 404 (whitelist, never a path
    interpolation). Never mounted in production."""
    if variant is None:
        stylesheet = "/static/components.css"
    else:
        filename = VARIANTS.get(variant)
        if filename is None:
            return HttpResponse(b"Unknown variant", status=404, content_type="text/plain")
        stylesheet = f"/_dev/static/{filename}"
    return render(
        request,
        "components_demo.html",
        {
            "stylesheet": stylesheet,
            "variant": variant,
            "variant_names": sorted(VARIANTS),
            "modes": _MODES,
            "sort_options": _SORT_OPTIONS,
            "facet_items_bestand": _FACET_ITEMS_BESTAND,
            "facet_items_schlagworte": _FACET_ITEMS_SCHLAGWORTE,
            "swatch_surface_ramp": _SWATCH_SURFACE_RAMP,
            "swatch_pairs": _SWATCH_PAIRS,
            "card_meta": ("Signatur F 12", "Datierung 1962-22", "Foto"),
        },
    )


def serve_variant_stylesheet(request: HttpRequest, filename: str) -> HttpResponseBase:
    """``GET /_dev/static/<filename>`` — a WHITELISTED variant stylesheet (dev-only route).
    Variant css files are design experiments; they never get a production static route. Anything
    not registered in ``VARIANTS`` → 404, so the route cannot serve arbitrary static files."""
    if filename not in VARIANTS.values():
        return HttpResponse(b"Unknown stylesheet", status=404, content_type="text/plain")
    return _serve_static(filename, "text/css")
