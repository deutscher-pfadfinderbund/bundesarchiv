# User flows

Status: LIVE DOCUMENT (2026-08-06). The screen-to-screen topology of the
product, one diagram per flow. Companion to `design-system.md` (how screens
look) and `part-4-web.md` (what each screen contains).

## Notation

Flows are **Mermaid flowcharts** checked into this file: machine-readable,
diffable, and rendered natively by GitHub — no build step, no image exports
to rot. Nodes are screens (with their route names), edges are user actions.

The **executable counterpart is the e2e journey suite**
(`tests/e2e/test_journeys.py`): every flow below names the journey test(s)
that walk it in a real browser. Gherkin/Cucumber was considered and not
adopted — a `.feature` layer would be a second, non-executing copy of the
journey suite (one proof per fact; the razor applies to specs too). If a
flow and its journey disagree, the journey is right and this file is stale.

Conventions: `[screen]` nodes carry the Django route name in parentheses;
`{decision}` nodes are branches the user or server takes; dashed edges are
htmx partial swaps (no navigation).

## 1. Search and find

The workbench is the home surface for every tier; what differs is what the
index lets each viewer see (leak filtering, not UI branching). Pane state
lives in the URL — every state below is a bookmarkable GET. Filtering is
the FILTER RAIL under the header (owner 2026-08-07, primary filter
interaction): facet dropdowns + removable active-filter chips, every one a
plain GET link. One-click entry (owner 2026-08-07): the Titel click IS the
detail navigation on every viewport; the pane is the explicit per-row
Vorschau action (a plain GET link — no JS interception), never a toll gate
on the primary loop.

```mermaid
flowchart TD
    WB["Workbench (workbench)\nledger + filter rail"] -->|"type query / Suchen"| WB
    WB -->|"rail filter click (?schlagwort=, ?bestand=, …)"| WB
    WB -->|"chip ✕ (filter removed)"| WB
    WB -->|"pagination (?seite=)"| WB
    WB -->|"Titel click"| DET["Detail (artikel-detail)"]
    WB -->|"row Vorschau (?artikel=<ulid>)\npane visible ≥1280px"| PANE["Workbench + preview pane\n(workbench)"]
    WB -->|"row Bearbeiten (pencil, archivist)"| EDIT["Edit form (artikel-bearbeiten)"]
    PANE -->|"Öffnen"| DET
    PANE -->|"Bearbeiten"| EDIT
    PANE -->|"✕ close (URL drops ?artikel)"| WB
    DET -->|"Zurück zur Suche"| WB
    DET -->|"breadcrumb (Bestand)"| WB
```

Journeys: `test_search_filter_and_open_pane`,
`test_detail_read_from_search_result`, `test_public_never_sees_a_draft`
(the tier-filtering proof).

## 2. Catalog an article (create → edit → read)

The core archivist loop. Create is deliberately minimal (Titel + Bestand);
everything else happens on the edit form, which is also where serial
cataloging (Kopieren) restarts the loop.

```mermaid
flowchart TD
    WB["Workbench"] -->|"+ Neuer Artikel"| NEU["Create step (artikel-neu)"]
    LAND["Create step, Bestand pre-selected\n(artikel-neu?bestand=…&angelegt=…)"] --> NEU
    NEU -->|"POST: draft created"| EDIT["Edit form (artikel-bearbeiten)"]
    EDIT -.->|"Medienart change (artikel-dokumenttypen)"| EDIT
    EDIT -.->|"Datierung blur → echo (artikel-datierung-echo)"| EDIT
    EDIT -->|"media upload / caption / reorder / remove"| EDIT
    EDIT -->|"Speichern"| SAVE{"CAS check"}
    SAVE -->|"clean"| READ["Read view (artikel-detail)"]
    SAVE -->|"'Inzwischen geändert' conflict"| EDIT
    SAVE -->|"validation error"| EDIT
    READ -->|"Bearbeiten"| EDIT
    READ -->|"Kopieren (artikel-kopieren)\nnew draft, Signatur focused"| EDIT
```

