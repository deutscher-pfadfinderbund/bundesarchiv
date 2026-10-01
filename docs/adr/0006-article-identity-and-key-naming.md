# Article identity is a ULID; the canonical key is ULID-only; the slug is display-only

> **Amended (proposed 2026-09-24):** media keys are named files, `media/<cleaned filename>`,
> not content hashes — [ADR 0019](0019-canonical-layout-v1.md). Folders stay ULID-only.

## Context

The Part 1 plan named the key-naming policy as "NFC lowercase ASCII slug + ULID" without
pinning where the slug goes. Read literally as a key segment (`articles/<slug>-<ulid>/`),
a title- or ref_code-derived slug would change whenever the human renames the Article —
moving its files and breaking the stable-identity invariant CONTEXT.md states plainly
(the *Reference code* is "**not** the Article's stable identity (which is an internal ULID)").

## Decision

- **Identity = ULID.** Each Article is identified by a ULID (Crockford base32, 26 chars,
  lexicographically sortable), minted at creation via `domain.identity.new_ulid()`.
- **The canonical key is ULID-only and stable** — `articles/<ulid>/…`. It never embeds a
  slug. Renaming an Article never moves its files.
- **Media keys are content-addressed** (sha256), also slug-free and write-once.
- **A slug is never identity** — a title-derived slug changes with the title and is
  non-unique, so nothing load-bearing may depend on one. (The `slugify()` display helper
  first named here was deleted unused, 2026-10-01.)

## Consequences

- ULID minting and validation are **domain** primitives (`domain/identity.py`); the
  persistence layer treats the ULID as an opaque key segment. Traversal safety is enforced
  by `ObjectStore.validate_key`; strict ULID-format enforcement is the **creator's** job
  (the Article factory, Part 2), not the repository's.
- Stable keys mean stable Nextcloud-mirror paths and clean restic history across renames.
- **Rejected:** `articles/<slug>-<ulid>/` for human-browsable directories — it trades the
  stable-identity invariant for a browsing convenience, and Nextcloud browsing is a
  convenience (humans only read the mirror), not a contract worth that cost.
