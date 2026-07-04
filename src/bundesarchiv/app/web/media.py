"""The media-serving seam (Part 4.3) — ``media_response`` + the byte-identical 404.

THE POINT OF THIS MODULE: it is the SINGLE place in the whole system that knows media
bytes live on the local filesystem. Every media/thumbnail byte reaches a browser through
``media_response`` and nowhere else, and ``media_response`` is called ONLY after the caller
(the view) has already run ``can_view`` on the resolved Collection chain. Authorization is
not this module's job; serving-once-authorized is (roadmap "Media authorization: critical").

Tiering door (roadmap Part 7): X-Accel-from-local-path is an IMPLEMENTATION DETAIL confined
to this one function. When media tiering lands (Nextcloud cold storage + a size-capped local
read-through cache behind a ``TieredObjectStore``), the miss-path — blob not resident locally
→ stream/Range-proxy from cold storage — grows HERE, behind this same signature. No caller
changes; no second place learns where bytes live. That is why the seam exists (roadmap: "the
port is the openness").

Denial is NEVER expressed here — the view owns 404s (see ``_not_found``). This function is
only ever reached for an authorized (article, media_ref) pair; if the blob is unexpectedly
absent on disk it raises, which the view turns into the same byte-identical 404 (a
not-yet-mirrored / pruned-thumbnail blob is indistinguishable from a forbidden one).
"""

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.utils.http import content_disposition_header

from bundesarchiv.domain.models import Article, MediaRef

#: Store-relative key scheme for an Article's media blob — mirrors ``repository._media_key``.
#: Kept here (not imported) so the seam owns its own store-relative → wire mapping; the two are
#: pinned equal by ``test_media_key_matches_repository`` so a repo layout change can't drift silently.
_MEDIA_KEY = "articles/{ulid}/media/{content_hash}"

#: Default MIME when a MediaRef carries no media_type — the safe generic (never text/html, which a
#: browser would render, so a mislabelled blob can never become a stored-XSS vector).
_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def blob_key(ulid: str, content_hash: str) -> str:
    """The store-relative blob path for one media reference (``articles/<ulid>/media/<hash>``).

    The ONE mapping from (ulid, hash) to a storage key used both by the X-Accel redirect target
    and the dev filesystem read — so there is exactly one notion of *where the bytes are*."""
    return _MEDIA_KEY.format(ulid=ulid, content_hash=content_hash)


def media_response(article: Article, media_ref: MediaRef, request: HttpRequest) -> HttpResponseBase:
    """Serve the bytes of ``media_ref`` (belonging to ``article``) — called ONLY after
    authorization has passed for the resolved chain (the view's job, never re-checked here).

    Two modes, chosen by ``settings.BUNDESARCHIV_X_ACCEL_PREFIX``:

    - **Prod / nginx** (prefix set): returns an EMPTY-body response carrying an ``X-Accel-Redirect``
      header pointing at ``<prefix>/<store-relative blob path>``. nginx (with an ``internal;``
      location over the media tree) serves the file and, crucially, handles HTTP Range requests
      itself — so byte-range/streaming is delegated to nginx, not Django. Content-Type comes from
      the MediaRef; Content-Disposition is ``inline`` with the original filename.

    - **Dev / no nginx** (prefix unset): streams the blob directly from the local canonical store
      via ``FileResponse``. Range is NOT supported in this path — a dev ``FileResponse`` without an
      explicit Range handler ignores the ``Range`` header and returns the whole body (200). That is
      ACCEPTED for dev (roadmap: Range is a prod/nginx concern; the seam keeps the door open for the
      Part 7 proxy miss-path). Do not rely on Range in dev.

    The blob location is derived HERE and NOWHERE ELSE (the tiering door). A missing blob raises
    (``FileNotFoundError`` in dev; prod hands the path to nginx which 404s internally) — the view
    treats absence as the same byte-identical 404 as a denial, so existence never leaks.
    """
    key = blob_key(article.ulid, media_ref.content_hash)
    content_type = media_ref.media_type or _DEFAULT_CONTENT_TYPE
    prefix = getattr(settings, "BUNDESARCHIV_X_ACCEL_PREFIX", None)
    if prefix:
        return _x_accel(prefix, key, content_type, media_ref.filename)
    return _dev_stream(key, content_type, media_ref.filename)


def thumbnail_response(
    article: Article, media_ref: MediaRef, request: HttpRequest
) -> HttpResponseBase:
    """Serve the WebP thumbnail derived from ``media_ref``'s blob — same authorization contract as
    ``media_response`` (a thumbnail leaks the image, so it is gated identically). The thumbnail is a
    LOCAL derived cache keyed by content-hash (``BUNDESARCHIV_THUMBNAIL_ROOT/<hash>.webp``): not
    canonical, not the ObjectStore, prunable. A not-yet-generated thumbnail raises absence, which
    the view turns into the same byte-identical 404 (indistinguishable from a forbidden one).

    Served straight from the local thumbnail cache: no X-Accel path (the thumbnail root is not the
    canonical media tree nginx fronts, and thumbnails are tiny — dev-style streaming is fine in prod
    too). Range is not supported (thumbnails are small; same dev-FileResponse caveat as above)."""
    path = thumbnail_path(media_ref.content_hash)
    return FileResponse(
        path.open("rb"),
        content_type="image/webp",
        as_attachment=False,
        filename=f"{media_ref.content_hash}.webp",
    )


def thumbnail_path(content_hash: str) -> Path:
    """The local derived-cache path for one blob's thumbnail (``THUMBNAIL_ROOT/<hash>.webp``).

    Derived, prunable, NOT backed up, NOT mirrored, NOT the ObjectStore (README runbook)."""
    return Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT) / f"{content_hash}.webp"


def _x_accel(prefix: str, key: str, content_type: str, filename: str) -> HttpResponse:
    """Prod path: hand the file to nginx via ``X-Accel-Redirect`` over an ``internal;`` location.
    Empty body — nginx replaces it with the file bytes (and serves Range itself). The filename is
    encoded through Django's ``content_disposition_header`` (RFC 5987), so a hostile upload filename
    (quotes/newlines) cannot inject a response header."""
    response = HttpResponse(b"", content_type=content_type)
    response["X-Accel-Redirect"] = f"{prefix.rstrip('/')}/{key}"
    disposition = content_disposition_header(as_attachment=False, filename=filename)
    if disposition is not None:
        response["Content-Disposition"] = disposition
    return response


def _dev_stream(key: str, content_type: str, filename: str) -> FileResponse:
    """Dev path: stream the blob straight off the local canonical store. Raises
    ``FileNotFoundError`` if the blob is absent — the view maps that to the shared 404. ``filename``
    is passed to ``FileResponse``, which safely encodes the inline Content-Disposition."""
    path = Path(settings.BUNDESARCHIV_CANONICAL_ROOT).joinpath(*key.split("/"))
    return FileResponse(
        path.open("rb"), content_type=content_type, as_attachment=False, filename=filename
    )
