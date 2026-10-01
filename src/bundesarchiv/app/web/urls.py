"""Production ROOT_URLCONF (Part 4.3) — the prod-minimal HTTP surface.

Production settings set ``ROOT_URLCONF = "bundesarchiv.app.web.urls"``: the app's whole HTTP
surface. ``settings_dev`` composes this module WITH the dev viewer switcher (see ``dev_urls``), so
dev gets both.

The public URL namespace never encodes filesystem paths (plan §4.3): media is addressed by
``/media/<article-ulid>/<content-hash>`` and the store-relative blob path is derived inside the seam.
"""

from django.urls import URLPattern, path

from bundesarchiv.app.web.auth_views import login, logout, oidc_callback
from bundesarchiv.app.web.browse_views import article_detail, choose_columns, trash, workbench
from bundesarchiv.app.web.bulk_views import article_bulk_edit, bulk_dokumenttypen
from bundesarchiv.app.web.catalog_views import (
    article_copy,
    article_create,
    article_delete,
    article_delete_permanently,
    article_dokumenttypen,
    article_edit,
    article_medien_entfernen,
    article_medien_hochladen,
    article_medien_verschieben,
    article_publish,
    article_restore,
    tag_suggestions,
    upload_gate,
)
from bundesarchiv.app.web.collection_views import collection_create, collection_edit
from bundesarchiv.app.web.media_views import page_not_found, serve_media, serve_thumbnail

handler404 = page_not_found

#: ``<str:...>`` (not a stricter converter): the view validates the ulid via ``is_valid_ulid`` and
#: the hash shape itself, mapping any malformed value to the SAME plain 404 — a route-level
#: converter that 404'd on shape would be a distinguishable failure mode (a different 404 body), so
#: validation stays in the view where every reject collapses to one shape.
#:
#: ``artikel-neu`` is registered BEFORE ``artikel-detail`` so the literal ``new`` path wins over the
#: ``<str:ulid>`` capture (``new`` is not a valid ULID anyway, but ordering makes intent explicit).
urlpatterns = [
    path("", workbench, name="workbench"),
    path("columns", choose_columns, name="spalten"),
    path("trash", trash, name="trash"),
    # The login surface (ADR 0018). English paths: these are protocol endpoints, not UI — the
    # callback path is registered in the realm client, and /login is what the anonymous gate points
    # at. They are the routes the gate exempts, so they must stay reachable to an anonymous visitor.
    path("login", login, name="login"),
    path("oidc/callback", oidc_callback, name="oidc-callback"),
    path("logout", logout, name="logout"),
    # /static/* is served by WhiteNoise middleware (ADR 0016), not the urlconf — hence no route here.
    path("articles/new", article_create, name="artikel-neu"),
    path("collections/new", collection_create, name="bestand-neu"),
    path("collections/<str:ulid>/edit", collection_edit, name="bestand-bearbeiten"),
    path(
        "articles/bulk-edit/document-types",
        bulk_dokumenttypen,
        name="artikel-sammelbearbeitung-dokumenttypen",
    ),
    path("articles/bulk-edit", article_bulk_edit, name="artikel-sammelbearbeitung"),
    path("articles/<str:ulid>/edit", article_edit, name="artikel-bearbeiten"),
    path("articles/<str:ulid>/copy", article_copy, name="artikel-kopieren"),
    path("articles/<str:ulid>/delete", article_delete, name="artikel-loeschen"),
    # English paths: owner-interview-2026-08.md, "Ruling of 2026-10-01 (URLs)".
    path(
        "articles/<str:ulid>/delete-permanently",
        article_delete_permanently,
        name="article-delete-permanently",
    ),
    path("articles/<str:ulid>/restore", article_restore, name="article-restore"),
    path("articles/<str:ulid>/publish", article_publish, name="artikel-veroeffentlichen"),
    path(
        "articles/<str:ulid>/media/move",
        article_medien_verschieben,
        name="artikel-medien-verschieben",
    ),
    path(
        "articles/<str:ulid>/media/remove",
        article_medien_entfernen,
        name="artikel-medien-entfernen",
    ),
    path(
        "articles/<str:ulid>/media/upload",
        article_medien_hochladen,
        name="artikel-medien-hochladen",
    ),
    path("upload-gate/<str:ulid>", upload_gate, name="upload-gate"),
    path("articles/<str:ulid>/document-types", article_dokumenttypen, name="artikel-dokumenttypen"),
    path("tags/suggestions", tag_suggestions, name="tag-suggestions"),
    path("articles/<str:ulid>", article_detail, name="artikel-detail"),
    path("media/<str:ulid>/<str:content_hash>", serve_media, name="media"),
    path("media/<str:ulid>/<str:content_hash>/thumb", serve_thumbnail, name="media-thumb"),
]


#: The German paths of before 2026-10-01 stay as ALIASES (owner-interview-2026-08.md, "Ruling of
#: 2026-10-01 (URLs)"): each serves the same view as its English path. Segment by segment; a ULID
#: never collides with a word here.
_OLD_SEGMENTS = {
    "articles": "artikel",
    "collections": "bestand",
    "columns": "spalten",
    "new": "neu",
    "edit": "bearbeiten",
    "copy": "kopieren",
    "delete": "loeschen",
    "publish": "veroeffentlichen",
    "document-types": "dokumenttypen",
    "media": "medien",
    "move": "verschieben",
    "remove": "entfernen",
    "upload": "hochladen",
    "bulk-edit": "sammelbearbeitung",
}


def _alias(route: URLPattern) -> URLPattern:
    """The old German path of ``route``, under the distinct name ``alias-<name>``. Names are the
    reverse() key (templates and ``redirect_to`` use them), so the aliases must not share them:
    Django's ``reverse`` tries the LAST-registered pattern of a shared name first, which would hand
    out the German path. Distinct names make the English path the only one ``reverse`` can yield."""
    old = "/".join(_OLD_SEGMENTS.get(part, part) for part in str(route.pattern).split("/"))
    return path(old, route.callback, name=f"alias-{route.name}")


# Registered after every English route and in their order, so ``artikel/neu`` keeps winning over
# ``artikel/<ulid>``. Only the three renamed trees have aliases (``media/`` and ``trash`` did not move).
urlpatterns += [
    _alias(route)
    for route in urlpatterns
    if isinstance(route, URLPattern)
    and str(route.pattern).split("/")[0] in ("articles", "collections", "columns")
]
