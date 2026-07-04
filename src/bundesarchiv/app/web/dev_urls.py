"""Dev-only URLconf — mounted ONLY by ``settings_dev.ROOT_URLCONF`` (Part 4.4).

Production settings define no ``ROOT_URLCONF`` at all, so this module (and the switcher route it
exposes) is unreachable in production by absence, not by a flag. It carries exactly one route: the
dev viewer switcher.
"""

from django.urls import path

from bundesarchiv.app.web.dev import switch_viewer

# ``SWITCHER_PATH`` is "/_dev/viewer/"; the URLconf pattern is the same without the leading slash.
urlpatterns = [
    path("_dev/viewer/", switch_viewer, name="dev-switch-viewer"),
]
