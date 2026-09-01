# app — package map

Law: `Archive.canonical()` is the ONLY place in `src/` that builds the CANONICAL store from settings
— new code takes an `Archive`, never constructs a store. (`tasks.mirror_store()` builds the optional
WebDAV mirror from settings too; the mirror is a convenience copy, never a read path.) The write
shell's ordering is a contract (ADR 0013/0014): canonical CAS write, then index sync (whose failure
must NOT re-raise), then thumbnail and mirror enqueue (both swallowing). Form saves carry the form's
expected version straight to `save_article` — never through a retrying wrapper.

- `archive.py` — the one construction site for the canonical store + its repositories · interface: `Archive` (`.canonical()`, `.of()`, `.articles`, `.collections`, `.store`) · tests: `tests/app/test_archive.py`
- `articles.py` — Article write services: the canonical-then-index shell · interface: `save_article`, `create_article`, `copy_article`, `hard_delete_article` · tests: `tests/app/test_services.py`
- `collections.py` — Collection write service: canonical-then-subtree-index shell · interface: `create_collection`, `save_collection` · tests: `tests/app/test_services.py`
- `mirror.py` — WebDAV mirror replay/reconcile; speaks only the ObjectStore port · interface: `push_key`, `reconcile`, `ReconcileSummary` · tests: `tests/app/test_mirror.py`
- `tasks.py` — the background job seam (Procrastinate, ADR 0014); resolves its stores per job · interface: `reindex_article`, `reindex_subtree`, `full_rebuild`, `generate_thumbnail` · tests: `tests/app/test_tasks.py`
- `thumbnails.py` — thumbnail generation, content-hash-keyed local cache · interface: `generate_thumbnail` · tests: `tests/app/web/test_media.py` (no suite of its own — debt #5)
- `reindex.py` — deploy-startup config-version currency guard (ADR 0014) · interface: `ensure_index_current` · tests: `tests/app/test_config_version.py`
- `result.py` — the write services' result shapes · interface: `SaveResult`, `CreateResult` · tests: `tests/app/test_services.py`

Internal: `management/commands/ensure_index_current.py`
