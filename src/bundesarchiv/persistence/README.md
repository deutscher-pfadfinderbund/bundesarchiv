# Persistence layer

Two seams (full design + rationale: [ADR 0005](../../../docs/adr/0005-persistence-layer.md)):

- **`ObjectStore`** — a low-level blob port (its operations: `objectstore.py`), defined to
  the WebDAV/S3 lowest common denominator.
  The backend varies behind it; the rest of the app never touches it directly.
- **`ArticleRepository`** — the deep module everything uses. It owns the canonical-file
  protocol and sits on an injected `ObjectStore`.

## Files

| File | Role |
|------|------|
| `objectstore.py` | the `ObjectStore` Protocol + `ObjectEntry` (key, size, version) + `validate_key` (key contract) + `validate_prefix` (prefix delete) + `is_reserved` (the dot-prefixed internal namespace excluded from `list()`) |
| `errors.py` | the only exceptions that cross the port: `ArchiveError` → `NotFound`, `AlreadyExists`, `Conflict`, `Busy` |
| `adapters/memory.py` | `InMemoryObjectStore` — the test fake; what `ArticleRepository` is exercised against |
| `adapters/localfs.py` | `LocalFsObjectStore` — **canonical** backend; temp→fsync, then `rename` (replace) or `link` (create-only), all backend errors mapped to `ArchiveError` via the `_backend` seam |
| `adapters/webdav.py` | `WebDavObjectStore` — the Nextcloud backend (plain `PUT`, bounded retries on `423` and a transient `404`/`409`), a sync adapter; transport errors wrapped via `_request` |
| `repository.py` | `ArticleRepository` — key scheme, media names, trash |
| `collections.py` | `CollectionRepository` — the same for Collections |
| `_writer.py` | the save protocol both share: CAS under `WRITER_LOCK`, history, commit |
| `readme.py` | the README codec: `encode`/`decode` (Article ⇄ front-matter bytes) + a cheap `read_version` |
| `collection_readme.py` | the Collection README codec |
| `_change.py` | the change record's `changed_at` / `changed_by` fields, shared by both codecs |

Every adapter passes one shared contract: `tests/persistence/test_objectstore_conformance.py`
(parametrized over all three — the WebDAV one against a real in-process server).

## Canonical layout (owned by the repositories)

```
articles/<ulid>/README.md             front-matter + Markdown body + managed-by marker — the commit point
articles/<ulid>/history/<version>.md  every replaced README, byte for byte, create-only
articles/<ulid>/media/<name>          media files under their own name, write-once (ADR 0019)
collections/<ulid>/README.md          the Collection's commit point
collections/<ulid>/history/<version>.md
.trash/articles/<ulid>/…              recoverable hard_delete destination (reserved → excluded from list)
```

Identity is the ULID; the key never embeds a slug ([ADR 0006](../../../docs/adr/0006-article-identity-and-key-naming.md)).
Write order is pinned ([ADR 0019](../../../docs/adr/0019-canonical-layout-v1.md)): media →
the current README copied to `history/<n>.md` → the new README (= commit). Concurrency is
optimistic (`save(article, expected_version)` → `Conflict` if stale, nothing written).
