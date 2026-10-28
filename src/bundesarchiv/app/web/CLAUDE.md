# app/web — package law

Law: `viewer_of(request)` is THE request→Viewer trust boundary — no view resolves identity another way. Deny is a plain 404
revealing and changing nothing (`assert_denied` is the test contract). Every route is enumerated by the leak matrix
(`tests/app/web/test_leak_matrix.py`) — a new route must join its contract table. UI is German, code identifiers English
(`CONTEXT.md`). A form save catches ADR 0013's `Conflict` and re-displays the winner; every other mutation goes through
`app.articles.update_article` and matches on its outcome union.
The edit form has ONE render (`catalog_views.EditSurface`), always built from the
SAVED article and parameterised by a closed overlay union — a new panel joins that union, never a second context build. An
archivist gate is `isinstance(viewer_of(request), Archivist)`, and a write route passes that Archivist's `username` on as
`changed_by` (ADR 0019); a new write route joins `test_changed_by.py` and `test_index_lag.py` (it shows a lagging index, ADR
0014).
