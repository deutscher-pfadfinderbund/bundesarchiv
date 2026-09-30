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
detail navigation on every viewport. The preview is paused (owner
2026-09-30): the list shows no Vorschau control, and the pane opens only from
its address (`?artikel=<ulid>`).

```mermaid
flowchart TD
    WB["Workbench (workbench)\nledger + filter rail"] -->|"type query / Suchen"| WB
    WB -->|"rail filter click (?schlagwort=, ?bestand=, …)"| WB
    WB -->|"chip ✕ (filter removed)"| WB
    WB -->|"pagination (?seite=)"| WB
    WB -->|"Titel click"| DET["Detail (artikel-detail)"]
    WB -.->|"address only (?artikel=<ulid>)\npane visible ≥1280px"| PANE["Workbench + preview pane\n(workbench)"]
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

The archivist sets the Status and saves. The over-exposure preview GATE retired
(owner ruling 5, 2026-08-08): who would gain sight is on screen the whole time
they are cataloging — the margin's "Sichtbar für" select names the audience, the
inherited option included (a1 round 3). The audience computation itself did not
change: it is still the domain's `preview()`, still archivist-only. v1 lifecycle
is binary.

```mermaid
flowchart TD
    EDIT["Edit surface (draft)"] -->|"Status: Veröffentlicht, Speichern\n(the edit form's own POST + CAS)"| READ["Read view, published"]
    DET["Detail (draft)"] -->|"Veröffentlichen → confirmation\n→ Jetzt veröffentlichen (artikel-veroeffentlichen, CAS)"| READ
    READ -->|"Als Entwurf zurückziehen"| EDIT
```

Two ways publish a draft. The edit form's margin has a Status select, and
Speichern applies it in the form's single CAS-guarded write (a1 round 4). Enter
submits Speichern, so it publishes exactly when the archivist set
Veröffentlicht. The article page has its own route (owner, 2026-09-27, a3 round
7 in `explorations/2026-09-26-monochrome/REVIEW-ARCHIVIST.md`):
"Veröffentlichen" opens a confirmation that says who will see the record, and
"Jetzt veröffentlichen" posts to `artikel-veroeffentlichen` with the page's
version. A stale page or a record that is no longer a draft writes nothing and
returns to the page. Withdrawing still goes through the edit form.

Draft → published is the one gated transition, on both paths, and the gate is
one decision: `BestandChooser.chain_of(...) is None`. When the Bestand chain
does not resolve, the select offers no Veröffentlicht and the server refuses it
with a German error on Bestand; the article-page route refuses it inside its
write, against the record actually written.

Journeys: `test_publish_by_status_saves_the_form`,
`test_publish_from_the_article_page_confirms_first`,
`test_edit_and_save_redirects_to_read_view` (Enter).

## 4. Delete

```mermaid
flowchart TD
    DET["Detail (artikel-detail)"] -->|"Löschen"| CONF["Confirm page (artikel-loeschen)"]
    CONF -->|"POST: delete"| WB["Workbench"]
    CONF -->|"abort (back link)"| DET
```

Journey: `test_loeschen_confirm_then_delete`.

## 5. Bulk edit (Sammelbearbeitung)

"Auswählen" turns on selection mode (`?auswahl=`, the checkbox column);
"Abbrechen" leaves it and drops the selection. The selection is URL-borne
(`?auswahl=<ulid>&auswahl=…`) so it survives navigation and can be seeded by
a link; DOM ticks are merged into the URL set as the archivist pages. One
field + one value per pass.

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

## 7. Arrival and access

How each viewer tier reaches the workbench, per ADR 0018 as amended by the
2026-08 rulings (`docs/requirements/owner-interview-2026-08.md`). The Keycloak
branch and the login redirect are built (2026-08-30); the capability link is
still designed only. Dev keeps the viewer-switcher instead — the gate is off
there.

```mermaid
flowchart TD
    START{"How did they arrive?"} -->|"Keycloak login\n(members + archivists)"| OIDC["OIDC flow → Viewer cookie\nwith Keycloak groups"]
    START -->|"capability link\n(token mints Viewer cookie)"| CAP["Link-tier Viewer\n(possibly group-carrying)"]
    START -->|"no credential"| DENY["Login redirect —\nno public browsing exists"]
    OIDC --> WB["Workbench"]
    CAP --> WB
```

No browser journey: the flow leaves the app for Keycloak. It is covered by
`tests/app/web/test_auth_views.py` and `test_anonymous_gate.py` against an
in-memory realm, plus the runbook's one-real-login smoke step.
