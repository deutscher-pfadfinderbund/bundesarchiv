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
6. **Error voice** — one generic banner string today; needs a small
   error-copy taxonomy (what the archivist is told, when), then mechanical.
7. **Bulk chooser composition** — "— Feld wählen —" state shows no value
   widget and strands the primary button far right; recompose.
8. **badge_visibility exhibit** — demo-only template; park-or-delete
   verdict (catechism Q1).
9. **Chip type role** — the one four-axis C8 exemption without a ruling
   (issue #45, open owner question).
10. **Empty-media hollow weight** — a postcard of absence on the quiet
    sheet; revisit when the pane wave touches that template.
11. **Screen propagation (the precedent rule):** workbench exemplar →
    detail page (reader, now distinct from pane by contract) → edit form
    re-check against propagated learnings → member Lesesicht (serif
    reading role is RESERVED, licensed with that wave) → demo pages in
    lockstep throughout.

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
