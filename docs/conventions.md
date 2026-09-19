# Conventions

How code in this repo is written. Binds human contributors and AI agents alike.

## Stack & tooling

- **Python ≥ 3.14**, managed by **uv** (`uv.lock` pinned, `.python-version`).
- **Sync, not async** (WSGI) — see rationale below.
- **ruff** = lint + format (line length 100; ruff's defaults `E4,E7,E9,F` extended with `I,UP,B,SIM,RUF,C4,FURB,PERF,PIE,PTH,RET`).
- **mypy `--strict`** = the **canonical** type checker, gating at the **pre-push** hook. `django-stubs` + `mypy_django_plugin` are wired in — it is the only checker today with first-class Django ORM typing.
- **pyrefly** = a fast **blocking** second opinion, zero-error policy: commit-stage pre-commit hook plus an agent Stop hook (Django ORM typing is immature in pyrefly / ty as of 2026, so mypy stays canonical; see `docs/django6-notes.md`).
- Editor LSP: Pylance / pyright / ty — any; not the gate.
- **pytest** + **TDD** (red → green → refactor). Test *through* interfaces (replace-don't-layer; in-memory fakes).
- **pre-commit**, two stages (all via `uv run`): commit = uv-lock → ruff → pyrefly; push = mypy → pytest. Running the full gate on every commit is writer-agent discipline (`docs/agents/writer-brief.md`), not the commit hook.

## Why sync (not async)

Django 6's async ORM is still partial — transactions raise `SynchronousOnlyOperation`, the ORM is "async-unsafe" global state, and the docs route back to `sync_to_async`. This app is server-rendered CRUD + search at small scale, so async buys nothing and adds function-coloring + a dual `save()/asave()` API = bus-factor cost. Slow I/O (WebDAV mirror, large media) goes to a **background worker** (Django Tasks framework), not async views.

## Architecture patterns

- **Pure core, imperative shell** — domain + persistence logic is pure and testable; IO / DB / framework live only at the edges.
- **No framework in the core** — `domain/` and `persistence/` never import Django (ADR 0005).
- **Ports & adapters** — `ObjectStore` is a port; swap backends at the seam.
- **Dependency injection** — pass deps in (`ObjectStore` → repositories → domain; `Archive` → services and web); never construct them inside. The canonical store is built from settings in `Archive.canonical()` and nowhere else.
- **Deep modules** (`codebase-design`) — small interface, lots of behaviour; the interface is the test surface.
- **Fail closed for security** — effective-audience / field-floor logic defaults to *less* visible.

## Code style

- **Typed** — every public interface fully annotated; mypy strict.
- **No `from __future__ import annotations`** — on Python ≥3.14, PEP 649 evaluates annotations lazily by default; the future import (PEP 563) re-stringizes them and defeats PEP 649 (and runtime introspection). Omit it.
- **Errors** — a typed exception hierarchy (`ArchiveError` → `NotFound`, `Conflict`, …); never bare `Exception`.
- **Immutability** — frozen dataclasses where sensible.
- **Docstrings** — light; public interfaces only. Types + clear names carry the rest.
- **Language** — code / identifiers / comments in **English**; user-facing strings in **German** (i18n machinery added with the UI).
- **Layout** — `src/` layout. Pure packages (`domain/`, `persistence/`); Django (apps + a `conf/` project package + `manage.py`) is added at the edges later and imports the pure core — the core never moves.

## Git

- **Conventional Commits.**
- `origin` is a public GitHub repo (issues + PRDs live there). No CI backstop yet — tracked in #12.
