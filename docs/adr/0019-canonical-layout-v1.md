# Canonical layout v1: version history, named media files, a fixity check

Status: Proposed (2026-09-24). Amends ADR 0005 (history, `changes/`, `.snapshots/`),
ADR 0006 (media keys; its ULID-only folders stand), ADR 0013 (media exemption, secondary
history) and ADR 0015 (media layout). ADR 0018 supplies `changed_by`: the Archivist's Keycloak username.

> **Amended 2026-09-27:** the README front matter gains an optional `added_at` (ISO 8601, UTC,
> whole seconds): when the record entered the archive (*Hinzugefügt am*). The legacy import fills
> it from `pub_date`; a new Article gets the time it was created; no edit changes it. It is a field
> of the Article, not version 1's `changed_at`: the date is a fact of the record, while `changed_at`
> says when a file was written. Setting version 1's `changed_at` to 2017 would falsify that, and a
> field survives a later history rewrite or layout migration. Absent means unknown (a README
> written before the field existed).

> **Amended 2026-10-01 (ADR 0022):** the front matter gains an optional `deleted_at` / `deleted_by`
> pair, spelled like `changed_at` / `changed_by`: the Article is in the Papierkorb, deleted by that
> Archivist at that time. The pair is the change record of the version that set it. Both are present
> or both absent; absent means not deleted (a README written before the fields existed).

## Context

The canonical tree was compared with two preservation layouts (sources below). The
comparison found four gaps, all measured on the legacy import of 2026-09-24:

- **No history.** ADR 0005 states "metadata history lives in `changes/` + `.snapshots/`".
  `changes/<version>.json` holds only `{"ulid": …, "version": …}`, and `.snapshots/` was
  never built. Every `save` replaces `README.md`, so earlier states are gone. A bulk edit
  over hundreds of Articles cannot be undone, and backup is out of scope
  (`docs/requirements/owner-interview-2026-08.md`, addendum 2026-09-19).
- **Nameless media.** Blobs live at `media/<sha256>`, with no name and no extension. The
  name exists only in the front matter, so a file browser cannot open the file.
- **No self-description.** Nothing in the tree explains the layout to a reader without the
  app. (Deferred, see "Layout version".)
- **No fixity check.** SHA-256 values are stored and never compared against the bytes.

Legacy import figures: 2506 Articles; 843 with media (569 with one file, 256 with two,
18 with three); 5.0 GB of media; README size 587 bytes on average, 1688 bytes at most;
no Article with two media names that are equal ignoring case.

## Prior work

As published on 2026-09-24:

