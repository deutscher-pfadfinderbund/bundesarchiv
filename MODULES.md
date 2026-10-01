# Module map

One screen: which modules exist, per package. Rows (responsibility, interface, tests) live in each
package's `CLAUDE.md`; this file is the table of contents. Detail discipline: indices hold
addresses, not facts — a fact's home is the module docstring (interface contract), an ADR (why), or
`CONTEXT.md` (domain language). Kept honest by `tests/test_module_map.py`. How to update:
the `update-module-map` skill.

## domain — pure core: values, access decisions; no IO, no Django
`models.py`, `access.py`, `audience.py`, `collections.py`, `viewer.py`, `identity.py`, `edtf.py` · rows + law: `src/bundesarchiv/domain/CLAUDE.md`

## persistence — files-canonical storage: README codecs, repositories, the ObjectStore port; no Django
`repository.py`, `collections.py`, `readme.py`, `collection_readme.py`, `fixity.py`, `objectstore.py`, `adapters/localfs.py`, `adapters/memory.py`, `adapters/webdav.py` · rows + law: `src/bundesarchiv/persistence/CLAUDE.md`

## index — derived, disposable Postgres search index
`indexer.py`, `query.py`, `scope.py`, `models.py` · rows + law: `src/bundesarchiv/index/CLAUDE.md`

## app — application services: the write shell, background jobs, the Archive handle
`archive.py`, `after_write.py`, `articles.py`, `collections.py`, `jsonlog.py`, `legacy.py`, `mirror.py`, `push_record.py`, `tasks.py`, `thumbnails.py`, `pdf_preview.py`, `reindex.py`, `result.py` · rows + law: `src/bundesarchiv/app/CLAUDE.md`

## app/web — Django+HTMX surface: views, auth seam, form parsing, media serving
`viewers.py`, `auth_views.py`, `keycloak.py`, `oidc.py`, `anonymous_gate.py`, `article_auth.py`, `browse.py`, `browse_views.py`, `ledger.py`, `catalog.py`, `card.py`, `panels.py`, `catalog_views.py`, `collection_views.py`, `bulk.py`, `bulk_views.py`, `media.py`, `media_views.py`, `vocab.py`, `landing.py`, `bestand.py` · rows + law: `src/bundesarchiv/app/web/CLAUDE.md`
