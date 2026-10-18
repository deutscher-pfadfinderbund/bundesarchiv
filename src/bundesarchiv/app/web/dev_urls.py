"""Dev URLconf (``settings_dev.ROOT_URLCONF``): the production ``urls`` plus the dev-only routes,
which production lacks because it never loads this module."""

from collections.abc import Collection, Mapping
from typing import cast

from django.conf import settings
from django.urls import include, path
from django.utils.csp import CSP
from django.views.decorators.csp import csp_override

from bundesarchiv.app.web.components_demo import component_library
from bundesarchiv.app.web.dev import authorize, favicon
from bundesarchiv.app.web.layouts_demo import layout_demo
from bundesarchiv.app.web.media_views import page_not_found

handler404 = page_not_found

# The two demo pages carry their own <style> and style="" attributes; every other dev page keeps the
# production policy, so the browser suites catch an inline style there.
# The cast: django-stubs types the setting as dict[str, object].
_PAGE_POLICY = cast("Mapping[str, Collection[str] | str]", settings.SECURE_CSP)
_demo_csp = csp_override({**_PAGE_POLICY, "style-src": [CSP.SELF, CSP.UNSAFE_INLINE]})

urlpatterns = [
    path("", include("bundesarchiv.app.web.urls")),
    path("favicon.ico", favicon, name="dev-favicon"),
    path("_dev/viewer/", authorize, name="dev-switch-viewer"),
    path("_dev/components/", _demo_csp(component_library), name="dev-components"),
    path("_dev/layouts/split-narrow/", _demo_csp(layout_demo), name="dev-layout"),
]
