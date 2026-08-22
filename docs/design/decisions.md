# Design decisions index

Status: LIVE INDEX — current state and open queue only; history lives in git
and the sources. This file DECIDES nothing: every row points at its
authority (`design-system.md`, `design-review-law.md`,
`docs/requirements/*`, a brief). One line per decision; edit the source,
then this index, in the same wave.

## Ratified — the standing law (pointers)

| Decision | Source |
|---|---|
| Construction law: semantic HTML, three-layer composition model, precedent rule, provenance | design-system.md §Construction law |
| Cascade over class taxonomy; `c-*`/`l-*` deprecated, dissolved in the rework wave | design-system.md; owner-interview 2026-08 |
| Token architecture: seed → ramps → roles; one-line sibling retheme; roles-not-colors | design-system.md; tokens.css |
| Stamp grammar: seed tint only on archival marks; states = neutral inversions; amber + red the only loud hues | design-system.md §Principles |
| Cue register (12 rows, MAY-only) + review catechism + cascade rules C1–C14 | design-review-law.md §A–C |
| Paper material: cut sheets on the gray desk, not Google Material; contact + overlay shadows only | review-law row 8/12; owner 2026-08-06/07 |
| Bevel: single cut, leading corner, reader-header context only; trapezoid reserved | review-law row 1 + reserved |
| Ledger = bound register (line-table default view); Lesesaal + cards as switchable views | owner 2026-08-07 exploration verdicts |
| Rail = primary filter interaction; bare on the desk; compact control-height knob | owner 2026-08-07 rail waves |
| Intrinsic first, derived thresholds only (C9/C11); fold = phone-width last resort | owner 2026-08-07 round 2 |
| Form wave: composition E, one sticky action row, every identity fact a field, native file input | owner 2026-08-08, form-wave-brief.md |
| A11y floor WCAG 2.2 AA; viewport targets: archivist desktop-first, reader phone-first | review-law §D |
| Signatur domain fact: no spaces, 8-char practical ceiling | CONTEXT.md; owner 2026-08-07 |
| North Star "The Archivist's Desk"; seed = "Stamp-Ink Violet" (hue unchanged) | DESIGN.md; owner 2026-08-22 |
| Design is IN DEVELOPMENT — never treat incumbent patterns as complete/settled | owner 2026-08-22 |
| Pane = scent surface: preview; details on the article's own page | pane-lifecycle-brief.md; owner 2026-08-22 |
| Shared views: archivists browse/research like members — one experience, capabilities layer on | owner-interview 2026-08 §Strategic rulings |
| Media v1 = designed essentials, simple (image viewing, native players, PDF hand-off); exotic viewers future | owner-interview 2026-08 §Strategic rulings |
| Entry surfaces: one-sentence sheet door, silent link arrival, no identity chrome, footer Abmelden, quiet dead-link hint | entry-surfaces-brief.md; owner 2026-08-22 |
| Reader: record first → vertical media roll → facts; Bearbeiten only; no audience fact | reader-brief.md; owner 2026-08-22 |
| Footer = Abmelden only (the app's one footer; bare desk) | owner 2026-08-22 §Craft rulings |
| Reading-measure token (~65–70ch) for prose surfaces — enters with the wave that needs it | owner 2026-08-22 §Craft rulings |
| Amber parks for Submission once gray ENTWURF lands (reserved, not licensed) | owner 2026-08-22 §Craft rulings |
| Lifecycle mark = gray ENTWURF word (no amber, no box), all surfaces | pane-lifecycle-brief.md; owner 2026-08-22 — **lukewarm ("for now"), revisit candidate (G.20)** |
| Quiet defaults stand: hover-revealed bulk boxes/row toolbars, self-hiding Sammelbearbeitung | owner 2026-08-07, reconfirmed 2026-08-22 |

## Open queue — work through in this order

1. **Fix #53: overlay panels render over their trigger** (bug, filed,
   ready-for-agent). FIRST because every gate render judges through the
   broken dropdowns until fixed; add the "panel below trigger" walker.
