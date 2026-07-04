# Incremental reindex: synchronous scope updates, reference jobs, reconcile net

Status: DRAFT — designed ahead of Part 4 (the worker + first member-visible serving).

Part 3's index is rebuild-only. Part 4 serves members from it, so scope changes
(audience edits, unpublish, collection moves) must reach the index without a
human remembering to run `rebuild`. The §11 risk here is a *staleness* leak:
a narrowing edit that the index has not seen yet keeps content visible.

## Decision

Three mechanisms, one invariant each:

1. **Synchronous in-request index updates** own the leak window.
   Article save/delete → single-row upsert/delete in the same request, right
   after the canonical write. Collection audience/parent edit → synchronous
   subtree reindex (compute descendant ulids from the canonical tree, upsert
   those rows). At this archive's scale (~10³ articles) both are milliseconds;
   the over-exposure window is the request itself. No outbox, no dual-write
   dance on the happy path.

2. **Queue jobs are references, never payloads.** A job says "reindex article
   X" / "reindex subtree C" / "full rebuild"; execution re-reads canonical
   truth and recomputes. Jobs are idempotent and commute — two racing edits
   enqueue two pointers, whichever runs last recomputes the same final truth.
   No ordering, versioning, or dedup logic needed for correctness (dedup is an
   optimization only). The queue exists for: retry after a failed synchronous
   update, heavy work (thumbnails, future OCR), mirror replay, full rebuilds.

3. **Scheduled reconcile bounds every failure.** A periodic full `rebuild()`
   (already idempotent, single transaction, seconds at this scale) restores
   the invariant no matter what was missed — crashed process between file
   write and index write, failed sync update, operator error. Frequency is an
   ops knob (nightly default; cheap enough to run hourly). `config_version`
   mismatch at startup/deploy also forces one.

Failure of a synchronous index update does NOT fail the canonical write (the
archive is files-first); it enqueues the reference job and surfaces a UI
warning. The stale window is then bounded by retry backoff, worst-case by the
reconcile interval.

## The gate (from the roadmap, now concrete)

Member-visible serving may ship only when: (a) synchronous scope updates are
live for article AND collection edits, (b) the reconcile job is scheduled,
(c) a staleness test exists: narrow a collection's audience, assert the
member's very next search (same test process, no worker involved) no longer
returns descendants.

## Why not

- **Transactional outbox:** solves dual-write for DB-canonical systems; our
  canonical is files, so an outbox adds a third store without closing the
  file-write-then-crash gap. Reconcile closes it simpler.
- **Async-only queue (no synchronous path):** leaves a narrowing edit visible
  for the queue latency — an avoidable leak window when the synchronous
  update is milliseconds.
- **Delta-carrying jobs (payloads):** reintroduces ordering and staleness
  reasoning per job type. References + recompute make the whole class
  unrepresentable.
- **Postgres LISTEN/NOTIFY or triggers:** index-side machinery watching a
  store it cannot see (files). Wrong direction of truth.

## Consequences

- `rebuild()` stays THE semantics; incremental paths are performance sugar
  over the same `build_row`. The equivalence grid (Task 9) keeps guarding the
  shared code path.
- Collection deletion in the UI must be blocked while descendants exist
  (otherwise: fail-closed rows by design, archivist cleans up — acceptable,
  ugly, so the UI prevents it).
- The Part 4 plan gains tests: staleness test per edit type (the gate),
  sync-failure → job-enqueued path, reconcile-heals-orphan test.
- Deferred with triggers: job dedup/coalescing (only if queue depth ever
  matters); sub-second freshness SLAs (only if reconcile + sync prove
  insufficient — no current reason to expect it).
