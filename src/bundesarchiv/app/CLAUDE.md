# app — package map

Law: `Archive.canonical()` is the ONLY place in `src/` that builds the CANONICAL store from settings
— new code takes an `Archive`, never constructs a store. (`tasks.mirror_store()` builds the system of
record's WebDAV store from settings too, ADR 0020; it is never a read path.) The write shell's
ordering is a contract (ADR 0013/0014): canonical CAS write, then index sync (whose failure must NOT
re-raise), then thumbnail and mirror enqueue (both swallowing). ADR 0013's split is which entry point
you call: form saves carry the form's expected version straight to `save_article`, never
through the retrying `update_article` (which owns the load-mutate-save cycle for internal mutations).
Every write service takes `changed_by`, who is acting; the version it writes records it (ADR 0019).

- `archive.py` — the one construction site for the canonical store + its repositories · interface: `Archive` (`.canonical()`, `.of()`, `.articles`, `.collections`, `.store`) · tests: `tests/app/test_archive.py`
- `articles.py` — Article writes: canonical, then index · interface: `save_article`, `update_article`, `create_article`, `copy_article`, `delete_`/`restore_`/`hard_delete_article` · tests: `tests/app/test_services.py`
- `collections.py` — Collection write service: canonical-then-subtree-index shell · interface: `create_collection`, `save_collection` · tests: `tests/app/test_services.py`
- `mirror.py` — the push to the system of record, add-only but for hard delete (ADR 0020); port + injected record only · interface: `push`, `reconcile`, `delete_article`, `PushRecord` · tests: `tests/app/test_mirror.py`
- `push_record.py` — the push record in Postgres, derived state (ADR 0020) · interface: `PostgresPushRecord`, `InMemoryPushRecord` · tests: `tests/app/test_push_record.py`
- `tasks.py` — the background job seam (Procrastinate, ADR 0014); resolves its stores per job · interface: `reindex_article`, `reindex_subtree`, `full_rebuild`, `generate_thumbnail` · tests: `tests/app/test_tasks.py`
- `thumbnails.py` — thumbnail generation, content-hash-keyed local cache · interface: `thumbnail_path`, `generate_thumbnail` · tests: `tests/app/web/test_media.py` (no suite of its own)
- `reindex.py` — deploy-startup config-version currency guard (ADR 0014) · interface: `ensure_index_current` · tests: `tests/app/test_config_version.py`
- `legacy.py` — the legacy CSV → Article mapping for the one-time import; pure, no IO · interface: `ITEM_COLUMNS`, `bestand_names`, `map_item`, `plan`, `unknown_vocabulary`, `Report` · tests: `tests/app/test_legacy.py`
- `result.py` — the write services' result shapes · interface: `SaveResult`, `CreateResult`, `UpdateOutcome` (`Updated` | `Conflicted` | `Missing`) · tests: `tests/app/test_services.py`

Internal: `models.py`, `management/commands/ensure_index_current.py`, `management/commands/import_legacy.py`, `management/commands/rebuild_index.py`, `management/commands/rebuild_thumbnails.py`, `management/commands/verify.py`
