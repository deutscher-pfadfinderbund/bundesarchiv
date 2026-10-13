"""Media serving views (Part 4.3) — the authorized entry points for media/thumbnail bytes.

The classic direct-media leak (bytes served without the resolver) is closed HERE: every media
byte enters through one of these views, which resolve the viewer, authorize against the resolved
Collection chain via ``can_view``, and ONLY THEN hand off to ``media.media_response`` /
``media.thumbnail_response``. There is no other route to a media byte (roadmap: "the media tree is
never web-root reachable").

Denial semantics (BINDING, plan §4.3):

- Everything that is not a served byte is a **plain 404** via ``not_found()``: no such
  article, no such blob on the article, not permitted, malformed ulid, malformed hash, a file that
  yields no version of the asked size (a PDF has no display version) — all the SAME status, body
  and header set. Existence never leaks; a forbidden article is indistinguishable from a
  nonexistent one, and an unrenderable file from a forbidden one.
- **Authorization runs and denies BEFORE any blob-existence lookup.** The blob/thumbnail is only
  ever touched inside the seam, which is reached only after ``can_view`` passed — so a denied
  request never probes the filesystem (no timing/metadata oracle) and never derives a version. The one existence check that
  DOES gate a 404 is purely in-memory: the hash must belong to the article's ``media`` list (a valid
  hash on the WRONG article → 404).

This is a bytes-or-404 endpoint: it NEVER calls the domain ``project()`` and never emits Article
fields. Nothing but blob bytes (or the constant 404 page) leaves.
"""

import logging
from functools import cache

from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.template.loader import render_to_string

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import Size
from bundesarchiv.app.web import media
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.access import can_view
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Article, MediaRef
from bundesarchiv.persistence.errors import ArchiveError

logger = logging.getLogger(__name__)

#: A content_hash is a lowercase sha256 hex digest.
_HASH_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


def _is_valid_hash(value: str) -> bool:
    return len(value) == _HASH_LENGTH and all(ch in _HEX_DIGITS for ch in value)


@cache
def _not_found_page() -> bytes:
    """The one 404 page, rendered once without a request: no viewer, path, query or CSRF token can
    reach it, so every reason and every viewer gets the same bytes."""
    return render_to_string("404.html").encode()


def not_found() -> HttpResponse:
    """The one 404 every deny and absence returns: same status, body and headers for every
    reason."""
    return HttpResponse(_not_found_page(), status=404)


def page_not_found(request: HttpRequest, exception: Exception) -> HttpResponse:
    """Django's ``handler404``: an unmatched path answers the same page as a deny."""
    return not_found()


def _authorize(
    request: HttpRequest, ulid: str, content_hash: str
) -> tuple[Archive, Article, MediaRef] | None:
    """Authorization decides before any blob is touched; the hash is matched in memory."""
    if not is_valid_ulid(ulid) or not _is_valid_hash(content_hash):
        return None
    archive = Archive.canonical()
    try:
        article = archive.articles.load(ulid).article
    except ArchiveError:
        return None
    viewer = viewer_of(request)
    chain = CollectionChooser.of(archive).chain_of(article.collection_id)
    if chain is None:
        return None
    if not can_view(viewer, article, chain):
        return None
    media_ref = _media_ref_for(article, content_hash)
    if media_ref is None:
        return None
    return archive, article, media_ref


def serve_media(request: HttpRequest, ulid: str, content_hash: str) -> HttpResponseBase:
    """``GET /media/<ulid>/<content_hash>`` — the original file."""
    authorized = _authorize(request, ulid, content_hash)
    if authorized is None:
        return not_found()
    archive, article, media_ref = authorized
    try:
        return media.media_response(archive, article, media_ref, request)
    except ArchiveError:
        return not_found()


def serve_thumbnail(
    request: HttpRequest, ulid: str, content_hash: str, size: Size = Size.TILE
) -> HttpResponseBase:
    """``GET /media/<ulid>/<content_hash>/thumb`` (the tile) and ``…/display`` (``size`` from the
    urlconf) — SAME authorization as the original (a derived version leaks the image). A missing
    version is derived on this request; a file that yields none, or a derive that fails for any
    reason → the same plain 404 as a forbidden one."""
    authorized = _authorize(request, ulid, content_hash)
    if authorized is None:
        return not_found()
    archive, article, media_ref = authorized
    try:
        return media.thumbnail_response(archive, article, media_ref, size)
    except FileNotFoundError:
        return not_found()
    except Exception:
        logger.exception("serving the %s version of %s failed", size.name, content_hash)
        return not_found()


def _media_ref_for(article: Article, content_hash: str) -> MediaRef | None:
    return next((ref for ref in article.media if ref.content_hash == content_hash), None)
