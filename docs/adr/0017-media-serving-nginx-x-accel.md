# Media bytes: nginx X-Accel sidecar; thumbnails from Django; the mirror never serves users

Original media blobs are served through an **nginx sidecar via
`X-Accel-Redirect`**: Django runs the full authorization gate per request
(`media_views._authorize` — viewer, tier, chain, hash-on-article, every
failure the same revealing-nothing 404), then answers with an empty body and an
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
the deny contract is untouched (a 404 revealing nothing — the byte-identical
form of that law was relaxed by the owner in 2026-08).

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

- nginx is in the stack as a small sidecar: `proxy_pass` to gunicorn, the
  `internal;` media location, and the upload gate below. Static assets
  deliberately stay with WhiteNoise (ADR 0016).
- **The internal location serves only what the app names.** It matches the key
  shape `articles/<ulid>/media/<name>` (ADR 0019) with no leading dot in the
  name, and follows no symlink. A README, a history file or a planted symlink is
  refused even if a bug named it.
- **Media runs no script and stays on this site.** An uploaded SVG or HTML file
  opened directly is a document on the archive's origin. Every media and
  thumbnail response carries `Content-Security-Policy: sandbox` and
  `X-Content-Type-Options: nosniff`, so the file displays but runs no script and
  gets an opaque origin. It also carries `Cross-Origin-Resource-Policy:
  same-origin`: pages on sibling DPB hosts are same-site, so their requests carry
  the login cookies, and without it such a page could learn whether its visitor
  may see a record. On an X-Accel redirect nginx keeps only a few of the app's
  headers (`Cache-Control` among them) and drops these three, so the `internal;`
  location adds them with `add_header … always`.
- **The sidecar must not set its own cache headers.** nginx keeps the app's
  `Cache-Control` on an X-Accel redirect, so an `expires` or
  `add_header Cache-Control` in the `internal;` location would override the
  `private` policy Django stamps and let a shared cache store gated bytes. The
  app applies the header at the seam's public exits (`media.media_response`,
  `media.thumbnail_response`).
- **An upload is authorized before nginx reads its body.** nginx buffers request
  bodies to disk (owner, 2026-09-24, ADR 0020), so an ungated upload route would
  let anyone fill the disk. Only the upload route takes a large body. On it, an
  `auth_request` asks `GET /upload-gate/<ulid>`, which runs the upload view's own
  gate and answers 204 exactly when the upload would be taken. Everyone else,
  anonymous included, gets the plain empty 404 from nginx, and the body is
  discarded, never stored. The gate also admits only a same-origin request
  (`Sec-Fetch-Site`, else `Origin`, else `Referer`, the order Django's CSRF check
  falls back in): a page on a sibling DPB host is same-site, so its post carries
  an Archivist's cookies, and Django's CSRF check would refuse it only after the
  body is on disk. Every other route takes at most 4 MiB, just above
  Django's own cap on a body without files. This is `auth_request` for uploads
  only; media keeps the X-Accel seam (see "Considered options").
- Dev keeps the direct `FileResponse` path (prefix unset) — no Range in dev,
  documented and accepted in `media.media_response`.
- **Tiering door**: when the archive outgrows the app host's disk, the
  X-Accel target for cold blobs becomes an `internal;` `proxy_pass` location
  pointing at the WebDAV mirror with service credentials — nginx streams and
  passes Range through, Django code unchanged. Trigger: archive size
  approaching local disk, not before.
