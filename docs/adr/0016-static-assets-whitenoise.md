# Static assets: WhiteNoise owns CSS/JS

CSS/JS are served by **`django.contrib.staticfiles` + WhiteNoise** with
`CompressedManifestStaticFilesStorage`: hashed filenames (`forms.a1b2c3.css`),
`Cache-Control: immutable` far-future headers, and gzip + brotli variants
precompressed once at `collectstatic` — zero per-request CPU. Templates
reference assets via `{% static %}`. WhiteNoise serves identically under
`runserver` and in prod (dev/prod parity — no proxy-only behavior to miss in
dev), and nginx (present as the media sidecar, ADR 0017) takes no static
role, so its config stays minimal.

Archive media and thumbnails are **not static assets**: every byte is
authorized per request per viewer, and every failure collapses to the
byte-identical 404 (ADR 0001, 0012). How their bytes are served is ADR 0017.

The app server is **gunicorn with `gthread` workers**, not an ASGI server:
the app is fully synchronous (no async views, no websockets; HTMX is plain
HTTP) and WhiteNoise is WSGI-native. HTML compression, if wanted, belongs at
the reverse proxy, not in Django (`GZipMiddleware` costs app CPU and carries
the BREACH caveat).

## Considered options

- **Explicit per-asset routes** (one URL + view per file): keeps the HTTP
  surface fully enumerable, so the route × tier leak matrix walks each static
  route as a named row, and needs no `collectstatic` step. Rejected: three
  touchpoints per asset, caching/fingerprinting/compression left unsolved, and
  the matrix keeps its exhaustiveness with a one-line public-by-design
  allowlist for the `/static/` prefix.
- **nginx for static files**: rejected even though nginx is in the stack as
  the media sidecar (ADR 0017) — it would break dev/prod parity, needs a
  non-default module for brotli, and small files don't have the slow-client
  problem (they fit in socket buffers); serving them from Django costs
  nothing measurable.
- **uvicorn / ASGI**: rejected for now — a synchronous Django app gains
  nothing from an async server (sync views execute through the thread-adapted
  path anyway), and WhiteNoise's fast path is WSGI. Revisit if async views or
  SSE ever appear.

## Consequences

- `/static/*` is served by WhiteNoise middleware, not the URLconf, so the
  route × tier leak matrix (which walks the URLconf) never sees it. Its
  public-by-design contract lives in its own test: a fail-loud whitelist of
  the asset set, tier-invariance of an uncollected path (no existence oracle),
  and directory-traversal containment. The byte-identical-404 law is untouched
  — it protects articles and collections, never assets.
- The manifest storage makes `{% static %}` **raise** for any file missing
  from the manifest: dead asset references fail loudly instead of 404ing
  silently. This fail-loud is enforced in the **test gate** (which runs under
  the manifest storage), not on the dev `runserver`: dev overrides to the
  non-manifest backend so `runserver` needs no `collectstatic`, which trades
  dev-side fail-loud for zero-friction iteration. The parity the ADR defends —
  *WhiteNoise* serving in dev, not nginx — holds (WhiteNoise is in the dev
  middleware too). Dev-only variant stylesheets stay on their `/_dev/` routes
  outside the manifest.
- `collectstatic` becomes a deploy step (and a session fixture in the test
  gate, so the manifest exists for `{% static %}` and WhiteNoise to resolve).
