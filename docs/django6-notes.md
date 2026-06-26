# Django 6.0 — notes for later parts

Verified against the Django 6.0 release notes + topic docs (2026-06). Adopt these when the relevant part lands. Django 6.0 supports Python 3.12–3.14; use **psycopg 3** (≥3.1.12).

## Background worker (Part 6)

- Adopt Django's **Tasks framework API** (`@task`, `.enqueue()`, `TaskResult`, the `TASKS` setting) as the application-facing contract.
- Core ships **no production worker** — only `ImmediateBackend` / `DummyBackend` (dev/test). So keep our plan: bring a **Postgres-backed backend** — `django-tasks-db` (ORM-backed, confirmed in the ecosystem) or **Procrastinate** (Postgres `LISTEN/NOTIFY`; *verify* it adapts to the 6.0 `TASKS` contract). **No Redis.**
- Task args/returns must be **JSON-serializable** → pass IDs/paths, never model instances or file objects.
- Enqueue inside `transaction.on_commit(...)` so jobs don't fire for rolled-back writes.
- This is also how the **async Nextcloud mirror** (ADR 0005) runs: a task replays a committed Article's files to the WebDAV `ObjectStore`.

## Web / UI (Part 4)

- **Template partials** are in core now (`{% partialdef %}` / `{% partial %}`, plus `template_name#partial_name`) — the idiomatic way to return the *same* fragment for an HTMX swap and a full-page render. Do **not** use the third-party `django-template-partials`.
- **Content-Security-Policy is built in** (`ContentSecurityPolicyMiddleware`, `SECURE_CSP`, per-request nonces via `{{ csp_nonce }}` / `{% csp_nonce_attr %}`). Plan HTMX inline scripts around `CSP.NONCE` from day one; HTML + header must be same-request (not cached).
- Pagination: the `querystring` tag (auto `?`, merges/overrides params) + `forloop.length` — handy for faceted-filter links.

## Search (Part 3)

- German FTS: `SearchVector(..., config="german")` + `SearchQuery(..., config="german")`.
- New **`Lexeme`** expression — injection-safe boolean/prefix/weighted query terms (`&`, `|`, `~`, `prefix=`, `weight=`). Use it to parse untrusted faceted-search input.
- `StringAgg` is now `django.db.models.StringAgg` (db-agnostic); the `contrib.postgres` one is deprecated.
- Custom SQL expressions: `as_sql()` must return params as a **tuple** (relevant for ICU-collation / FTS tuning).

## Greenfield correctness

- `DEFAULT_AUTO_FIELD` defaults to `BigAutoField` (no settings line needed).
- `Model.save()` may raise `Model.NotUpdated` on a forced zero-row update; `Field.pre_save()` may be called more than once (keep idempotent).
- Our custom `ObjectStore` is **not** Django's `Storage` API → unaffected by 6.0 (only the obscure `OS_OPEN_FLAGS` was removed).
- Keycloak OIDC is unaffected by 6.0 (handled by the OIDC library, e.g. `mozilla-django-oidc`).
