# Conventions

How code in this repo is written. Binds human contributors and AI agents alike.

## Stack & tooling

- **Python ≥ 3.14**, managed by **uv** (`uv.lock` pinned, `.python-version`).
- **Sync, not async** (WSGI) — see rationale below.
- **ruff** = lint + format (line length 100; rules `E,F,I,UP,B,SIM,RUF`).
- **mypy `--strict`** = the **committed** type checker; gates merges via pre-commit. `django-stubs` is added when Django arrives (parts 3–4) — it is the only checker today with first-class Django ORM typing.
- **pyrefly / ty** may be run **advisory / in-editor only** — they are *not* the merge gate (Django ORM typing is immature in both as of 2026; see `docs/django6-notes.md`).
- Editor LSP: Pylance / pyright / pyrefly / ty — any; not the gate.
- **pytest** + **TDD** (red → green → refactor). Test *through* interfaces (replace-don't-layer; in-memory fakes).
- **pre-commit** runs ruff → mypy → pytest (all via `uv run`).

## Why sync (not async)

Django 6's async ORM is still partial — transactions raise `SynchronousOnlyOperation`, the ORM is "async-unsafe" global state, and the docs route back to `sync_to_async`. This app is server-rendered CRUD + search at small scale, so async buys nothing and adds function-coloring + a dual `save()/asave()` API = bus-factor cost. Slow I/O (WebDAV mirror, large media) goes to a **background worker** (Django Tasks framework), not async views.

## Architecture patterns

- **Pure core, imperative shell** — domain + persistence logic is pure and testable; IO / DB / framework live only at the edges.
- **No framework in the core** — `domain/` and `persistence/` never import Django (ADR 0005).
- **Ports & adapters** — `ObjectStore` is a port; swap backends at the seam.
- **Dependency injection** — pass deps in (`ObjectStore` → `ArticleRepository` → domain / web); never construct them inside.
- **Deep modules** (`codebase-design`) — small interface, lots of behaviour; the interface is the test surface.
- **Fail closed for security** — effective-audience / field-floor logic defaults to *less* visible.

## Code style

- **Typed** — every public interface fully annotated; mypy strict.
- **Errors** — a typed exception hierarchy (`ArchiveError` → `NotFound`, `Conflict`, …); never bare `Exception`.
- **Immutability** — frozen dataclasses where sensible.
- **Docstrings** — light; public interfaces only. Types + clear names carry the rest.
- **Language** — code / identifiers / comments in **English**; user-facing strings in **German** (i18n machinery added with the UI).
- **Layout** — `src/` layout. Pure packages (`domain/`, `persistence/`); Django (apps + a `conf/` project package + `manage.py`) is added at the edges later and imports the pure core — the core never moves.

## Git

- **Conventional Commits.**
- Local-only for now (no remote); GitHub Actions CI added when a remote exists.
