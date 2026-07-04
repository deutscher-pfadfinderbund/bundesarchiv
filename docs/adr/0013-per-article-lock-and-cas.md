# Per-Article optimistic concurrency: version CAS, no locks

Status: DRAFT — designed ahead of Part 4 (multi-writer arrives with the web UI).

Multiple archivists edit through the web UI at once. v1 through Part 3 was
single-writer; Part 4 breaks that assumption. We need a concurrency rule for
the canonical store (README files through the ObjectStore port).

## Decision

**Optimistic compare-and-swap on the Article version, no locks.**

- Every `Article` carries a monotonically increasing `version` (already the
  `changes/<version>.json` counter from Part 1). The README's front matter
  records it.
- `ArticleRepository.update(ulid, mutate, expected_version)`: load, check
  `loaded.version == expected_version`, apply, write `version + 1` via the
  atomic temp→fsync→rename path. On mismatch → typed `StaleVersion` error
  (ArchiveError hierarchy), nothing written.
- The web form carries the version it loaded as a hidden field. On
  `StaleVersion` the UI re-loads, shows "Inzwischen geändert von …" with a
  field-level diff, and lets the archivist re-apply — never a silent
  last-writer-wins, never a merge attempt in v1.
- The check-and-write must be serialized per process: one process-wide mutex
  around the load-check-write critical section (we deploy ONE app process for
  the write path in v1; enforced by deployment config, stated in the runbook).
  Cross-process safety therefore reduces to the single-writer-process rule —
  no fcntl/advisory file locks, no lock files to leak on crash.

## Why not

- **Advisory file locks (fcntl/flock):** don't survive NFS-ish mounts, leak on
  crash, unobservable, and give false confidence the moment a second host
  appears. The failure mode of CAS (a clean retry screen) is strictly better
  than the failure mode of locks (deadlock or silent bypass).
- **Pessimistic lock rows in Postgres:** the index is disposable; putting the
  concurrency truth there inverts the files-canonical rule. Locks also rot
  (browser closed mid-edit → lease expiry machinery). CAS needs no expiry.
- **Last-writer-wins:** silent data loss in an archive is the one unforgivable
  failure.
- **CRDT/merge:** v1 has a handful of archivists; a conflict is rare and a
  human re-apply is cheap. Merge machinery is decade-maintenance poison.

## Consequences

- `Collection` edits get the same rule (collections carry audience — a lost
  collection edit is an access-control change). Same CAS, same error type.
- Media blobs are exempt: content-addressed write-once, concurrent identical
  writes are idempotent by construction; a differing blob is a new key.
- The WebDAV mirror replay and the future inbox-ingest worker go through the
  same repository CAS path — a worker is just another writer.
- The `changes/` version counter becomes load-bearing for correctness, not
  just history; the Part 4 plan adds a conformance test: two racing updates,
  exactly one wins, the loser gets `StaleVersion`, the store ends at
  `version + 1` with the winner's content.
- Deferred with triggers: multi-host write path (would need real distributed
  CAS — revisit only if a second app host ever exists); field-level merge UX
  (revisit if conflicts prove frequent in practice).
