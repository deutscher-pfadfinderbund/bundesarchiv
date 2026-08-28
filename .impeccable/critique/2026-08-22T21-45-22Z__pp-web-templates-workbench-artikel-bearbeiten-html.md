---
target: edit form
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
timestamp: 2026-08-22T21-45-22Z
slug: pp-web-templates-workbench-artikel-bearbeiten-html
---
Method: dual-agent (A: design review agent · B: detector agent; detector re-run full-power by parent)

# Design Health Score — Edit form (artikel_bearbeiten, Operate)

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | CAS conflict arrives with zero focus/announcement; dirty flag resets on error re-render while edits are unsaved |
| 2 | Match System / Real World | 3 | Raw English EDTF parser error leaks into the German UI |
| 3 | User Control and Freedom | 3 | Zurückziehen reverses publish; but save always exits to detail; no Escape on the Mehr menu |
| 4 | Consistency and Standards | 4 | One system with the workbench; one renderer per fact |
| 5 | Error Prevention | 3 | Two-step remove, own delete page, CAS; accidental Enter anywhere commits-and-leaves |
| 6 | Recognition Rather Than Recall | 3 | Fold summaries carry values; EDTF recall-y but hint + echo carry it |
| 7 | Flexibility and Efficiency | 3 | Kopieren 2 clicks → caret in Signatur; per-save detail-page detour taxes the serial loop |
| 8 | Aesthetic and Minimalist Design | 4 | Ruled card, quiet defaults, folds recede — earned |
| 9 | Error Recovery | 3 | Validation state exemplary; CAS diff panel excellent but unannounced |
| 10 | Help and Documentation | 3 | Inline hints where needed |
| **Total** | | **31/40** | **Good** |

# Design Specificity Verdict

**LLM:** designed, not defaulted — a surface with a thesis executed against its own written law (ruled-card grammar off a measured label axis, ch-derived widths, arithmetic-derived columns, licensed cues citing rows). No AI-form tells. Weak spots are behavioral seams, not visual genericism.

**Deterministic scan:** degraded run 0 findings; full-power re-run: 2 advisories, both the `rgb(0,0,0)` static-inheritance class (likely false positives — the engine can't see body-level ink; one computed check settles the class).

**Visual overlays:** skipped — no browser automation tool exposed.

# Ruling compliance (the eight form-wave rulings)

ALL EIGHT MET, live-verified. Notes: ruling 4 (folds) met with a practical dilution — first-empty GET autofocus forces a rare fold open on most plain edits; ruling 7's premise (German browser → German file-input strings) is locale-contingent, worth one doc line.

# What's Working

1. **Validation state is exemplary** — server-decided [open] from the same context, :has(.error) summary marker that cannot lie, first-error focus surviving the htmx swap, all values preserved incl. inside folds (G.33 fully internalized).
2. **Composition E is earned** — two columns by arithmetic, sheet sticks on a derived --pane-top, exposure statement provably exactly-once at every width.
3. **Post-Kopieren state coheres end-to-end** — Signatur cleared AND focused, ENTWURF, Veröffentlichen appears, sheet flips tense, hollow media slot.

# Priority Issues

**[P1] CAS conflict focuses nothing; the intended target doesn't exist.** catalog_views.py:307 sets autofocus="speichern" but no element renders it; verified live: focus = body, no announcement. The one state risking silent data loss is invisible to keyboard/SR users and anyone scrolled down; blind re-submit applies your values over the winner's. Fix: render autofocus on Speichern for that state + role="alert" on the conflict panel. (G.33's class with the viewport as the fold.)

**[P2] English domain error in the German UI.** catalog.py:226 interpolates the raw ValueError: "unrecognised EDTF value: 'kaputt-datum'". Fix: German message at the parse boundary with examples.

**[P2] First-empty GET autofocus fights ruling 4.** Rare fields are exactly the likely-empty ones, so a rare fold opens on most plain edits and yanks the narrow-viewport scroll past Kerndaten. Serial case already served by ?fokus=signatur. Fix candidate: first-empty walk only on create→edit continuation; plain re-edit focuses Titel or nothing.

**[P3] Datierung echo triggers on keyup only** — paste/autofill never fires it (verified: value 1980-05, echo "um 1970"). Fix: hx-trigger="input changed delay:400ms".

**[P3] Dirty flag resets while still dirty** on every POST re-render. Render it visible on error/conflict re-renders.

# Cognitive Load

The costliest state (CAS) has the weakest signposting; first-empty autofocus spends orientation before work starts (390px opens scrolled past Kerndaten); 390px sticky row = 129px chrome (worst width, tolerable on a desktop-first surface).

# Persona Red Flags

**Alex:** between-records loop good; within-record checkpoint saves cost detail→Bearbeiten→reload; accidental Enter = commit-and-leave.
**Sam:** full 45-tab cycle = field order, icons named, disabled arrows skipped; CAS silence is THE flag; Mehr menu lacks Escape.
**Riley:** no overflow at any width with 100+-char values; but 18ch short inputs hide 75% of a long Autor while editing; English EDTF error is the daily greeting; many-media untested (corpus: 2 files).

# Minor Observations

- Kopieren does NOT copy media — archivist-wishes only say "Signatur cleared"; media semantics unstated. Owner ratification needed.
- Kerndaten leaves a tall empty band under Signatur at 1440 (grid balances to the taller neighbor) — cosmetic.
- Caption inputs keep boxes while card fields are ruled lines — two input grammars, defensible (register vs card material), nowhere stated.
- Dark mode coherent at both widths tested.

# Questions to Consider

1. Should Speichern keep you on the form? A cataloger's save is a heartbeat, not an exit.
2. Is first-empty autofocus still right now that folds exist? It aims at the LEAST important empty field of a mostly-complete record.
3. Should a CAS conflict outrank a validation error in loudness? It's the only state where misreading costs another archivist's saved work.

# Coverage

Live: all 8 rulings, sticky mechanics, full keyboard cycle, Enter semantics, validation round-trip, CAS conflict, Kopieren round-trip, 1440/800/390, both modes, long values, echo paste-gap. Source-only: publish fail-closed branch, index-lag state, many-media, axe pass. Corpus thin (4 records — G.6 caveat on anything volume-dependent).
