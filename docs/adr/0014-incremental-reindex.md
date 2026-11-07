# Incremental reindex: synchronous scope updates, reference jobs, reconcile net

Status: Accepted (2026-07-04). Refined by 0024 (2026-10-18).

Worker library: **Procrastinate** (Postgres-table-only queue, no broker, Django
6.0 compatible, `periodic` scheduler for the reconcile, single-process deploy).
django-tasks was rejected: as of 0.12.0 it ships no database backend (only
`immediate`/`dummy`), so it cannot durably queue jobs today.

Part 3's index is rebuild-only. Part 4 serves members from it, so scope changes
(audience edits, unpublish, collection moves) must reach the index without a
human remembering to run `rebuild`. The §11 risk here is a *staleness* leak:
a narrowing edit that the index has not seen yet keeps content visible.

## Decision

Three mechanisms, one invariant each:

1. **Synchronous in-request index updates** own the leak window.
   Article save/delete → single-row upsert/delete in the same request, right
   after the canonical write. Collection audience/parent edit → synchronous
   subtree reindex. At this archive's scale (~10³ articles) both are
   milliseconds; the over-exposure window is the request itself.

   Both upserts, `index_article` and `index_subtree`, route through the SAME
   `build_row` + fail-closed branch as `rebuild()` (an article whose chain breaks mid-edit becomes a
   fail-closed row, identical semantics). `rebuild()` remains THE semantics;
   the incremental paths are performance sugar over the same code path, so the
   Task 9 equivalence grid keeps guarding all of them.

2. **Queue jobs are references, never payloads.** A job says "reindex article
   X" / "reindex subtree C" / "full rebuild"; execution re-reads canonical
   truth and recomputes. Jobs are idempotent and commute — two racing edits
   enqueue two pointers; whichever runs last recomputes the same final truth.
   The queue exists for: retry after a failed synchronous update, heavy work
   (thumbnails, future OCR), mirror replay, full rebuilds.

3. **Scheduled reconcile bounds every failure.** A periodic full `rebuild()`
   restores the invariant no matter what was missed. **Default: hourly** (the
   rebuild is seconds at this scale; hourly makes the worst-case staleness
   window below match the archive's own risk language instead of a day).
   `config_version` mismatch check runs at startup (`ensure_index_current`)
   and forces a rebuild.

## Writer coordination (rebuild vs sync upsert race)

A sync upsert landing while a full `rebuild()` is mid-flight can be clobbered
by the rebuild's older file snapshot (rebuild read the tree before the edit,
writes after it). Files heal on the NEXT reconcile, but the window is real.
**Rule: every index writer — `rebuild`, `index_article`, `index_subtree` —
takes the same Postgres transaction-scoped advisory lock
(`pg_advisory_xact_lock`, one project-wide key), and takes it BEFORE it reads
the files: lock, read, write, in one transaction.** The lock orders the reads
too, so a writer that read an older snapshot can never commit after a newer
one. Sync upserts wait behind a running rebuild; in the request that wait is
bounded (`SYNC_LOCK_TIMEOUT_MS`), and a timeout hands the reindex to the retry
job. One lock, one rule, no lost updates between index writers. (Canonical-file
writers are governed by ADR 0013, not this lock.)

## Honest failure window

If the process dies after the canonical write but before BOTH the sync update
and the enqueue, the index stays stale until the reconcile. With the hourly
default, a security-narrowing edit can remain over-exposed for up to an hour
in that crash case. This is the accepted residual risk — stated here so nobody
discovers it in an incident review.

## The gate (from the roadmap, now concrete and adversarial)

Member-visible serving may ship only when: (a) synchronous scope updates are
live for article AND collection edits, (b) the reconcile job is scheduled,
(c) the staleness test passes **adversarially**: it calls ONLY the production
edit entry point (the service/repository call the UI uses — `rebuild()` is
forbidden inside the test), then asserts the member's very next `search()`
excludes the narrowed content. A test that could pass via an incidental
rebuild proves nothing about the synchronous path.

## Why not

- **Transactional outbox:** solves dual-write for DB-canonical systems; our
  canonical is files, so an outbox adds a third store without closing the
  file-write-then-crash gap. Reconcile closes it simpler.
- **Async-only queue:** leaves a narrowing edit visible for the queue latency
  when the synchronous update costs milliseconds.
- **Delta-carrying jobs:** reintroduces ordering/staleness reasoning per job
  type. References + recompute make the class unrepresentable.
- **LISTEN/NOTIFY or DB triggers:** index-side machinery watching a store it
  cannot see (files). Wrong direction of truth.

## Consequences

- Job-table hygiene is an ops knob: Procrastinate accumulates finished
  `procrastinate_jobs` rows; prune them periodically. Stated in the deploy
  runbook next to the reconcile interval.
- Concrete knobs: the reconcile cadence is `BUNDESARCHIV_RECONCILE_CRON`
  (default `0 * * * *`, hourly); the canonical store a job re-reads is
  `BUNDESARCHIV_CANONICAL_ROOT`; the one index-writer advisory-lock key is the
  fixed constant `indexer._INDEX_WRITER_LOCK_KEY` (never reuse it for another
  lock). config_version drift is remedied by `manage.py ensure_index_current`,
  run at deploy and worker startup.
- Tests: the adversarial staleness gate per edit type; sync-failure →
  job-enqueued path; reconcile-heals-orphan; advisory-lock
  serialization (upsert during rebuild → final state reflects canonical).
- Deferred with triggers: job dedup/coalescing (only if queue depth matters);
  sub-second freshness SLAs (only if reconcile + sync prove insufficient).
