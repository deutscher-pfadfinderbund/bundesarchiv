# The search index belongs to the Archive, behind a port

Status: Accepted (2026-10-18). Refines ADR 0014 (who holds the index the write path refreshes).

## Context

After every canonical write the app refreshes the search index in the same request (ADR 0014,
point 1). That refresh reached Postgres through two module-level functions, so the write services
could not run without Postgres, and the tests that only checked the write path patched our own
code to stub the index (`docs/tech-debt.md` #55, #56). The `Archive` handle already carried the
canonical store and the two repositories built over it.

## Decision

- **The `Archive` carries what a canonical write must refresh in the request** (ADR 0014,
  point 1): today, the search index. Owner, 2026-10-18: the index is a projection of the
  archive's own store. Its content is a function of that store and can be rebuilt from it, and it
  never exists without it; the store never reads the index. So it is built over the archive's
  store, like `articles` and `collections`. Under ADR 0020 Stage B that is the local store.
- **Derived projections filled later stay reference jobs**, not `Archive` members: thumbnails,
  the page texts (ADR 0023).
- **Construction rule: the `Archive` builds its index from its own store.** It takes a factory
  `(store) -> index` and calls it with its store; it never takes a ready index.
- **The port speaks in IDs** and lives in the `index` package: refresh one Article's row (or drop
  it when the Article is gone), refresh a Collection's subtree. Best effort: the write already
  stood. Which write needs which refresh stays in `after_write.run`.
- **Postgres is the default.** `Archive.of(store)` builds the Postgres index; a test asks for the
  in-memory one explicitly. `Archive.canonical()` builds the Postgres index too, unless a test's
  settings override sets `BUNDESARCHIV_INDEX` to another factory. The settings module never
  defines it, and the production WSGI entry refuses to serve when it is set: over the in-memory
  index, a save would claim the index current, queue no retry and show no lag notice.
- **The Postgres adapter is ADR 0014's writer**: lock, read, write, in one transaction. The sync
  lock timeout is a construction parameter.
- **The in-memory index computes no rows.** It records each refresh with the version the store
  held at that moment, so a test still sees a refresh that ran before its write; it can be told
  to fail. Row content stays covered by the indexer's own Postgres tests.

The mirror is different. It is another store that receives copies, it is optional, and its role
swaps with the canonical store in ADR 0020 Stage B. So it stays an argument of the jobs that use
it, not part of the `Archive`.

## Consequences

- The write services' tests run without Postgres, except those that assert index rows or hold
  the real lock. The web tests select the in-memory index through the setting, not a patch.
- Some entry points reach the Postgres indexer directly, on purpose: `rebuild`,
  `ensure_index_current`, and the retry jobs, which wait for the lock without the sync timeout.
  The read side (search, facets) stays Postgres too: a fake search would be a second search
  engine, and the leak tests must prove the real SQL.
