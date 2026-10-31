# Search UI review 2026-10-18 — a record, frozen

Status: RECORD, frozen 2026-10-31. An agent's notes from the review of the search units
(Lesesaal, suggestions) with the owner, 2026-10-18; no quotes. Binds nothing (root
`CLAUDE.md`, "Decisions and records"); the code and its tests are what holds.

1. **A table sort carries into the Lesesaal, and the Lesesaal shows it.** Switching views keeps
   `sort=`; the Lesesaal states the active sort visibly, so a non-relevance order never looks like
   relevance.
2. **Picking a suggested value keeps the current filters.** A pick from the Autor, Ort or
   Schlagworte group adds that value as a filter on top of the filters already set; the typed
   text it completed is not kept as a query. The groups and their counts respect the current
   filters, so a count matches what the pick returns.
3. **Suggestion options are real links.** Each option is an `<a href>`, so middle-click,
   Cmd-click and "open in new tab" work; the keyboard combobox behaviour stays.
4. **The suggestion list dismisses like a normal combobox.** It may overlay the page below it and
   closes on Escape or a click outside; it does not close by itself when the live results update.
