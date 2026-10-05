# app/web — package map

Law: `viewer_of(request)` is THE request→Viewer trust boundary — no view resolves identity another
way. Deny is a plain 404 revealing and changing nothing (`assert_denied` is the test contract).
Every route is enumerated by the leak matrix (`tests/app/web/test_leak_matrix.py`) — a new route
must join its contract table. UI is German, code identifiers English (`CONTEXT.md`). ADR 0013's `Conflict` is caught at exactly four form
sites here (`catalog.py`, `collection_views.py`, the delete confirm, restore), each re-displaying the winner; every non-form
mutation goes through `app.articles.update_article` and matches on its outcome union instead.
The edit form has ONE render (`catalog_views.EditSurface`), always built from the SAVED article and
parameterised by a closed overlay union — a new panel joins that union, never a second context build.
An archivist gate is `isinstance(viewer_of(request), Archivist)`, and a write route passes that
Archivist's `username` on as `changed_by` (ADR 0019); a new write route joins `test_changed_by.py`
and `test_index_lag.py` (it shows a lagging index, ADR 0014).

- `viewers.py` — Viewer, request kind, responses · interface: `viewer_of`, `request_kind`, `render_screen`, `redirect_to`, `panel_response`, `TokenCookieMiddleware` · tests: `test_*viewer*.py`, `test_request_kind.py`
- `auth_views.py` — the login surface: Keycloak in, two token cookies out (ADR 0018) · interface: `login`, `oidc_callback`, `logout`, `login_redirect` · tests: `tests/app/web/test_auth_views.py`
- `keycloak.py` — the ONE place that talks to the realm; failure is `None` (ADR 0018) · interface: `authorization_url`, `verify_access`, `fetch_tokens`, `refresh`, `logout_url` · tests: `tests/app/web/test_keycloak_*.py`
- `oidc.py` — validated OIDC claims → Viewer, least privilege on an unknown shape · interface: `viewer_from_claims`, `ARCHIVIST_REALM_ROLE` · tests: `tests/app/web/test_oidc_claims.py`
- `anonymous_gate.py` — the anonymous gate: one middleware check, never a per-view decorator (ADR 0018) · interface: `AnonymousGateMiddleware` · tests: `tests/app/web/test_anonymous_gate.py`
- `slow_requests.py` — one WARNING record per request over `BUNDESARCHIV_SLOW_REQUEST_MS`, by route name · interface: `SlowRequestMiddleware` · tests: `tests/app/web/test_slow_requests.py`
- `article_auth.py` — Article-level authorization for full-Article render paths · interface: `resolve_visible_detail`, `DetailResolution` · tests: `tests/app/web/test_detail_resolver.py`, `test_detail.py`
- `browse.py` — pure URL-as-state algebra for the workbench (no IO) · interface: `parse_query`, `ParsedQuery`, `with_param`, `without_param` · tests: `tests/app/web/test_browse_params.py`, `test_browse_links.py`
- `browse_views.py` — the list, detail and Papierkorb routes · interface: `workbench`, `article_detail`, `choose_columns`, `trash`, `preset_url` · tests: `test_workbench.py`, `test_choose_columns.py`, `test_trash.py`
- `start.py` — start page: areas (a function + a partial each) on one grid, one tuple per role · interface: `start`, `Area`, `ARCHIVIST`, `MEMBER` · tests: `tests/app/web/test_start.py`
- `ledger.py` — the ledger's columns and rows: one registry the chooser offers and the ledger prints (debt #8) · interface: `COLUMNS`, `build`, `chosen`, `cookie_value` · tests: `tests/app/web/test_ledger.py`
- `catalog.py` — the cataloging form's leak-sensitive parse layer + save controller · interface: `parse_edit_form`, `parse_audience`, `parse_lines`, `save_catalog_form`, `apply_captions` · tests: `test_catalog_form.py`
- `card.py` — THE record card field registry: every field declared once, joined to a render (debt #2) · interface: `FIELDS`, `CardRow`, `card_fields` · tests: `tests/app/web/test_catalog_edit.py`
- `panels.py` — the small forms as tool panels; a leaf, so the header builds them (debt #24) · interface: `FormPanel`, `header_panels`, the three `*_panel` builders · tests: `test_collection_entrypoints.py`
- `catalog_views.py` — cataloging routes, the card on ONE `EditSurface` · interface: `article_create`/`_edit`/`_copy`/`_delete`/`_delete_permanently`/`_restore`, `tag_suggestions` · tests: `test_catalog_*.py`
- `collection_views.py` — Bestand management routes · interface: `collection_create`, `collection_edit` · tests: `tests/app/web/test_collection_*.py`
- `bulk.py` — bulk-edit core: allowlist, Feld-chooser context, per-article CAS apply · interface: `FIELDS`, `apply_bulk`, `is_allowed_field`, `feldwahl_context` · tests: `tests/app/web/test_bulk_core.py`, `test_bulk.py`
- `bulk_views.py` — bulk-edit confirm/commit routes · interface: `article_bulk_edit` · tests: `tests/app/web/test_bulk_views.py`, `test_bulk_links.py`
- `media.py` — the media-serving seam: X-Accel in prod, port-streamed in dev, local thumbnail cache (ADR 0017) · interface: `media_response`, `thumbnail_response` · tests: `tests/app/web/test_media.py`
- `media_views.py` — media entry points, `can_view` before any blob probe · interface: `serve_media`, `serve_thumbnail`, `not_found` (the one 404 page) · tests: `tests/app/web/test_media.py`
- `vocab.py` — controlled vocabulary + the German spellings (Sichtbarkeit, dates, sizes) · interface: `is_valid_pair`, `SICHTBARKEIT_OPTIONS`, `exposure_label`, `datierung_parts`, `human_size` · tests: `test_vocab.py`
- `landing.py` — state a redirect hands on · interface: `noting_lag`, `index_lagging`, `copy_url`, `bestand_created_url`, `preselected_bestand`, `created_bestand_name` · tests: `test_index_lag.py`, `test_collection_*.py`
- `bestand.py` — per-request Bestand chooser: one ordering, one refusal · interface: `BestandChooser.of` + `options`/`accepts`/`error`/`name_of`/`names`/`by_ulid`/`chain_of` · tests: `tests/app/web/test_bestand.py`

Internal: `dev.py`, `dev_urls.py`, `urls.py`, `components_demo.py`, `layouts_demo.py`
