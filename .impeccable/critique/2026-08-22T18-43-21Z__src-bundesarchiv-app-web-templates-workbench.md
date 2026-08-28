---
target: workbench
total_score: 27
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
timestamp: 2026-08-22T18-43-21Z
slug: src-bundesarchiv-app-web-templates-workbench
---
Method: dual-agent (A: design review agent · B: detector agent)

# Design Health Score — Workbench (Operate)

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Live Treffer count, chips, aria-current strong; sort state subtle |
| 2 | Match System / Real World | 3 | Archival German excellent; machine tokens leak (chip "Medienart: dokument", raw ULIDs on broken Bestand chains) |
| 3 | User Control and Freedom | 3 | URL-as-state, per-chip ✕, clear-all; zero-hit state drops all facet dropdowns — pivot tools vanish |
| 4 | Consistency and Standards | 3 | One-renderer law mostly holds; pane omits ENTWURF badge the detail header carries |
| 5 | Error Prevention | 3 | Bulk two-step confirm good; "Änderung prüfen" submits with Feld unset (server-side reject only) |
| 6 | Recognition Rather Than Recall | 2 | Row actions, bulk checkboxes, Sammelbearbeitung disclosure all invisible until hover/first tick; sortable heads identical to non-sortable at rest |
| 7 | Flexibility and Efficiency | 3 | Type-to-search, sortable heads, sane tab order; no skip link/shortcuts |
| 8 | Aesthetic and Minimalist Design | 4 | Dense, quiet, no filler chrome, both modes coherent |
| 9 | Error Recovery | 2 | One generic banner string; unresolvable Bestand names print raw 26-char ULIDs |
| 10 | Help and Documentation | 1 | Nothing on-surface; weekly volunteer tool with hover-hidden affordances has no first-run hint |
| **Total** | | **27/40** | **Acceptable (upper band)** |

# Design Specificity Verdict

**LLM assessment:** Genuinely authored, not category-interchangeable. Small-caps serif wordmark over the double rule, bound-register ledger (hairline rules, one violet margin rule, right-aligned mono Datierung), stamp-ink grammar, tinted pulled-sheet pane with single contact shadow — reads unmistakably as "an archivist's desk", surviving dark mode intact. The discipline is the signature. One slip toward generic: the dropped overlay panels (plain gray boxes), which also currently misposition.

**Deterministic scan:** DEGRADED — detector ran regex-fallback (htmlparser2/css-select/css-tree/domutils unavailable), 0 findings across workbench + components templates, exit 0. An undercount, not a clean bill: custom properties, selector matching, computed contrast not evaluated. The LLM review found real issues (anchor mispositioning, view-model gaps) that live outside even the full detector's reach — no contradiction between the two assessments, but also no corroboration.

**Visual overlays:** skipped — no browser automation tool exposed on this machine.

# Overall Impression

The visual system is the strength: 8/10 on minimalism is earned, and the paper-desk metaphor holds under dark mode, long content, and keyboard use. The weaknesses cluster in two families: (1) a real rendering bug in the anchor-positioning enhancement that the project's own gate browser has been silently judging, and (2) the hover-reveal economy pushed past what a monthly-returning volunteer can rediscover — invisibility of sort, bulk, and row actions is the surface's real cognitive cost.

# What's Working

1. **Ledger resilience is real, not claimed** — 150-char injected Titel ellipsizes, keeps its ENTWURF mark, never widens the page; intrinsic columns keep everything visible at 680px, no fold.
2. **Keyboard journey first-class** — 18-step Tab walk in reading order; hidden toolbar/checkboxes reveal on :focus-within (computed-verified); German accessible names on all icon controls; aria-sort, live count, aria-current all present.
3. **Stamp grammar under pressure** — dark mode re-derives from the same roles; amber + violet stay the only hues; the two 1440px mode shots could pass as one design on different paper.

# Priority Issues

**[P1] A — Overlay panels render OVER their own trigger row.** Facet panel top 63px vs trigger bottom 107px, measured live; anchor-positioning enhancement (`position-area`/`position-anchor`) is active but lands the panel at the row's top-left, covering the trigger and neighbor buttons; header "+ Neu …" panel covers the search input. The project's e2e/gallery Chromium renders this, so the design gate has been judging the broken rendering; the G.26 walker checks containment, not "below trigger". Fix: verify on current stable Chrome; repair the anchor branch (likely anchor-scope resolution against the details box) or drop the pre-Baseline enhancement so the correct row-pinned fallback actually runs. `components.css:347-369`. Suggested: /impeccable polish (+ a walker assertion "panel top ≥ trigger bottom").

