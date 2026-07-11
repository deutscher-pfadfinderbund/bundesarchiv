"""Production ROOT_URLCONF (Part 4.3) — the prod-minimal HTTP surface.

Production settings set ``ROOT_URLCONF = "bundesarchiv.app.web.urls"`` and mount ONLY the media
routes needed to serve authorized bytes. Everything else stays prod-minimal (ADR 0004/0005: Django
is an adapter, not a web framework here). ``settings_dev`` composes this module (prod media routes)
WITH the dev viewer switcher (see ``dev_urls``), so dev gets both.

The public URL namespace never encodes filesystem paths (plan §4.3): media is addressed by
``/media/<article-ulid>/<content-hash>`` and the store-relative blob path is derived inside the seam.
"""

from django.urls import path

from bundesarchiv.app.web.browse_views import (
    article_detail_stub,
    serve_catalog_form_js,
    serve_components_css,
    serve_forms_css,
    serve_htmx,
    serve_layouts_css,
    serve_ledger_pane_js,
    serve_tokens,
    workbench,
)
from bundesarchiv.app.web.catalog_views import (
    article_copy,
    article_create,
    article_datierung_echo,
    article_delete,
    article_dokumenttypen,
    article_edit,
    article_lifecycle,
    article_medien_entfernen,
    article_medien_hochladen,
    article_medien_verschieben,
    article_vorschau,
)
from bundesarchiv.app.web.media_views import serve_media, serve_thumbnail

#: ``<str:...>`` (not a stricter converter): the view validates the ulid via ``is_valid_ulid`` and
#: the hash shape itself, mapping any malformed value to the SAME byte-identical 404 — a route-level
#: converter that 404'd on shape would be a distinguishable failure mode (a different 404 body), so
#: validation stays in the view where every reject collapses to one shape.
#:
#: ``artikel-neu`` is registered BEFORE ``artikel-detail`` so the literal ``neu`` path wins over the
#: ``<str:ulid>`` capture (``neu`` is not a valid ULID anyway, but ordering makes intent explicit).
urlpatterns = [
    path("", workbench, name="workbench"),
    path("static/htmx.min.js", serve_htmx, name="static-htmx"),
    path("static/ledger_pane.js", serve_ledger_pane_js, name="static-ledger-pane"),
    path("static/catalog_form.js", serve_catalog_form_js, name="static-catalog-form"),
    path("static/tokens.css", serve_tokens, name="static-tokens"),
    path("static/components.css", serve_components_css, name="static-components"),
    path("static/layouts.css", serve_layouts_css, name="static-layouts"),
    path("static/forms.css", serve_forms_css, name="static-forms"),
    path("artikel/neu", article_create, name="artikel-neu"),
    path("artikel/<str:ulid>/bearbeiten", article_edit, name="artikel-bearbeiten"),
    path("artikel/<str:ulid>/kopieren", article_copy, name="artikel-kopieren"),
    path("artikel/<str:ulid>/loeschen", article_delete, name="artikel-loeschen"),
    path("artikel/<str:ulid>/lebenszyklus", article_lifecycle, name="artikel-lebenszyklus"),
    path("artikel/<str:ulid>/vorschau", article_vorschau, name="artikel-vorschau"),
    path(
        "artikel/<str:ulid>/medien/verschieben",
        article_medien_verschieben,
        name="artikel-medien-verschieben",
    ),
    path(
        "artikel/<str:ulid>/medien/entfernen",
        article_medien_entfernen,
        name="artikel-medien-entfernen",
    ),
    path(
        "artikel/<str:ulid>/medien/hochladen",
        article_medien_hochladen,
        name="artikel-medien-hochladen",
    ),
    path("artikel/<str:ulid>/dokumenttypen", article_dokumenttypen, name="artikel-dokumenttypen"),
    path(
        "artikel/<str:ulid>/datierung-echo", article_datierung_echo, name="artikel-datierung-echo"
    ),
    path("artikel/<str:ulid>", article_detail_stub, name="artikel-detail"),
    path("media/<str:ulid>/<str:content_hash>", serve_media, name="media"),
    path("media/<str:ulid>/<str:content_hash>/thumb", serve_thumbnail, name="media-thumb"),
]
