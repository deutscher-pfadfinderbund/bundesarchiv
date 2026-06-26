# Persistence layer: ObjectStore + ArticleRepository; local-FS canonical with async Nextcloud mirror

## Module shape (two seams)

Two modules:

- **`ObjectStore`** — the low-level 6-op blob port (`read`, `writeAtomic`, `putLarge`, `list`, `exists`, `delete`). The **internal** seam, where only the storage *backend* varies.
- **`ArticleRepository`** — the **external** deep module the rest of the app uses: `load(ulid)`, `save(article, expected_version)`, `list_ulids()`, `hard_delete(ulid)`. It owns the entire canonical-file protocol — the `articles/<ulid>/{README.md, media/, changes/, .snapshots/}` layout, README.md (de)serialization + managed-by marker, the per-Article lock, the pinned write order (media → README.md = commit → changes → snapshot), optimistic versioning, media write-once — and sits on an `ObjectStore`.

Domain core, web views, reindex, and migration depend on **`ArticleRepository`** and never touch `ObjectStore`.

**Rejected:** the domain core talking to `ObjectStore` directly — shallow and leaky (key scheme, write-ordering, and lock protocol would spread across callers; fails the deletion test).

## ObjectStore is defined to the WebDAV/S3 lowest common denominator

No append, no rename, no OS-level lock. The per-Article lock is a **lock object in the store**; atomic write is PUT-temp+`MOVE` (chunked upload for large media) on WebDAV, temp→fsync→rename→fsync-dir on local-FS, multipart `PutObject` on S3. All adapters pass one shared **conformance suite**: a concurrent reader sees old-or-new (never partial); a process killed mid-write leaves prior-object-or-nothing at the final key; `list` excludes reserved temp/lock keys; `putLarge` finalize is all-or-nothing.

## Deployment topology (refines ADR 0002)

The app and Nextcloud **cannot share a host**, so:

- **Canonical = local filesystem** (`LocalFsObjectStore`). The app is the sole writer; writes never block on Nextcloud and are not coupled to its uptime or ~yearly major-version upgrades.
- **Nextcloud = an async, one-way WebDAV mirror** (off-host copy + human browse). After each `ArticleRepository.save()` commits locally, a Postgres-backed job replays that Article's files to the WebDAV `ObjectStore` (or an external one-way `rclone`/`nextcloudcmd` sync does the same). Eventually consistent; a lagging mirror is harmless and self-heals on the next push. Humans only **read** in Nextcloud (never write back → the sole-writer invariant holds). The WebDAV adapter is therefore a first-class, exercised component — the mirror target — even though it is not the canonical backend.
- **Backup / DR = restic** (off-site, encrypted, rehearsed restore) — the real durability mechanism; Nextcloud is not a backup tool.
- Losing some Nextcloud file-versions is acceptable: metadata history lives in `changes/` + `.snapshots/`, and media is write-once.

Adapters: `LocalFsObjectStore` (canonical, v1), `WebDavObjectStore` (Nextcloud mirror, first-class), `S3ObjectStore` (future), `InMemoryObjectStore` (test fake).

## Consequences

- `ArticleRepository` is tested through its interface over an `InMemoryObjectStore` fake (no disk); `LocalFsObjectStore` and `WebDavObjectStore` are each verified against the `ObjectStore` conformance suite; domain core and web accept an injected `ArticleRepository`.
- The mirror is one-way and idempotent; reconciliation is just a re-push from canonical — no conflict resolution, because Nextcloud is read-only to humans.
- Keeps ADR 0002's "Nextcloud never canonical, never human-writable" stance; refines only the connection mechanism.
