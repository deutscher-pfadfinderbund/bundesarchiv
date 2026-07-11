"""Media serving views (Part 4.3) — the authorized entry points for media/thumbnail bytes.

The classic direct-media leak (bytes served without the resolver) is closed HERE: every media
byte enters through one of these views, which resolve the viewer, authorize against the resolved
Collection chain via ``can_view``, and ONLY THEN hand off to ``media.media_response`` /
``media.thumbnail_response``. There is no other route to a media byte (roadmap: "the media tree is
never web-root reachable").

Denial semantics (BINDING, plan §4.3):

- Everything that is not a served byte is a **byte-identical 404** via ``_not_found()``: no such
  article, no such blob on the article, not permitted, malformed ulid, malformed hash, missing
  thumbnail — all the SAME status, body and header set. Existence never leaks; a forbidden article
  is indistinguishable from a nonexistent one, and a not-yet-thumbnailed image from a forbidden one.
- **Authorization runs and denies BEFORE any blob-existence lookup.** The blob/thumbnail is only
  ever touched inside the seam, which is reached only after ``can_view`` passed — so a denied
  request never probes the filesystem (no timing/metadata oracle). The one existence check that
  DOES gate a 404 is purely in-memory: the hash must belong to the article's ``media`` list (a valid
  hash on the WRONG article → 404).

This is a bytes-or-404 endpoint: it NEVER calls the domain ``project()`` and never emits Article
fields. Nothing but blob bytes (or an empty 404) leaves.
"""

from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase

from bundesarchiv.app.web import media
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.access import can_view
from bundesarchiv.domain.collections import resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Article, Collection, MediaRef, Ulid
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

#: A content_hash is a sha256 hex digest: exactly 64 lowercase hex characters. Anything else is
#: malformed → the same 404 (a route param that can't name a blob must not be distinguishable from
#: a param that names a forbidden one).
_HASH_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


def media_url(ulid: str, content_hash: str) -> str:
    """The public wire URL of a blob: ``/media/<ulid>/<content_hash>`` (the ``media`` route). The ONE
    builder for this shape — the detail view, the preview pane, and the edit-form media manager all
    call it, so the URL layout has a single home (it is earmarked to change with the Part 7 tiering
    work). Distinct from ``media.blob_key`` — that builds the store-relative blob key, not the URL."""
    return f"/media/{ulid}/{content_hash}"


def thumbnail_url(ulid: str, content_hash: str) -> str:
    """The public wire URL of a blob's thumbnail: ``/media/<ulid>/<content_hash>/thumb`` (the
    ``media-thumb`` route). Same single-source rule as :func:`media_url`."""
    return f"{media_url(ulid, content_hash)}/thumb"


def _canonical_store() -> ObjectStore:
    """The canonical files-store the views read from (ADR 0005). Built per request from settings —
    the same construction as the worker's ``canonical_store``. Monkeypatched in tests."""
    return LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))


def _is_valid_hash(value: str) -> bool:
    """True iff ``value`` is a well-formed sha256 content hash (64 lowercase hex chars). Total: a
    malformed route param yields False, never an exception — it floors to the shared 404."""
    return len(value) == _HASH_LENGTH and all(ch in _HEX_DIGITS for ch in value)


def _not_found() -> HttpResponse:
    """THE single 404 every denial/absence path returns — byte-identical by construction.

    One constant shape: status 404, an empty body, and NO Content-Type/Content-Length divergence
    (Django would otherwise stamp a default ``text/html`` Content-Type; we pin an empty content_type
    so the header set is constant regardless of which reason produced the 404). A caller can learn
    NOTHING from a 404 — not whether the article exists, the blob exists, the viewer lacks
    permission, or a param was malformed. That indistinguishability is the existence-hiding invariant
    (plan §4.3: same body, same headers, constant shape)."""
    return HttpResponse(b"", status=404, content_type="")


def _authorize(
    request: HttpRequest, ulid: str, content_hash: str
) -> tuple[Article, MediaRef] | None:
    """The shared gate for both views: validate params, resolve the viewer, load + authorize the
    article, and locate the referenced media — returning ``(article, media_ref)`` ONLY if every
    check passes, else ``None`` (the caller returns ``_not_found()``).

    Order is load-bearing: authorization runs to a decision BEFORE any blob-existence lookup (the
    blob is never touched here — only the in-memory Article and its media list are). A malformed
    param, a missing article, a broken chain, a denied viewer, or a hash not on THIS article all
    collapse to ``None`` with no filesystem probe of the blob."""
    if not is_valid_ulid(ulid) or not _is_valid_hash(content_hash):
        return None  # malformed route param → the same 404, before any lookup
    store = _canonical_store()
    try:
        article = ArticleRepository(store).load(ulid).article
    except ArchiveError:
        return None  # no such article (or an unreadable one) → 404 (existence-hiding)
    viewer = viewer_of(request)
    try:
        chain = resolve_chain(article.collection_id, _collections(store))
    except DomainError:
        return None  # broken/unresolvable chain → deny everyone (fail closed)
    if not can_view(viewer, article, chain):
        return None  # AUTHORIZATION denies here — before any blob-existence lookup
    media_ref = _media_ref_for(article, content_hash)
    if media_ref is None:
        return None  # a valid hash that is not on THIS article → 404 (wrong-article guard)
    return article, media_ref


def serve_media(request: HttpRequest, ulid: str, content_hash: str) -> HttpResponseBase:
    """``GET /media/<ulid>/<content_hash>`` — the original blob, authorized. Denial/absence/malformed
    → the byte-identical 404. A permitted request hands off to the ``media_response`` seam (which
    alone knows the bytes are local); if the blob is unexpectedly absent, the seam raises absence and
    we still return the SAME 404 (existence-hiding preserved past the auth gate)."""
    authorized = _authorize(request, ulid, content_hash)
    if authorized is None:
        return _not_found()
    article, media_ref = authorized
    try:
        return media.media_response(article, media_ref, request)
    except FileNotFoundError, OSError:
        return _not_found()  # blob absent on disk (not-yet-mirrored/pruned) → the same 404


def serve_thumbnail(request: HttpRequest, ulid: str, content_hash: str) -> HttpResponseBase:
    """``GET /media/<ulid>/<content_hash>/thumb`` — the WebP thumbnail, SAME authorization as the
    original (a thumbnail leaks the image). A not-yet-generated thumbnail → the same byte-identical
    404 as a forbidden one (a not-yet-thumbnailed image must be indistinguishable from a denial)."""
    authorized = _authorize(request, ulid, content_hash)
    if authorized is None:
        return _not_found()
    article, media_ref = authorized
    try:
        return media.thumbnail_response(article, media_ref, request)
    except FileNotFoundError, OSError:
        return _not_found()  # thumbnail not (yet) generated → the same 404


def _collections(store: ObjectStore) -> dict[Ulid, Collection]:
    """Every saved Collection as a ULID→Collection mapping for ``resolve_chain`` (chain resolution
    is injected the lookup, never fetches — domain purity). Read-only; no versions needed."""
    return {c.ulid: c for c in CollectionRepository(store).load_all()}


def _media_ref_for(article: Article, content_hash: str) -> MediaRef | None:
    """The ``MediaRef`` on ``article`` whose ``content_hash`` matches, or ``None`` if this article
    carries no such blob (the wrong-article / no-such-blob guard — an in-memory check, no filesystem
    probe)."""
    return next((ref for ref in article.media if ref.content_hash == content_hash), None)
