"""Dev URLconf — mounted ONLY by ``settings_dev.ROOT_URLCONF`` (Part 4.4 + 4.3).

It COMPOSES the production HTTP surface (``bundesarchiv.app.web.urls`` — the authorized media
routes) WITH the dev-only viewer switcher, so a dev process gets both. Production settings point
``ROOT_URLCONF`` at ``bundesarchiv.app.web.urls`` directly (the media routes, no switcher), so the
switcher route this module adds is unreachable in production by absence, not by a flag.
"""

from django.urls import include, path

from bundesarchiv.app.web.components_demo import component_library, serve_variant_stylesheet
from bundesarchiv.app.web.dev import favicon, switch_viewer
from bundesarchiv.app.web.layouts_demo import layout_demo, serve_layout_stylesheet

# Prod routes first (included verbatim), then the dev-only routes: an explicit /favicon.ico -> 404
# (the browser probes for it; without a route DEBUG's technical-404 page crashes on the empty dev
# SECRET_KEY and surfaces as a 500 — see dev.favicon), the viewer switcher (dev.py reverses this
# pattern by name — "dev-switch-viewer" — rather than hardcoding the path), the component library
# (baseline + whitelisted design variants), the layout demos (whitelisted full workbench layouts),
# and the two dev-only stylesheet routes — all unreachable in prod by absence of this URLconf.
urlpatterns = [
    path("", include("bundesarchiv.app.web.urls")),
    path("favicon.ico", favicon, name="dev-favicon"),
    path("_dev/viewer/", switch_viewer, name="dev-switch-viewer"),
    path("_dev/components/", component_library, name="dev-components"),
    path("_dev/components/<str:variant>/", component_library, name="dev-components-variant"),
    path("_dev/layouts/<str:name>/", layout_demo, name="dev-layout"),
    path("_dev/static/<str:filename>", serve_variant_stylesheet, name="dev-variant-css"),
    path("_dev/layouts/static/<str:filename>", serve_layout_stylesheet, name="dev-layout-css"),
]
