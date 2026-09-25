# Per-Article optimistic concurrency: version CAS, no locks

> **Note (proposed 2026-09-24):** stage B of [ADR 0020](0020-storage-topology-system-of-record.md)
> would move the compare-and-swap to WebDAV `If-Match` and retire `WRITER_LOCK`.

Status: Accepted (2026-07-04) — adopted by Part 4.1. v2 folded the 2026-07-04
adversarial panel findings (reconciled against the built Part 1 code); Part 4.1
added the shared writer mutex and Collection versioning, then adopted this ADR.

Multiple archivists edit through the web UI at once. v1 through Part 3 was
single-writer; Part 4 breaks that assumption. We need a concurrency rule for
the canonical store (README files through the ObjectStore port).

## Decision

**Optimistic compare-and-swap on the Article version, no locks.**

- The version's source of truth is the **README front matter** (`version:` key,
  read via `readme.read_version` / `ArticleRepository._current_version`). The
  `changes/<version>.json` records are gap-tolerant secondary history per
  ADR 0005 — never the counter, never load-bearing for CAS.
  *(Amended 2026-09-25, [ADR 0019](0019-canonical-layout-v1.md): `_current_version` and
  `changes/` are gone. `_writer.commit` reads the version, and writes `history/<n>.md`
  create-only inside the CAS section; a history file holding other bytes refuses the save.)*
- The CAS primitive **already exists**: `ArticleRepository.save(article,
  expected_version)` raises the existing typed **`Conflict`** error on version
  mismatch, nothing written. We reuse `Conflict` — no new `StaleVersion` type;
  inventing a parallel name for the same condition would split the seam.
- **The web form path calls `save(mutated, expected_version_from_form)`
  directly and lets the FIRST `Conflict` propagate.** The form carries the
  version it loaded as a hidden field. On `Conflict` the UI re-loads, shows
  "Inzwischen geändert von …" with a field-level diff, and lets the archivist
  re-apply. Never silent last-writer-wins, never an automatic merge.
- The retrying variant — re-load and retry on `Conflict` — is **for internal
  idempotent mutations only** (worker jobs, structural changes). It is
  last-writer-wins by construction and therefore FORBIDDEN for form saves.
  *(Amended 2026-09: it lives as `app.articles.update_article`, one level up,
  so a retry carries the full write shell; the repository-level `update()`
  this ADR originally named had no production caller and was deleted. The
  split is now enforced by which service a caller uses, not by a docstring.)*
- Atomicity sits at the port: `write_atomic`'s create-or-replace contract (the
  LocalFs adapter implements it temp→fsync→rename; other adapters honor the
  same contract). The check-and-write critical section is serialized by one
  process-wide mutex + the single-app-process deploy rule (runbook item).
  Worker jobs write through the same repositories in the same process group's
  discipline; see ADR 0014.

## Collections get the same rule — as sized work, not a footnote

`Collection` carries audience; a lost collection edit is an access-control
change. But Collections have **no version field today**: Part 4.1 adds
`version` to the collection README front matter, the codec round-trip, a
versioned load result, and `save(collection, expected_version)` with the same
`Conflict` semantics. This is a real task with codec + repository + conformance
tests, mirroring the Article shape.

## Supersession

ADR 0002/0005 reserved a per-Article `.lock` object as the future multi-writer
mechanism. **This ADR supersedes that provision:** CAS + the single-writer
process replaces the lock object. The reserved `.lock` key name stays reserved
(never write it), so mirrors and backups of older trees stay interpretable.

## Why not

- **Advisory file locks (fcntl/flock):** leak on crash, unobservable, false
  confidence the moment a second host appears. CAS's failure mode (a clean
  retry screen) is strictly better than a deadlock or a silently bypassed lock.
- **Pessimistic lock rows in Postgres:** the index is disposable; putting
  concurrency truth there inverts files-canonical. Locks also rot (browser
  closed mid-edit → lease machinery). CAS needs no expiry.
- **Last-writer-wins:** silent data loss in an archive is the one unforgivable
  failure — and it is exactly what routing form saves through the retrying
  `update()` would produce.
- **CRDT/merge:** a handful of archivists; conflicts are rare and a human
  re-apply is cheap. Merge machinery is decade-maintenance poison.

## Consequences

- Media files exempt: create-only writes, plus the hash suffix on a taken name (ADR 0019).
- The process-wide mutex assumes a local-latency canonical store (the v1
  deploy): a WebDAV-canonical configuration would serialize network
  round-trips under the one lock — revisit the lock scope before any such
  configuration ships.
- Part 4.1 conformance tests: two racing form saves → exactly one winner, the
  loser's `save(…, stale_version)` raises `Conflict`, the store's README ends
  at the winner's `version + 1`. Assert against the README version — never
  against `changes/*.json` presence (gap-tolerant). *(Amended 2026-09-25: `changes/` is
  gone, see Decision.)*
- The Part 4 UI task must map `Conflict` → the "Inzwischen geändert" screen at
  the form controller layer; no other layer catches it.
- Deferred with triggers: multi-host write path (needs real distributed CAS —
  only if a second app host ever exists); field-level merge UX (only if
  conflicts prove frequent).
