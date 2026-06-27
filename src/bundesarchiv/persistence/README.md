# Persistence layer

Two seams (full design + rationale: [ADR 0005](../../../docs/adr/0005-persistence-layer.md)):

- **`ObjectStore`** — a low-level blob port (`read` · `write_atomic` · `put_large` ·
  `list` · `exists` · `delete`), defined to the WebDAV/S3 lowest common denominator.
  The backend varies behind it; the rest of the app never touches it directly.
- **`ArticleRepository`** — the deep module everything uses. It owns the canonical-file
  protocol and sits on an injected `ObjectStore`.

## Files

| File | Role |
|------|------|
| `objectstore.py` | the `ObjectStore` Protocol + `validate_key` (key contract) + `is_reserved` (the dot-prefixed internal namespace excluded from `list()`) |
| `errors.py` | the only exceptions that cross the port: `ArchiveError` → `NotFound`, `Conflict` |
| `adapters/memory.py` | `InMemoryObjectStore` — the test fake; what `ArticleRepository` is exercised against |
| `adapters/localfs.py` | `LocalFsObjectStore` — **canonical** backend; atomic temp→fsync→rename, all backend errors mapped to `ArchiveError` via the `_backend` seam |
| `adapters/webdav.py` | `WebDavObjectStore` — the Nextcloud **mirror** (PUT-temp+MOVE), a sync adapter; transport errors wrapped via `_request` |
| `repository.py` | `ArticleRepository` — versioning, pinned write order, media, trash |
| `readme.py` | the README codec: `encode`/`decode` (Article ⇄ front-matter bytes) + a cheap `read_version` |

Every adapter passes one shared contract: `tests/persistence/test_objectstore_conformance.py`
(parametrized over all three — the WebDAV one against a real in-process server).

## Canonical layout (owned by `ArticleRepository`)

```
articles/<ulid>/README.md            front-matter + Markdown body + managed-by marker — the commit point
articles/<ulid>/media/<sha256>       content-addressed media blobs, write-once
articles/<ulid>/changes/<version>.json   append-only change records
.trash/articles/<ulid>/…             recoverable hard_delete destination (reserved → excluded from list)
```

Identity is the ULID; the key never embeds a slug ([ADR 0006](../../../docs/adr/0006-article-identity-and-key-naming.md)).
Write order is pinned: media → README (= commit) → changes. Concurrency is optimistic
(`save(article, expected_version)` → `Conflict` if stale). Deferred: `.snapshots/` and
the per-Article lock object (single-writer v1).
