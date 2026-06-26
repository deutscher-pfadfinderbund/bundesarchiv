# Framework: Django + HTMX

The application is built with **Django** (Python) using **HTMX** for interactivity (server-rendered HTML fragment swaps), plus a sprinkle of Alpine.js only for purely-local UI. No SPA, no separate JS frontend, no API layer.

Chosen because the application is **server-render-shaped** (CRUD + faceted search + media display), not SPA-shaped — HTMX covers the needed interactivity (autocomplete, search-as-you-type, inline edit, the publish-time visibility preview) with no build pipeline to maintain over a decade. Django is a mature, stable, batteries-included fit for this shape, existing Django expertise is available, and Python is the strongest ecosystem for the deferred OCR/content-search goal (OCRmyPDF + Tesseract `deu`). Keycloak OIDC integrates via `mozilla-django-oidc`.

## Considered options

- **Rails 8 + Hotwire** — densest batteries (Solid Queue, Kamal), but introduces a new language and its faster release cadence is a weaker fit for a long-lived, low-maintenance archive.
- **Phoenix + LiveView (Elixir)** — strong interactivity, background jobs (Oban on Postgres), and a long-proven runtime, but introduces an unfamiliar language, a thinner OCR ecosystem, and a stateful-websocket model v1 does not need.
- **SvelteKit (TypeScript)** — well-shaped for the app and a broad contributor pool, but introduces a new stack, German OCR lives in the Python ecosystem, and there is no built-in admin.

## Consequences

- **The Django admin is NOT the cataloging UI.** Canonical data is `README.md` files under the sole-writer storage port; the admin edits DB rows and would write the *disposable index*, bypassing the port + lock — a correctness bug. Archivist screens are **custom forms** that go through the storage port.
- **Background jobs** (thumbnails, reindex, future OCR) run on a single **Postgres-backed worker** (Procrastinate or `django-tasks-db`) — no Redis, no Celery broker.
- The **effective-audience function** is one pure, test-guarded Python function (Django does not enforce purity at the language level — tests do); it is reused by list filters, detail auth, the index filter, and the visibility preview.
- The Postgres index is treated as **disposable/derived** — resist the ORM's gravity to treat DB rows as canonical; everything rebuilds from `README.md`.
- Per ADR 0002, framework lock-in is bounded to an app-layer rewrite; the archive (files) is unaffected by this choice.
