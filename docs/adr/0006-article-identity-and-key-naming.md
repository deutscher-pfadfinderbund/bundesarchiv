# Article identity is a ULID; the canonical key is ULID-only; the slug is display-only

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
- **The slug is a display helper, not identity** — `domain.identity.slugify()` (NFKD →
  drop non-ASCII → lowercase → hyphenate) produces human-readable download filenames, URL
  slugs (web layer, Part 4), and browse labels. It is intentionally lossy (ß is dropped)
  and non-unique; nothing load-bearing depends on it.

## Consequences

- ULID minting and validation are **domain** primitives (`domain/identity.py`); the
  persistence layer treats the ULID as an opaque key segment. Traversal safety is enforced
  by `ObjectStore.validate_key`; strict ULID-format enforcement is the **creator's** job
  (the Article factory, Part 2), not the repository's.
- Stable keys mean stable Nextcloud-mirror paths and clean restic history across renames.
- **Rejected:** `articles/<slug>-<ulid>/` for human-browsable directories — it trades the
  stable-identity invariant for a browsing convenience, and Nextcloud browsing is a
  convenience (humans only read the mirror), not a contract worth that cost.
