# Articles are valid-by-construction; no persistence DTO layer

## Context

Today there is one path that builds an `Article`: the README codec (`persistence/readme.py`)
reconstructs an already-created Article from front-matter. Part 3 adds a **second** path —
the derived Postgres index returns Article-shaped rows — and Part 4 a third (the cataloging
form *creates* new Articles). An architecture review flagged that `Article` is simultaneously
the persisted record, the repository return type, and the domain resolver's input, and proposed
a persistence-side `ArticleData` DTO with a `to_article()` seam where every source converges and
schema drift is caught once.

The repo's established idiom is the opposite of a DTO: domain value objects are **valid by
construction** — `Audience.__post_init__` forbids contradictory rungs, `ResolvedChain.__post_init__`
owns the chain's structural invariant, the codec coerces/validates every scalar before building an
Article. A parallel mutable DTO + converter + a field-by-field equivalence-test burden cuts against
that grain.

## Decision

- **No `ArticleData` DTO.** `Article` (frozen, validated) is the single in-memory shape every
  source produces. There is one construction contract, not a DTO-then-domain two-step.
- **Creation mints via one factory.** `domain.identity.create_article(...)` is the sole place a
  ULID is minted at creation (ADR 0006). The cataloging form (Part 4) calls it; nothing else mints.
- **Reconstruction goes through the codec.** Existing Articles are rebuilt by `readme.decode`
  (carrying the already-minted ULID); the Part-3 Postgres path must construct the **same** validated
  `Article`, not a separate shape. If a source proves able to produce a malformed Article, the fix is
  to strengthen `Article`'s own construction invariants (so *every* path is covered), not to add a DTO
  guarding one producer.
- **Identity-format enforcement stays at the edges it belongs to:** `create_article` (mint),
  `ObjectStore.validate_key` (traversal safety), and a future web-route check via `is_valid_ulid`
  (Part 4) — not a DTO.

## Consequences

- No DTO/converter/equivalence-matrix to maintain; Part 3 wiring constructs Articles the one way.
- The leak this guards against (a query path building an Article the resolver mistrusts) is closed by
  the type, reachable only by strengthening `Article` once if needed — covering all paths at once.
- `create_article` is the documented ADR-0006 "Article factory, Part 2", now implemented; it wires the
  previously-unused `new_ulid` into the creation path. `is_valid_ulid` remains a primitive awaiting its
  Part-4 web-route caller (validating a ULID from a URL before touching storage).
- **Rejected:** the `ArticleData` persistence DTO — it duplicates the Article shape and contradicts the
  valid-by-construction idiom for an anticipated drift that a single `Article` invariant can cover.
