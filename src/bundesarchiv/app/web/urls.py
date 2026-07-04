"""Production ROOT_URLCONF (Part 4.3) — the prod-minimal HTTP surface.

Production settings set ``ROOT_URLCONF = "bundesarchiv.app.web.urls"`` and mount ONLY the media
routes needed to serve authorized bytes. Everything else stays prod-minimal (ADR 0004/0005: Django
is an adapter, not a web framework here). ``settings_dev`` composes this module (prod media routes)
WITH the dev viewer switcher (see ``dev_urls``), so dev gets both.

The public URL namespace never encodes filesystem paths (plan §4.3): media is addressed by
``/media/<article-ulid>/<content-hash>`` and the store-relative blob path is derived inside the seam.
"""

from django.urls import path

from bundesarchiv.app.web.media_views import serve_media, serve_thumbnail

#: ``<str:...>`` (not a stricter converter): the view validates the ulid via ``is_valid_ulid`` and
#: the hash shape itself, mapping any malformed value to the SAME byte-identical 404 — a route-level
#: converter that 404'd on shape would be a distinguishable failure mode (a different 404 body), so
#: validation stays in the view where every reject collapses to one shape.
urlpatterns = [
    path("media/<str:ulid>/<str:content_hash>", serve_media, name="media"),
    path("media/<str:ulid>/<str:content_hash>/thumb", serve_thumbnail, name="media-thumb"),
]