2. **Pane + lifecycle wave** — implement `pane-lifecycle-brief.md`: gray
   ENTWURF everywhere, pane preview fact set (gate decides floor+),
   Vorschau targets detail route where the pane is hidden. Register row 4
   amendment rides along.
3. **Sortable-head resting affordance** — 2–3 quiet treatments as mocks at
   the same gate (owner direction ruled 2026-08-22; treatment open).
4. **Zero-hit rail** — dropdowns vanish at 0 Treffer, the rail dismantles
   itself when pivoting matters most. Design question: what does the rail
   promise at zero? (Also touches the C10 status-only-band tension.)
5. **Fail-open labels** — ULID fallback ("Unbekannter Bestand") +
   Medienart display vocab. Mechanical once copy is chosen; file as issue.
5b. **A11y mechanicals** — workbench lacks an `h1` and a skip link (live
   critique finds, 2026-08-22). WCAG 2.2 AA is already law (§D); no
   ruling needed, pure fixes.
6. **Error voice** — one generic banner string today; needs a small
   error-copy taxonomy (what the archivist is told, when), then mechanical.
7. **Bulk chooser composition** — "— Feld wählen —" state shows no value
   widget and strands the primary button far right; recompose.
8. ~~badge_visibility exhibit~~ — **RULED: DELETE** (owner 2026-08-22);
   demo entry drops in the same change. Rides the next cleanup wave.
9. ~~Chip type role~~ — **RULED: chips keep meta** ("values shouldn't
   shout", owner 2026-08-22; closes #45's question). NEW open item it
   spawned: **label-role case treatment** — "labels don't necessarily
   need to be Caps either"; mock round (uppercase vs mixed) across rail /
   ledger head / reader, decide at a gate (G.7/G.14).
10. **Empty-media hollow weight** — a postcard of absence on the quiet
    sheet; revisit when the pane wave touches that template.
11. **Screen propagation (the precedent rule):** workbench exemplar →
    detail page (reader, now distinct from pane by contract) → edit form
    re-check against propagated learnings → member Lesesicht (serif
    reading role is RESERVED, licensed with that wave) → demo pages in
    lockstep throughout.

### Strategic shape queue (owner order, 2026-08-22)

- **D3 entry surfaces — SHAPED** (`entry-surfaces-brief.md`); build rides
  the auth wave (ADR 0018, the deployment-1 blocker).
- **D1 detail page + media — SHAPED** (`reader-brief.md`): record first,
  vertical media roll, Bearbeiten the only reader action; inferences
  i1–i5 awaiting the correction round.
- **D2 — CLOSED (owner 2026-08-22):** Lesesaal is the third result view
  under the SAME rail (table default). No separate reading-mode filters;
  serif reading role stays reserved for that view's wave.
- **D4 Bestand navigation — RULED (owner 2026-08-22):** tree is shallow
  (≤2–3 levels); facet-only browsing for now (**lukewarm — revisit after
  real data**, G.20); optional Bestand description (display surface
  deferred); the term is "Bestand" (CONTEXT.md corrected). The facet
  panel presents the shallow tree indented *(inference i6 — correction
  round)*.
- **D5 — RULED (owner 2026-08-22):** Datierung von/bis range joins the
  rail now (EDTF bounds support it); further grammar UI waits for
  archivist feedback.
- **Zero-hit rail — RULED (owner 2026-08-22): smart facet counts** (each
  dropdown computed with its own filter excluded) — fixes the pivot dead
  end and stabilizes rail geometry. Index/query work rides the wave that
  builds it.

## Deferred / future (recorded, not queued)

- Vendored OFL faces (drop-in swap for the system stacks) — later decision.
- `prefers-contrast: more` remap (third mode; zero component changes by
  construction).
- Register-tab component (trapezoid cut) — reserved for view navigation.
- First-run discoverability hint — parked; quiet defaults stand.
- Papierkorb + Digitale Eingangskiste surfaces — product roadmap, get
  their own shape sessions when scheduled.

## Parked ideas (inspiration annex)

- Cursive/handwritten face for the ENTWURF mark (owner, 2026-08-22 — "not
  important right now"). Would need a new type role + register row.
