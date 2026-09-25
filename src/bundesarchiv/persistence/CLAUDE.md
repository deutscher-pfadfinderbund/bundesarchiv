# persistence — package map

Law: this package NEVER imports Django or reads settings (ADR 0005) — construction from settings
lives in `app/archive.py`. The README files are canonical; everything else is derived. Both
repositories save through `_writer.commit`: CAS under `WRITER_LOCK` (ADR 0013), the replaced README
kept under `history/` (ADR 0019), then the commit. All three ObjectStore adapters are parametrized
into the one shared conformance suite (`tests/persistence/test_objectstore_conformance.py`) — never
test an adapter its own way; adapter-specific files cover only what the port cannot state.

- `repository.py` — the deep module for Article persistence (ADR 0005/0019) · interface: `ArticleRepository`, `Stored`, `cleaned_name` · tests: `tests/persistence/test_article_repository.py`, `test_history.py`
- `collections.py` — CollectionRepository (ADR 0010/0013) · interface: `CollectionRepository`, `StoredCollection` · tests: `tests/persistence/test_collection_repository.py`, `test_history.py`
- `readme.py` — Article README codec: Markdown+front-matter ↔ Article (ADR 0005/0006) · interface: `encode`, `decode`, `read_version` · tests: `tests/persistence/test_readme.py`
- `collection_readme.py` — Collection README codec (ADR 0010) · interface: `encode_collection`, `decode_collection` · tests: `tests/persistence/test_collection_readme.py`
- `objectstore.py` — the ObjectStore port: minimal blob interface + key validation · interface: `ObjectStore`, `ObjectEntry`, `validate_key`, `is_reserved` · tests: `tests/persistence/test_objectstore_conformance.py`
- `adapters/localfs.py` — local-filesystem adapter, the canonical v1 backend · interface: `LocalFsObjectStore` · tests: conformance + `tests/persistence/test_localfs.py` (SIGKILL durability)
- `adapters/memory.py` — in-memory adapter, the test fake · interface: `InMemoryObjectStore` · tests: conformance
- `adapters/webdav.py` — WebDAV adapter, the Nextcloud mirror backend (ADR 0005/0007) · interface: `WebDavObjectStore` · tests: conformance + `tests/persistence/test_webdav.py`, `test_mirror_webdav.py`

Internal: `_writer.py`, `_change.py`, `errors.py`
