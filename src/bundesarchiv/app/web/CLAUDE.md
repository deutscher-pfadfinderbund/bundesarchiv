# app/web — package map

Law: `viewer_of(request)` is THE request→Viewer trust boundary — no view resolves identity another
way. Deny is a plain 404 revealing and changing nothing (`assert_denied` is the test contract).
Verbatim German UI strings are user contract (`tests/CLAUDE.md`). Every route is enumerated by the
leak matrix (`tests/app/web/test_leak_matrix.py`) — a new route must join its contract table. UI is
German, code identifiers English (`CONTEXT.md`). ADR 0013's `Conflict` is caught at exactly two form
sites here (`catalog.py`, `collection_views.py`), both re-displaying the winner; every non-form
mutation goes through `app.articles.update_article` and matches on its outcome union instead.

- `viewers.py` — the request→Viewer trust boundary + screen-chrome facts · interface: `viewer_of`, `render_screen`, `encode_viewer` · tests: `tests/app/web/test_viewer_of.py`
- `article_auth.py` — Article-level authorization for full-Article render paths · interface: `resolve_visible_article`, `resolve_visible_detail` · tests: `tests/app/web/test_detail_resolver.py`, `test_detail.py`
- `browse.py` — pure URL-as-state algebra for the workbench (no IO) · interface: `parse_query`, `ParsedQuery`, `with_param`, `without_param` · tests: `tests/app/web/test_browse_params.py`, `test_browse_links.py`
- `browse_views.py` — workbench + detail routes: search, browse, read · interface: `workbench`, `article_detail` · tests: `tests/app/web/test_workbench.py`
- `catalog.py` — the cataloging form's parse/validate layer (leak-sensitive, pure) + the save controller · interface: `parse_edit_form`, `save_catalog_form`, `ParseResult` · tests: `tests/app/web/test_catalog_form.py`
- `catalog_views.py` — cataloging routes + THE record-card field registry (`_FIELDS`) · interface: `article_create`, `article_edit`, `article_copy`, `article_delete` · tests: `tests/app/web/test_catalog_*.py`
- `collection_views.py` — Bestand management routes · interface: `collection_create`, `collection_edit` · tests: `tests/app/web/test_collection_*.py`
- `bulk.py` — bulk-edit core: field allowlist + per-article CAS application · interface: `FIELDS`, `BulkField`, `apply_bulk`, `is_allowed_field` · tests: `tests/app/web/test_bulk_core.py`, `test_bulk.py`
- `bulk_views.py` — bulk-edit confirm/commit routes · interface: `article_bulk_edit` · tests: `tests/app/web/test_bulk_views.py`, `test_bulk_links.py`
- `media.py` — the media-serving seam: X-Accel in prod, port-streamed in dev, local thumbnail cache (ADR 0017) · interface: `media_response`, `thumbnail_response` · tests: `tests/app/web/test_media.py`
- `media_views.py` — authorized media entry points (`can_view` before any blob probe — ordering is load-bearing) · interface: `serve_media`, `serve_thumbnail` · tests: `tests/app/web/test_media.py`
- `vocab.py` — controlled vocabulary + German label echo for the form · interface: `media_type_options`, `document_types_for`, `is_valid_pair` · tests: `tests/app/web/test_vocab.py`

Internal: `dev.py`, `dev_urls.py`, `urls.py`, `components_demo.py`, `layouts_demo.py`