Journeys: `test_create_draft_lands_on_edit_form`,
`test_edit_and_save_redirects_to_read_view`,
`test_cas_conflict_second_saver_sees_panel`,
`test_kopieren_creates_draft_copy_signatur_focused`,
`test_failed_save_banner_leaves_speichern_clickable`,
`test_no_js_create_and_save_baseline` (the whole loop works without JS).

## 3. Publish (lifecycle)

Publish is ONE click (owner ruling 5, 2026-08-08). The over-exposure preview
GATE retired: the archivist reads who would gain sight the whole time they are
cataloging — the exposure statement is permanent chrome on the edit surface (in
the reader's sheet at/above 80rem, in the card beside Zugriff below it) — so
the fact that used to cost a preview round trip, a checkbox and a second
Veröffentlichen is simply on screen. The audience computation itself did not
change: it is still the domain's `preview()`, still archivist-only. v1 lifecycle
is binary; absence of the ENTWURF badge = published.

```mermaid
flowchart TD
    EDIT["Edit surface (draft)\nexposure statement on screen"] -->|"Veröffentlichen\n(POST artikel-lebenszyklus, CAS)"| READ["Read view, published"]
    DET["Detail (draft)"] -->|"Veröffentlichen"| EDIT
    READ -->|"Als Entwurf zurückziehen"| EDIT
```

Journeys: `test_publish_is_one_click_with_the_exposure_on_screen`,
`test_exposure_statement_is_on_screen_at_every_width`.

## 4. Delete

```mermaid
flowchart TD
    DET["Detail (artikel-detail)"] -->|"Löschen"| CONF["Confirm page (artikel-loeschen)"]
    CONF -->|"POST: delete"| WB["Workbench"]
    CONF -->|"abort (back link)"| DET
```

Journey: `test_loeschen_confirm_then_delete`.

## 5. Bulk edit (Sammelbearbeitung)

Selection is URL-borne (`?auswahl=<ulid>&auswahl=…`) so it survives
navigation and can be seeded by a link; DOM ticks are merged into the URL
set as the archivist pages. One field + one value per pass.

```mermaid
flowchart TD
    WB["Workbench, rows ticked\n(?auswahl=…)"] -->|"Feld + Wert wählen,\nÄnderung prüfen (POST)"| PRUEF["Confirm page\n(artikel-sammelbearbeitung)"]
    PRUEF -->|"validation error\n(selection carried in hidden inputs)"| PRUEF
    PRUEF -->|"Anwenden (POST)"| ERG["Result page\nper-article outcome list"]
    PRUEF -->|"Zurück (keeps ?auswahl)"| WB
    ERG -->|"back to workbench"| WB
```

Journeys: `test_bulk_select_confirm_apply`,
`test_bulk_url_seeded_selection_still_works`,
`test_bulk_fresh_ticks_survive_paging`.

Known parked defects: refresh on the result page re-POSTs (no PRG, #23);
the full rework of this flow is parked until after the UI wave (#25).

## 6. Manage Bestände

```mermaid
flowchart TD
    WB["Workbench"] -->|"+ Neuer Bestand"| BNEU["Create Bestand (bestand-neu)"]
    BNEU -->|"POST: created"| LAND["Create-article step,\nnew Bestand pre-selected + Hinweis"]
    LAND -->|"file the first article"| EDIT["Edit form"]
    WB -->|"(from Bestand context)"| BED["Rename Bestand\n(bestand-bearbeiten, Name only)"]
    BED -->|"POST: renamed"| WB
```

Journey: `test_create_bestand_then_file_an_article_under_it`.

## 7. Arrival and access (designed, not built)

How each viewer tier reaches the workbench, per ADR 0018 as amended by the
2026-08 rulings (`docs/requirements/owner-interview-2026-08.md`). Only the
dev viewer-switcher exists today; this flow is the auth wave's target (#11).

```mermaid
flowchart TD
    START{"How did they arrive?"} -->|"Keycloak login\n(members + archivists)"| OIDC["OIDC flow → Viewer cookie\nwith Keycloak groups"]
    START -->|"capability link\n(token mints Viewer cookie)"| CAP["Link-tier Viewer\n(possibly group-carrying)"]
    START -->|"no credential"| DENY["Login redirect —\nno public browsing exists"]
    OIDC --> WB["Workbench"]
    CAP --> WB
```

No journey yet — lands with the auth wave.
