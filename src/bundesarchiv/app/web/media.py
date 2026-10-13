"""Serving already-authorized media bytes — the only path a media byte takes to a browser. Callers
authorize first and own every 404; where bytes live is the store's business (ADR 0017, ADR 0005)."""

from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.utils.http import content_disposition_header

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import Size, cached
from bundesarchiv.domain.models import Article, MediaRef

#: Default MIME when a MediaRef carries no media_type — the safe generic (never text/html, which a
#: browser would render, so a mislabelled blob can never become a stored-XSS vector).
_DEFAULT_CONTENT_TYPE = "application/octet-stream"

#: ADR 0017. ``private`` is the leak-relevant half — a shared cache must never store gated bytes.
_IMMUTABLE_CACHE_CONTROL = "private, max-age=31536000, immutable"

#: ADR 0017. An uploaded SVG or HTML file opened directly is a document on the archive's origin;
#: the sandbox runs no script in it and gives it an opaque origin.
_SANDBOX_CSP = "sandbox"

#: ADR 0017.
_SAME_ORIGIN_ONLY = "same-origin"


def media_response(
    archive: Archive, article: Article, media_ref: MediaRef, request: HttpRequest
) -> HttpResponseBase:
    """An X-Accel handoff to nginx (which serves Range) when ``BUNDESARCHIV_X_ACCEL_PREFIX`` is
    set, else a stream without Range (dev, ADR 0017) that raises for an absent blob."""
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
    return _stamped(response)


def thumbnail_response(
    archive: Archive, article: Article, media_ref: MediaRef, size: Size
) -> HttpResponseBase:
    """Streamed, not X-Accel: nginx's X-Accel location fronts only the canonical media tree."""
    root = Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
    path = cached(archive.articles, article.ulid, media_ref, root, size)
    if path is None:
        raise FileNotFoundError(media_ref.content_hash)
    return _stamped(
        FileResponse(
            path.open("rb"),
            content_type="image/avif",
            as_attachment=False,
            filename=path.name,
        )
    )


def _stamped(response: HttpResponseBase) -> HttpResponseBase:
    """Stamped at both public exits, not inside either serving branch, so a future third serving
    path cannot silently miss the policy."""
    response["Cache-Control"] = _IMMUTABLE_CACHE_CONTROL
    response["Content-Security-Policy"] = _SANDBOX_CSP
    response["Cross-Origin-Resource-Policy"] = _SAME_ORIGIN_ONLY
    return response


def _x_accel(prefix: str, key: str, content_type: str, filename: str) -> HttpResponse:
    """``key`` is percent-encoded: nginx decodes the header as a URI (ADR 0019). The filename
    goes through ``content_disposition_header``, so a hostile name cannot inject a header."""
    response = HttpResponse(b"", content_type=content_type)
    response["X-Accel-Redirect"] = f"{prefix.rstrip('/')}/{quote(key)}"
    disposition = content_disposition_header(as_attachment=False, filename=filename)
    if disposition is not None:
        response["Content-Disposition"] = disposition
    return response
