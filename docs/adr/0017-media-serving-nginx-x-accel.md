# Media bytes: nginx X-Accel sidecar; thumbnails from Django; the mirror never serves users

Original media blobs are served through an **nginx sidecar via
`X-Accel-Redirect`**: Django runs the full authorization gate per request
(`media_views._authorize` — viewer, tier, chain, hash-on-article, every
failure the byte-identical 404), then answers with an empty body and an
`X-Accel-Redirect` header; nginx serves the file from an `internal;` location
over the canonical media tree. The seam already exists
(`media.media_response`, `BUNDESARCHIV_X_ACCEL_PREFIX`); this ADR ratifies it
as *the* prod path:

**nginx (media offload) → gunicorn → Django** — TLS termination and routing
in front of nginx are deployment details outside this decision.

Why bytes must not stream through Django: a slow client holds its gunicorn
thread for the whole download — a handful of visitors on slow links pulling
multi-hundred-MB videos would starve the app — and Django's `FileResponse`
never answers HTTP Range requests, so video seeking re-downloads the entire
file. nginx isolates slow clients, does zero-copy sendfile, and serves
Range/206 natively. Authorization stays entirely in Django, per request; the
`internal;` location is unreachable except via the app's redirect header, so
the byte-identical-404 law is untouched.

**Thumbnails keep streaming from Django** (`media.thumbnail_response`): tiny
WebP files from a local derived cache, gated identically to originals (a
thumbnail leaks the image). Small files fit in socket buffers — no
slow-client problem — and gallery pages are thumbnail-heavy, so the win is
caching, not offload: thumbnail (and media) URLs are content-hash-keyed, same
hash = same bytes forever, so responses carry
`Cache-Control: private, max-age=31536000, immutable`. `private` keeps
shared caches (proxies, CDNs) from storing gated content; a browser that
cached a thumbnail was authorized when it fetched it.

The **WebDAV/Nextcloud mirror never serves users**: it is an async one-way
copy for human browsing (ADR 0002, 0005) — it lags fresh uploads, its share
model cannot express the tier gate, and serving from it would make a
deliberately non-load-bearing component load-bearing.

## Considered options

- **Stream media from Django (async views / uvicorn)**: rejected — async
  fixes thread-pinning only under a full ASGI switch, and does not add Range
  support; the wrong bytes served concurrently are still the wrong bytes.
- **Proxy-level auth subrequest (ForwardAuth / `auth_request`) + a separate
  file server**: rejected — a routing proxy cannot serve files itself, so a
  file server is needed regardless, plus a new Django auth endpoint plus
  404-parity work in the proxy. Strictly more moving parts than the X-Accel
  seam already in the code.
- **Direct WebDAV links to the mirror**: rejected — async mirror lag, no tier
  gate, permanent-capability share links, and a new hard availability
  dependency.

## Consequences

- nginx is in the stack, but only as a ~20-line media sidecar (`internal;`
  location + `proxy_pass` to gunicorn). Static assets deliberately stay with
  WhiteNoise (ADR 0016).
- Dev keeps the direct `FileResponse` path (prefix unset) — no Range in dev,
  documented and accepted in `media.media_response`.
- **Tiering door**: when the archive outgrows the app host's disk, the
  X-Accel target for cold blobs becomes an `internal;` `proxy_pass` location
  pointing at the WebDAV mirror with service credentials — nginx streams and
  passes Range through, Django code unchanged. Trigger: archive size
  approaching local disk, not before.
