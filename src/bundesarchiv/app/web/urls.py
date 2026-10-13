"""The app's whole HTTP surface (production ROOT_URLCONF; ``dev_urls`` adds the dev routes). Media is
addressed by ulid and content hash, never by a store path."""

from django.urls import URLPattern, path

from bundesarchiv.app.thumbnails import Size
from bundesarchiv.app.web.auth_views import login, logout, oidc_callback
from bundesarchiv.app.web.browse_views import article_detail, choose_columns, trash, workbench
from bundesarchiv.app.web.bulk_views import article_bulk_edit, bulk_document_types
from bundesarchiv.app.web.catalog_views import (
    article_copy,
    article_create,
    article_delete,
    article_delete_permanently,
    article_document_types,
    article_edit,
    article_media_move,
    article_media_remove,
    article_media_upload,
    article_publish,
    article_restore,
    tag_suggestions,
    upload_gate,
)
from bundesarchiv.app.web.collection_views import collection_create, collection_edit
from bundesarchiv.app.web.media_views import page_not_found, serve_media, serve_thumbnail
from bundesarchiv.app.web.start import start

handler404 = page_not_found

#: Literal paths (``articles/new``) precede the ``<str:ulid>`` captures, which would swallow them.
urlpatterns = [
    path("", start, name="start"),
    path("articles", workbench, name="workbench"),
    path("columns", choose_columns, name="columns"),
    path("trash", trash, name="trash"),
    # ADR 0018. The callback path is registered in the realm client: renaming it breaks login.
    path("login", login, name="login"),
    path("oidc/callback", oidc_callback, name="oidc-callback"),
    path("logout", logout, name="logout"),
    # /static/* is served by WhiteNoise middleware (ADR 0016), not the urlconf — hence no route here.
    path("articles/new", article_create, name="article-create"),
    path("collections/new", collection_create, name="collection-create"),
    path("collections/<str:ulid>/edit", collection_edit, name="collection-edit"),
    path(
        "articles/bulk-edit/document-types",
        bulk_document_types,
        name="article-bulk-edit-document-types",
    ),
    path("articles/bulk-edit", article_bulk_edit, name="article-bulk-edit"),
    path("articles/<str:ulid>/edit", article_edit, name="article-edit"),
    path("articles/<str:ulid>/copy", article_copy, name="article-copy"),
    path("articles/<str:ulid>/delete", article_delete, name="article-delete"),
    path(
        "articles/<str:ulid>/delete-permanently",
        article_delete_permanently,
        name="article-delete-permanently",
    ),
    path("articles/<str:ulid>/restore", article_restore, name="article-restore"),
    path("articles/<str:ulid>/publish", article_publish, name="article-publish"),
    path(
        "articles/<str:ulid>/media/move",
        article_media_move,
        name="article-media-move",
    ),
    path(
        "articles/<str:ulid>/media/remove",
        article_media_remove,
        name="article-media-remove",
    ),
    path(
        "articles/<str:ulid>/media/upload",
        article_media_upload,
        name="article-media-upload",
    ),
    path("upload-gate/<str:ulid>", upload_gate, name="upload-gate"),
    path(
        "articles/<str:ulid>/document-types", article_document_types, name="article-document-types"
    ),
    path("tags/suggestions", tag_suggestions, name="tag-suggestions"),
    path("articles/<str:ulid>", article_detail, name="article-detail"),
    path("media/<str:ulid>/<str:content_hash>", serve_media, name="media"),
    path("media/<str:ulid>/<str:content_hash>/thumb", serve_thumbnail, name="media-thumb"),
    path(
        "media/<str:ulid>/<str:content_hash>/display",
        serve_thumbnail,
        {"size": Size.DISPLAY},
        name="media-display",
    ),
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
    """The old German path of ``route``, named ``alias-<name>``: with a shared name ``reverse`` would
    prefer the later-registered German path."""
    old = "/".join(_OLD_SEGMENTS.get(part, part) for part in str(route.pattern).split("/"))
    return path(old, route.callback, name=f"alias-{route.name}")


# Registered after every English route and in their order, so ``artikel/neu`` keeps winning over
# ``artikel/<ulid>``. Only the three renamed trees have aliases (``media/`` and ``trash`` did not move).
urlpatterns += [
    _alias(route)
    for route in urlpatterns
    if isinstance(route, URLPattern)
    and str(route.pattern).split("/")[0] in ("articles", "collections", "columns")
    and route.name != "workbench"  # the list lived at /, which stays its alias (start.start)
]
