"""Dev URLconf — mounted ONLY by ``settings_dev.ROOT_URLCONF`` (Part 4.4 + 4.3).

It COMPOSES the production HTTP surface (``bundesarchiv.app.web.urls`` — the authorized media
routes) WITH the dev-only viewer switcher, so a dev process gets both. Production settings point
``ROOT_URLCONF`` at ``bundesarchiv.app.web.urls`` directly (the media routes, no switcher), so the
switcher route this module adds is unreachable in production by absence, not by a flag.
"""

from collections.abc import Collection, Mapping
from typing import cast

from django.conf import settings
from django.urls import include, path
from django.utils.csp import CSP
from django.views.decorators.csp import csp_override

from bundesarchiv.app.web.components_demo import component_library
from bundesarchiv.app.web.dev import favicon, switch_viewer
from bundesarchiv.app.web.layouts_demo import layout_demo
from bundesarchiv.app.web.media_views import page_not_found

handler404 = page_not_found

# The two demo pages carry their own <style> and style="" attributes; every other dev page keeps the
# production policy, so the browser suites catch an inline style there.
# The cast: django-stubs types the setting as dict[str, object].
_PAGE_POLICY = cast("Mapping[str, Collection[str] | str]", settings.SECURE_CSP)
_demo_csp = csp_override({**_PAGE_POLICY, "style-src": [CSP.SELF, CSP.UNSAFE_INLINE]})

# Prod routes first (included verbatim), then the dev-only routes: an explicit /favicon.ico -> 404
# (the browser probes for it; without a route DEBUG's technical-404 page crashes on the empty dev
# SECRET_KEY and surfaces as a 500 — see dev.favicon), the viewer switcher (reversed by name in
# dev.py), the component library (the ONE baseline — the variant toggle died with the papier cut,
# owner 2026-08-06) and the layout demo (the full workbench layout) — all unreachable in prod by
# absence of this URLconf.
urlpatterns = [
    path("", include("bundesarchiv.app.web.urls")),
    path("favicon.ico", favicon, name="dev-favicon"),
    path("_dev/viewer/", switch_viewer, name="dev-switch-viewer"),
    path("_dev/components/", _demo_csp(component_library), name="dev-components"),
    path("_dev/layouts/split-narrow/", _demo_csp(layout_demo), name="dev-layout"),
]
