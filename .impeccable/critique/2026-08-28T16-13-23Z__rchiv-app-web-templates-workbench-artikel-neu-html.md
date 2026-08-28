---
target: form + confirm surfaces (artikel_neu et al.)
total_score: 18
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 3
timestamp: 2026-08-28T16-13-23Z
slug: rchiv-app-web-templates-workbench-artikel-neu-html
---
# Critique — form + confirm surfaces (artikel_neu, bestand_neu/bearbeiten, artikel_loeschen, sammelbearbeitung_pruefen/ergebnis)

Method: dual-agent (A: opus design review · B: sonnet detector + evidence). 2026-08-28.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | System status | 2 | bulk-result never says WHICH records; article create 302s with no confirmation while Bestand create gets one |
| 2 | Real-world match | 3 | Strong archival German; roadmap copy in production ("folgen später") + broken quotes |
| 3 | User control | 1 | No undo anywhere; clean bulk success destroys the selection (erneut_query only renders on conflict) |
| 4 | Consistency | 2 | Three action-row alignments, two read-only-fact grammars, two quote conventions in one flow |
| 5 | Error prevention | 1 | Zero required attributes on four forms; bulk confirm hides the values it overwrites |
| 6 | Recognition > recall | 2 | Confirm shows new value only; archivist must remember what 40 records hold |
| 7 | Flexibility | 1 | Bulk edit = 4 page loads per field; second field restarts from empty selection; no skip link |
| 8 | Minimalist design | 3 | Real restraint; but success page and partial-failure page are the same gray page |
| 9 | Error recovery | 2 | Bulk error below submit, no role="alert"; field errors inside <label> corrupt the accessible name |
| 10 | Help | 1 | One hint total; "Vom Bestand erben" under "— Oberste Ebene —" unexplained |

Total: 18/40 — Poor.

## Design Specificity Verdict

System authored, application interchangeable. Only product-specific moments (violet F9/F12 Signatur marks) are the smallest type on their pages. Confirm/form tier inherited tokens, not conviction.

Detector: exit 2, six findings, ALL false positives (jsdom cannot parse light-dark(), falls back to rgb(0,0,0); verified against real renders). Browser overlay skipped (Django-served pages); substituted 104 fresh gallery renders. B corroborated A's dark-mode danger button + unstyled confirmation findings independently.

## Priority Issues

[P0] Bulk apply overwrites N records with zero visibility of what's destroyed. sammelbearbeitung_pruefen.html:82-115 shows Feld, new value, count — never current values. No undo behind it. Fix: reuse orphan branch's {alt} → {neu} grammar on the article list; lead with "N von {anzahl} haben bereits einen Wert." (/impeccable harden)

[P1] Success signal is dead CSS. Cascade-layer bug: .count/.hint (components layer) lose to .column > p (compositions layer, layouts.css:387) — success moment renders as anonymous secondary body text (forms.css:429). Fix: move .count/.hint to compositions or narrow to p:not([class]). (/impeccable polish)

[P1] Broken German closing quotes on 4 of 6 surfaces. „…" (ASCII close) at artikel_loeschen.html:23, sammelbearbeitung_ergebnis.html:27, _pruefen.html:93; artikel_neu.html:20 closes correctly with “. Fix: four characters. (/impeccable clarify)

[P1] Three action-row alignments, no shared content axis. Create flush-left; bulk confirm flung right (primary x≈930, content x=320, forms.css:239-241); delete bare left. .column.narrow 34rem vs .column 52rem both center independently — left edge jumps 144px mid-flow. Fix: one action-row rule + one column axis for the tier. (/impeccable layout)

[P2] Dark mode inverts the safety hierarchy on both confirm surfaces: danger button brightest object (pale salmon), Abbrechen recedes. Fix: cancel gets --outline in dark, ≥3:1 vs surface; comparable perceptual weight. (/impeccable polish)

## Persona Red Flags

Alex: 4-hop loop twice for two fields, second run from empty selection (recovery gated behind {% if conflicted %}); Enter-to-confirm 4+ tab stops away (no skip link); nothing verifiable after apply; _pruefen.html:119 hardcoded URL vs :28 {% url %}.

Jordan: "Vom Bestand erben" under "— Oberste Ebene —" = inheriting from nothing on an access-control field; Gruppen input enabled regardless of Sichtbarkeit, silently discarded; no required/asterisk anywhere; delete-confirm identifies record by title + 10px F9 only, Löschen/Abbrechen 12px apart at equal weight; bulk panel 2 unheaded.

Sam: no skip link in base.html; error+hint text inside <label> corrupts accessible names (artikel_neu.html:27, bestand_neu.html:23,33,42,47), no aria-invalid; destructive button first tab stop in <main> on delete-confirm; bulk validation error after submit button, unannounced; unnamed panels (bestand_bearbeiten.html:22 proves the pattern is known).

## Minor Observations

- Dashed underline (forms.css:229) under PRESENT read-only values — the system's absence cue misused; "Fotografien"/"Öffentlich" read as empty.
- Buttons ~29-32px tall (no --control-height row knob outside header) — below the 2.75rem touch-target token; 32px "Anlegen" at phone width.
- Count rendered three times on bulk-confirm.
- Two grammars for read-only facts (<dl> vs <strong>Feld:</strong> paragraphs).
- ~85% unshaped emptiness below the fold at 1440.
- No Bestand delete surface exists.
- Dark header lighter charcoal than page body — hard seam (deliberate token split? needs ruling).

## Strengths

1. Orphan disclosure (_pruefen.html:88-104): per-row Dokumenttyp {alt} → (leer); commit relabels itself.
2. Conflicts styled as non-errors (_ergebnis.html:37-51): quiet rows, per-row edit link, re-select recovery, no red.
3. Real no-JS baseline; htmx additive; _header.html:31-38 documents the regression that shaped it.

## Questions

1. Search field = largest object on "Neuer Artikel" — what is that page for? Quiet search affordance on task surfaces?
2. Orphan branch itemizes computed loss; overwrites are uncomputed loss. If the rule were "warn about overwrites," what changes?
3. Enforcement rigorous about tokens/layers, silent about flow-level sameness. Wrong altitude?
