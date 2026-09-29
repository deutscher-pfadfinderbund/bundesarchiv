"""The media-serving seam (Part 4.3) — ``media_response`` + ``thumbnail_response``.

THE POINT OF THIS MODULE: every media/thumbnail byte reaches a browser through one of these two
functions and nowhere else, and each is called ONLY after the caller (the view) has already run
``can_view`` on the resolved Collection chain. Authorization is not this module's job;
serving-once-authorized is (roadmap "Media authorization: critical").

Tiering door (ADR 0017): choosing between the X-Accel redirect and a direct stream is an
IMPLEMENTATION DETAIL confined to ``media_response``. When media tiering lands (Nextcloud cold
storage + a size-capped local read-through cache behind a ``TieredObjectStore``), the miss-path —
blob not resident locally → stream/Range-proxy from cold storage — grows HERE, behind this same
signature. No caller changes. Where the bytes physically live is the store's business, never this
module's: a blob is named and opened through ``ArticleRepository`` (ADR 0005). The one local path
served here is the THUMBNAIL cache, which is deliberately not the ObjectStore (derived, prunable).

Denial is NEVER expressed here — the view owns 404s (see ``media_views._not_found``). These
functions are only ever reached for an authorized (article, media_ref) pair; if the blob is
unexpectedly absent they raise, which the view turns into the same 404 (a not-yet-mirrored /
pruned-thumbnail blob is indistinguishable from a forbidden one).
"""

from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.utils.http import content_disposition_header

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import thumbnail_path
from bundesarchiv.domain.models import Article, MediaRef

#: Default MIME when a MediaRef carries no media_type — the safe generic (never text/html, which a
#: browser would render, so a mislabelled blob can never become a stored-XSS vector).
_DEFAULT_CONTENT_TYPE = "application/octet-stream"

#: ADR 0017. ``private`` is the leak-relevant half — a shared cache must never store gated bytes.
_IMMUTABLE_CACHE_CONTROL = "private, max-age=31536000, immutable"


def media_response(
    archive: Archive, article: Article, media_ref: MediaRef, request: HttpRequest
) -> HttpResponseBase:
    """Serve the bytes of ``media_ref`` (belonging to ``article``) — called ONLY after
    authorization has passed for the resolved chain (the view's job, never re-checked here).

    Two modes, chosen by ``settings.BUNDESARCHIV_X_ACCEL_PREFIX``:

    - **Prod / nginx** (prefix set): returns an EMPTY-body response carrying an ``X-Accel-Redirect``
      header pointing at ``<prefix>/<store-relative file key>``, each key segment percent-encoded
      (nginx decodes the header as a URI, ADR 0019). nginx (with an ``internal;`` location over the
      media tree) serves the file and, crucially, handles HTTP Range requests itself — so
      byte-range/streaming is delegated to nginx, not Django. The key is the wire format here, and
      the repository is its one author. Content-Type comes from the MediaRef; Content-Disposition is
      ``inline`` with the original filename.

    - **Dev / no nginx** (prefix unset): streams the blob out of the store through the port. Range
      is NOT supported in this path — a dev ``FileResponse`` without an explicit Range handler
      ignores the ``Range`` header and returns the whole body (200). That is ACCEPTED for dev (ADR
      0017); do not rely on Range in dev.

    An absent blob raises (the port's ``NotFound`` in dev; in prod the path goes to nginx, which
    404s internally) — the view treats absence as the same 404 as a denial, so existence never
    leaks.
    """
    content_type = media_ref.media_type or _DEFAULT_CONTENT_TYPE
    prefix = getattr(settings, "BUNDESARCHIV_X_ACCEL_PREFIX", None)
    if prefix:
        key = archive.articles.media_key(article.ulid, media_ref)
        response: HttpResponseBase = _x_accel(prefix, key, content_type, media_ref.filename)
    else:
        blob = archive.articles.open_media(article.ulid, media_ref)
        response = FileResponse(
            blob, content_type=content_type, as_attachment=False, filename=media_ref.filename
        )
    return _cacheable(response)


def thumbnail_response(
    article: Article, media_ref: MediaRef, request: HttpRequest
) -> HttpResponseBase:
    """Serve the WebP thumbnail derived from ``media_ref``'s blob — same authorization contract as
    ``media_response`` (a thumbnail leaks the image, so it is gated identically). The thumbnail is a
    LOCAL derived cache keyed by content-hash (``thumbnails.thumbnail_path``): not
    canonical, not the ObjectStore, prunable. A not-yet-generated thumbnail raises absence, which
    the view turns into the same 404 (indistinguishable from a forbidden one).

    Served straight from the local thumbnail cache: no X-Accel path (the thumbnail root is not the
    canonical media tree nginx fronts, and thumbnails are tiny — dev-style streaming is fine in prod
    too). Range is not supported (thumbnails are small; same dev-FileResponse caveat as above)."""
    path = thumbnail_path(Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT), media_ref.content_hash)
    return _cacheable(
        FileResponse(
            path.open("rb"),
            content_type="image/webp",
            as_attachment=False,
            filename=path.name,
        )
    )


def _cacheable(response: HttpResponseBase) -> HttpResponseBase:
    """Stamped at both public exits, not inside either serving branch, so a future third serving
    path cannot silently miss the policy."""
    response["Cache-Control"] = _IMMUTABLE_CACHE_CONTROL
    return response


def _x_accel(prefix: str, key: str, content_type: str, filename: str) -> HttpResponse:
    """Prod path: hand the file to nginx via ``X-Accel-Redirect`` over an ``internal;`` location.
    Empty body — nginx replaces it with the file bytes (and serves Range itself). The filename is
    encoded through Django's ``content_disposition_header`` (RFC 5987), so a hostile upload filename
    (quotes/newlines) cannot inject a response header.

    ADR 0017: the sidecar's ``internal;`` location must not set its own ``expires``/``Cache-Control``."""
    response = HttpResponse(b"", content_type=content_type)
    response["X-Accel-Redirect"] = f"{prefix.rstrip('/')}/{quote(key)}"
    disposition = content_disposition_header(as_attachment=False, filename=filename)
    if disposition is not None:
        response["Content-Disposition"] = disposition
    return response
