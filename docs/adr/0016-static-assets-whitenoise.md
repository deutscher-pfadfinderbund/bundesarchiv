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
authorized per request per viewer, and every failure collapses to the same
revealing-nothing 404 (ADR 0001, 0012; the byte-identical form of that law was
relaxed by the owner in 2026-08). How their bytes are served is ADR 0017.

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
  public-by-design contract lives in its own test (`test_static_assets.py`): a
  fail-loud whitelist of the asset set, an uncollected path that is not served
  (no existence oracle), and the unhashed-path pin below. The deny contract is
  untouched — it protects articles and collections, never assets.
- **No traversal test, deliberately.** An earlier draft promised
  directory-traversal containment here. There is no traversal surface to gate:
  outside autorefresh mode (so, prod and the test gate) WhiteNoise answers a URL
  by `self.files[url]` — a dict built once by scanning `STATIC_ROOT` — so no user
  input ever reaches a path join. A test there would pin library mechanics, which
  the testing razor excludes (owner ruling 2026-08, `tests/CLAUDE.md`).
- The manifest storage makes `{% static %}` **raise** for any file missing
  from the manifest: dead asset references fail loudly instead of 404ing
  silently. This fail-loud is enforced in the **test gate** (which runs under
  the manifest storage), not on the dev `runserver`: dev overrides to the
  non-manifest backend so `runserver` needs no `collectstatic`, which trades
  dev-side fail-loud for zero-friction iteration. The parity the ADR defends —
  *WhiteNoise* serving in dev, not nginx — holds (WhiteNoise is in the dev
  middleware too). Dev-only variant stylesheets stay on their `/_dev/` routes
  outside the manifest.
- **Only hashed names are collected** (`WHITENOISE_KEEP_ONLY_HASHED_FILES`), which
  closes the one hole in that fail-loud: `{% static %}` raises for a missing file,
  but a *hardcoded* `/static/tokens.css` never calls the tag, and by default
  `collectstatic` keeps an unhashed copy that would serve it (at a 60s max-age)
  as if nothing were wrong. Without those copies such a reference 404s in prod,
  and `STATIC_ROOT` holds one file per asset instead of two — each with gzip and
  brotli variants. Dev is unaffected (non-manifest backend; `runserver` serves
  from the finders), as are the `/_dev/static/` stylesheets, which read the
  source static dir rather than `STATIC_ROOT`.
- `collectstatic` becomes a deploy step (and a session fixture in the test
  gate, so the manifest exists for `{% static %}` and WhiteNoise to resolve).
