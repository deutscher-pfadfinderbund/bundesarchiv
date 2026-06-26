# Part 1 — Persistence layer (build plan)

Implements the two-seam persistence layer from [ADR 0005](../adr/0005-persistence-layer.md): a low-level **`ObjectStore`** (backend seam) and a deep **`ArticleRepository`** (the canonical-file protocol). Foundational — every later part sits on this.

## Scaffold decision

The persistence layer is **pure Python** — it needs nothing from Django. So:

- **This part initializes a minimal, framework-free Python project**: `pyproject.toml` (deps: `pytest`, `ruff`, `mypy`; runtime: a ULID lib, a YAML/front-matter lib, a WebDAV client), `src/bundesarchiv/`, `tests/`.
- **Django is NOT introduced here.** It arrives at Part 3 (index — Postgres/ORM) or Part 4 (web/UI), whichever lands first, and *imports* this package. The pure modules never move; the layout is chosen so the Django project slots in alongside (`src/bundesarchiv/persistence/`, `…/domain/`, later `…/web/` as a Django app + a `config/` project package).

## Modules (→ ADR 0005)

**`ObjectStore`** (internal seam; backend varies) — 6 ops, defined to the WebDAV/S3 lowest common denominator (no append, no rename, no OS lock):
```
read(key) -> bytes
writeAtomic(key, data: bytes) -> None        # create-or-replace; reader sees old-or-new, never partial
putLarge(key, stream, size) -> None          # streamed; same all-or-nothing finalize
list(prefix) -> Iterable[str]                # excludes reserved temp/lock namespace
exists(key) -> bool
delete(key) -> None                          # idempotent
```

**`ArticleRepository`** (external deep module; the app uses only this):
```
load(ulid) -> Article                        # reads README.md (+ manifest); NotFound if absent
save(article, expected_version) -> Version   # atomic commit; Conflict if stale
list_ulids() -> Iterable[ULID]               # walk for reindex
hard_delete(ulid) -> None                    # rare, recoverable trash; normal delete = a lifecycle/status save
```
Owns: the `articles/<ulid>/{README.md, media/, changes/<version>.json, .snapshots/}` layout; README.md (de)serialization (YAML front-matter + Markdown body + managed-by marker); the per-Article **lock object**; the pinned write order (**media → README.md = commit → changes → snapshot**); optimistic versioning; media write-once. Sits on an `ObjectStore`.

## Build steps (TDD — red → green → refactor, tiny commits)

1. **Scaffold** — `pyproject.toml`, `src/bundesarchiv/`, `tests/`, ruff+mypy+pytest config, CI-runnable `pytest`. _Commit._
2. **`ObjectStore` interface** — the Protocol/ABC + typed errors (`NotFound`, `Conflict`). No implementation. _Commit._
3. **Conformance suite (tests first)** — one parametrized test module any adapter must pass: concurrent-reader-sees-old-or-new (never partial); killed-mid-write leaves prior-object-or-nothing at the final key; `list(prefix)` excludes reserved temp/lock keys; `putLarge` finalize is all-or-nothing; round-trip `read`/`writeAtomic`/`exists`/`delete`. _Commit (red)._
4. **`InMemoryObjectStore`** — simplest adapter; makes the conformance suite green; doubles as the test fake. _Commit (green)._
5. **`LocalFsObjectStore`** (canonical, v1) — temp→fsync→`rename`→fsync-dir; refuse `EXDEV`; reserved-prefix handling. Pass conformance **including a kill-9 / crash-injection atomicity test**. _Commit._
6. **`WebDavObjectStore`** (Nextcloud mirror, first-class) — PUT-temp+`MOVE`; chunked upload for `putLarge`; retry `423`, handle `507`; lock object. Pass conformance against a WebDAV test server (or a recorded/mock transport). _Commit._
7. **`ArticleRepository`** over `ObjectStore` (tested via `InMemoryObjectStore`, no disk): README.md (de)serialize round-trip · `save` commit-ordering (media first, README.md last) · optimistic-version `Conflict` · `hard_delete` → trash (recoverable) · `list_ulids` · the key-naming policy (NFC lowercase ASCII slug + ULID; media keys content-addressed). _Commit._

## Test strategy

- **Replace, don't layer** — `ArticleRepository` is tested over the `InMemoryObjectStore` fake (no disk, fast); the FS and WebDAV adapters are tested through the shared `ObjectStore` conformance suite.
- The conformance suite is the single contract — adding an adapter later (S3) means making it pass the same suite.
- Domain core / web (later parts) accept an injected `ArticleRepository`.

## Done when

- All three adapters (`InMemory`, `LocalFs`, `WebDav`) pass the conformance suite (FS incl. crash test).
- `ArticleRepository` round-trips an Article, enforces optimistic concurrency, holds the write order, and supports recoverable `hard_delete`.
- No Django dependency anywhere in the package.