**[P2] B — Pane omits the ENTWURF lifecycle badge.** Ledger row says ENTWURF; the sheet header says nothing; detail.html:56 and artikel_bearbeiten.html:41 render the boxed badge. The "one reader view in two compositions" promise diverges on the one loud lifecycle fact, at the exact moment an archivist checks a record's state. Fix: add draft to `_Pane` (browse_views.py:220-274) and render the badge in `_pane.html:19-23` header (register row 4 licenses reader headers). Suggested: /impeccable harden.

**[P2] C — Vorschau row action is a near-no-op across 512–1280px.** Pane column is display:none below the 80rem query (layouts.css:450) but the Vorschau icon renders whenever the ledger container exceeds the 32rem fold — click = page reload + row highlight, no pane. False affordance (catechism Q6) in the half-screen-desktop-window band. Fix: below the pane switch, point Vorschau at the detail route, or hide it with the same condition that hides the pane — stated once (G.44). `components/ledger_row.html:47`. Suggested: /impeccable harden.

**[P3] D — Sortable column heads carry no resting affordance.** SIG/TITEL/DATIERUNG links compute identical to non-sortable TYP; the promised "link affordance on sortable heads" is hover-only, invisible at rest; sorting discoverable only by accident. Needs an owner ruling (cue-register discipline): quiet resting affordance — hollow direction slot or underline-on-sortable. `components.css:586-604`. Suggested: owner ruling, then /impeccable polish.

**[P3] E — Fail-open label fallbacks print machine tokens.** (i) Unresolvable Bestand ULID renders verbatim as facet row + chip label (browse_views.py:612 `labels.get(fc.value, fc.value)`); (ii) Medienart facet/chip values show the raw lowercase index token ("dokument") beside German capitalized siblings. Fix: German fallback string ("Unbekannter Bestand") + vocab mapping for media_type labels. Suggested: /impeccable clarify.

# Cognitive Load

Failed/strained: **≤4 options per decision point** (bulk Feld select holds 9 — necessary, but the worst point); **progressive-disclosure double edge** — hover-revealed checkboxes/toolbars + JS-hidden bulk disclosure mean the cold-start archivist sees no evidence bulk edit or row actions exist (owner-ruled 2026-08-07, so a tension, not a defect — but the surface's real cognitive cost). All other items pass; chip echo + "2 ausgewählt" off-page accounting exemplary.

# Emotional Journey

- Peak: pulling the sheet — tinted pane + contact shadow lands the physical metaphor.
- Reassurance gap: previewing a DRAFT shows no ENTWURF mark (issue B) at the "what is this record's state" moment.
- Dead end: at zero hits the facet dropdowns vanish (empty groups dropped) — the rail dismantles itself exactly when the user needs to pivot.

# Persona Red Flags

**Alex (power archivist):** dropdown overlap forces reopen-to-reread; rail geometry unstable (groups appear/disappear with counts, muscle-memory shifts per query); hover-hunting for checkboxes/actions every visit; sort cycle undiscoverable.

**Sam (keyboard + SR):** no h1 on the workbench, no skip link (landmarks otherwise good); focus reveals hidden controls, aria-sort strict, per-row checkbox labels, live count survives swaps. Summary-embedded status count is announced inside the button name — mouthful, acceptable.

**Riley (stress):** long Titel survives; chips wrap with clear-all; zero-hit removes pivot tools; broken Bestand chain → raw ULIDs in three places; 512–1280 Vorschau no-op; `leerer_bestand` state exists in code, untested live (no empty Bestand in corpus).

# Minor Observations

- Zero-hit + no chips leaves the rail as a status-only band ("0 Treffer" alone) — C10 tension acknowledged in a comment, not quite licensed.
- Active facet row + its ✕ share the identical href — duplicate adjacent tab stop.
- Pane's empty-media hollow is a whole postcard of absence — licensed (row 6), visually heavy.
- Bulk chooser: default "— Feld wählen —" shows no value widget; primary button sits alone far right — reads disconnected until a Feld picked.
- EDTF "1980-03" mono column beside "März 1980" title — licensed (G.46) but the machine date is what the eye scans on an Operate surface.
- Environment drift warning: the worktree's empty var/canonical vs shared Postgres index initially produced three phantom defects; a gallery/gate run in a fresh worktree would lie the same way.

# Questions to Consider

1. Hover-reveal economy assumes a returning user — is a four-week volunteer gap short enough to rediscover hover-hidden checkboxes, invisible sort, a self-hiding bulk tool, or does the quiet-default law need a first-run exception?
2. The anchor enhancement silently pre-empted a correct fallback for months in the gate browser. Is "never load-bearing" enforceable without a walker asserting "panel sits below its trigger"?
3. What is the pane's contract — a reader surface (then it must tell the truth about lifecycle) or a scent surface (then why Öffnen/Bearbeiten actions)?
