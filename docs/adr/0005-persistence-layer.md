# Persistence layer: ObjectStore + ArticleRepository; the canonical store is ADR 0020's

Status: Accepted (2026-06-26). Amended by 0013 (2026-07-04), 0019 (2026-09-24); topology superseded by 0020 (2026-09-24).

## Module shape (two seams)

Two modules:

- **`ObjectStore`** — the low-level blob port. The **internal** seam, where only the storage *backend* varies.
- **`ArticleRepository`** — the **external** deep module the rest of the app uses. It owns the entire canonical-file protocol — README.md (de)serialization, README last as the commit, version CAS under one writer lock (0013), media write-once — and sits on an `ObjectStore`.

Domain core, web views, reindex, and migration depend on **`ArticleRepository`** and never touch `ObjectStore`.

**Rejected:** the domain core talking to `ObjectStore` directly — shallow and leaky (key scheme, write-ordering, and lock protocol would spread across callers; fails the deletion test).

## ObjectStore is defined to the WebDAV/S3 lowest common denominator

No append, no rename, no OS-level lock. All adapters pass one shared **conformance suite**.

## Deployment topology

Replaced by [ADR 0020](0020-storage-topology-system-of-record.md), which decides which store is canonical.

Adapters: `LocalFsObjectStore`, `WebDavObjectStore` (the system of record, 0020), `S3ObjectStore` (future), `InMemoryObjectStore` (test fake).

## Consequences

- `ArticleRepository` is tested through its interface over an `InMemoryObjectStore` fake (no disk); `LocalFsObjectStore` and `WebDavObjectStore` are each verified against the `ObjectStore` conformance suite; domain core and web accept an injected `ArticleRepository`.
- The canonical store and the mirror are decided in ADR 0020, which reverses ADR 0002's "Nextcloud never canonical".