- **OCFL 1.1** (<https://ocfl.io/1.1/spec/>). An object is an `inventory.json` with a
  digest sidecar, plus immutable version directories `v1/`, `v2/`, …. The name a person
  sees (logical path) is separate from where the bytes sit (content path). The two are
  linked "with a digest of its contents, rather than its filename". Digests are `sha512` by
  default, and `sha256` is allowed. Content that did not change is not stored again. A
  storage root declares itself with a marker file `0=ocfl_1.1`. Extension 0005
  ("Mutable HEAD") keeps one changeable current version beside the frozen ones.
- **BagIt**, RFC 8493. Payload files keep their original names under `data/`, next to a
  `manifest-sha256.txt`.

Taken from them: the name is separate from the bytes (the README front matter is the
inventory), content paths are readable, past versions are frozen, a layout marker once the
layout changes, and fixity is checked.

Not taken: full OCFL. The current state would spread across version directories, and the
browse copy needs the current `README.md` at a fixed path.

## Decision

### Layout

```
articles/<ulid>/README.md               the current version — the commit point
articles/<ulid>/history/<version>.md    every replaced version, frozen
articles/<ulid>/media/<filename>        media under its own name, write-once
collections/<ulid>/README.md
collections/<ulid>/history/<version>.md
```

### History and audit

- The README front matter gains two fields: `changed_at` (ISO 8601, UTC) and
  `changed_by` (the Keycloak username, owner 2026-09-24; `unbekannt` if a token ever
  carries none). Each version therefore carries
  its own author, and the history is the audit trail (owner, 2026-09-24): version 1 says
  who created the Article, the current README who changed it last. No field for the kind
  of change (owner, 2026-09-24: not needed).
- Save order: media, then the current README copied byte for byte to
  `history/<n>.md`, then the new README (the commit).
  - A crash before the commit leaves the old README in place. The retry finds an
    identical history file and goes on.
- The history write is create-only. An existing history file is never replaced.
- Collections follow the same rule. A collection edit is an access change (ADR 0013).
- `changes/` is dropped. `history/` replaces the `.snapshots/` provision of ADR 0005.

### Media names

- A file is stored under the name it was uploaded with, cleaned:
  - `/ \ : * ? " < > |` and control characters replaced by `_`
  - leading and trailing spaces and dots stripped
  - Unicode NFC. The StorageShare normalizes names to NFC itself (measured 2026-09-24):
    a `PUT` under the NFD form of a name replaced the NFC file.
  - at most 250 bytes of UTF-8, with the extension kept. The StorageShare accepts
    250 bytes and answers `400` from 251 on, measured 2026-09-24 with ASCII and with
    multi-byte names.
  - A name that cleans to nothing (`...`, only spaces) is refused with a German error,
    not renamed (owner, 2026-09-24).
- A name is written once and never replaced. Names are compared after NFC and ignoring
  case. The StorageShare itself keeps `Scan.pdf` and `scan.pdf` apart (measured
  2026-09-24). A copy on a macOS or Windows disk would not.
- Name taken by the same bytes: the existing file is reused.
- Name taken by different bytes (a replaced scan, or a leftover from a crashed upload):
  the file is stored as `<stem>.<first 8 hex digits of the sha256>.<ext>`. If that name
  is taken too, the full hash is used.
- The media entry in the front matter records the stored name only when it differs from
  `filename`, following the omit-empty rule of ADR 0015. `content_hash` stays the link
  between entry and file, and the fixity value.
- A file dropped from an Article stays in `media/`, because older versions refer to it.
  The README lists the current files.
- Media URLs stay `/media/<ulid>/<content_hash>`. Thumbnails stay keyed by hash. The
  immutable caching of ADR 0017 is unaffected.
- The `X-Accel-Redirect` value percent-encodes each key segment. nginx decodes the
  header as a URI, and cleaned names keep `%`, spaces and umlauts.

### Storage port additions

The port gains semantics, not backend features. Each adapter maps them onto its backend,
and the shared conformance suite pins the same behaviour for every adapter, concurrency
included.

- **`create`**: writes a key only if it does not exist yet. Otherwise it raises
  `AlreadyExists`. Of several concurrent creates of one key, exactly one succeeds.
- **Listing with metadata**: each key comes with its `size` and an opaque `version`
  token. The token changes whenever the bytes change and says nothing else. A write
  returns the token of what it wrote.
- **Deferred to stage B of ADR 0020**: a conditional replace against a `version` token.
  Stage A has no consumer for it.
- **`Busy`**: a retryable error for a backend that refuses under contention.
- **Prefix delete**: removes everything under a prefix (ADR 0020 hard delete). It refuses a
  prefix of fewer than two segments, so no call can take `articles/` or the whole root.
- **Streamed read**: a read that hands out the bytes without holding the whole object in
  memory, on every adapter. The WebDAV adapter materializes today
  (`open_stream` wraps `read`).

History files and media files are written with `create`, so no file is ever
overwritten. Names stay case-insensitive for portability (owner, 2026-09-24): the name
choice lists `media/` first and compares after NFC and ignoring case. Two uploads racing
for names that differ only in case could both succeed; nothing is overwritten, and the
case is accepted as very unlikely (owner, 2026-09-24).
How an adapter implements these operations belongs to that adapter. The WebDAV mapping
is recorded in `docs/nextcloud-webdav-notes.md`.

### Streaming upload

- Django keeps large uploads in a temp file on disk. `add_media` hashes that file in one
  pass, picks the name, then streams it with the create-only write. No step holds the
  file in RAM.
- This closes tech-debt #18.

### Layout version

- A tree without a layout marker is layout 1. A future layout 2 writes
  `0=bundesarchiv_layout_2` at the root, in the naming style of OCFL's marker, and its
  migration decides what an older app image may do with the tree (owner, 2026-09-24).
- A `LAYOUT.md` explaining the tree to archivists is deferred: useful, not needed for
  deployment 1 (owner, 2026-09-24).

### Fixity

- `manage.py verify` does four things:
  - re-hashes every media file against its front matter
  - parses every README
  - reports files no README version refers to
  - reports references to files that do not exist
- It reports only and never repairs.
- The worker runs it monthly. The legacy import runs it once at the end.

## Considered options

- **Hash in the path**, `media/<sha256>/<filename>` or `<name>.<hash8>.<ext>` for every
  file. Rejected: write-once comes from create-only writes. A hash in every name is noise
  that 843 of 843 imported Articles would carry for a collision none of them has.
- **Counter suffix**, `scan (2).pdf`. Rejected by the owner (2026-09-24). A hash suffix
  says why the name differs.
- **OCFL version directories.** See Prior work.
- **Git as the history layer** (deferred in ADR 0002). Rejected: 5.0 GB of binary media,
  and a tool dependency for reading the history.

## Consequences

- The README codec gains two audit fields and the optional stored name. The codec
  round-trip tests cover both.
- `ArticleRepository` and `CollectionRepository` write history. The thumbnail job gets
  the Article instead of searching by hash, which retires `find_blob`.
- History costs about one README per edit: 587 bytes on average.
- The legacy import writes a fixed `changed_by` label and is re-run before deployment 1. Nothing
  is deployed yet, so no migration is needed.
- Readable folder names remain an open question (ADR 0006).
