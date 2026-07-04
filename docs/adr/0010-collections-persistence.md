# Collections persist as a per-node README tree, not a single file

## Context

Part 3 (derived Postgres search index) needs the full Collection tree from
canonical storage. Collections existed only in memory. They need the same
files-canonical persistence Articles already have (ADR 0005).

Two layouts were considered:

- **Single file** — one `collections.json` or `collections.yaml` listing every
  Collection.
- **Per-node README tree** — `collections/<ulid>/README.md` for each Collection,
  mirroring `articles/<ulid>/README.md`.

## Decision

Use the per-node README tree (`collections/<ulid>/README.md`).

Wire keys: `name` (required), `parent_id` (optional — absent means root),
`audience` (optional — absent means inherit, same convention as Article).

## Consequences

- **Consistent with the Article pattern.** The same codec shape, the same key
  naming, and the same `CollectionRepository` / `ObjectStore` split apply. No
  new concepts.
- **WebDAV-browsable.** Each Collection is a named directory in the mirror, just
  like each Article. Humans browsing Nextcloud see the tree structure directly.
- **Per-node atomic writes.** Saving one Collection never touches another node.
  A crash leaves at most one README in an inconsistent state.
- **Rejected — single collections file.** Atomicity was the main argument for it,
  but under the single-writer invariant (ADR 0002) multi-node atomicity is not
  needed. A single file also grows without bound and couples every tree-read to a
  full-file parse.
- `CollectionRepository.save` is last-write-wins (no optimistic versioning).
  Collections change rarely; a version counter can be added later without
  changing the caller interface.
- Dangling `parent_id` references are not the repository's problem. The
  `resolve_chain` function in the domain already fails closed on a broken tree
  (`BrokenCollectionTree`). The repository only guarantees well-formed single
  nodes.
