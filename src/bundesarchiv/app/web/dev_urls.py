"""Dev URLconf — mounted ONLY by ``settings_dev.ROOT_URLCONF`` (Part 4.4 + 4.3).

It COMPOSES the production HTTP surface (``bundesarchiv.app.web.urls`` — the authorized media
routes) WITH the dev-only viewer switcher, so a dev process gets both. Production settings point
``ROOT_URLCONF`` at ``bundesarchiv.app.web.urls`` directly (the media routes, no switcher), so the
switcher route this module adds is unreachable in production by absence, not by a flag.
"""

from django.urls import include, path

from bundesarchiv.app.web.dev import switch_viewer

# Prod media routes first (included verbatim), then the dev-only switcher. ``SWITCHER_PATH`` is
# "/_dev/viewer/"; the URLconf pattern is the same without the leading slash.
urlpatterns = [
    path("", include("bundesarchiv.app.web.urls")),
    path("_dev/viewer/", switch_viewer, name="dev-switch-viewer"),
]
