---
target: detail page (reader)
total_score: 21
max_score: 28
na_heuristics: 5,9,10
p0_count: 1
p1_count: 2
timestamp: 2026-08-22T21-32-55Z
slug: ndesarchiv-app-web-templates-workbench-detail-html
---
Method: dual-agent (A: design review agent · B: detector agent; detector re-run full-power post-dependency-fix by parent)

# Design Health Score — Detail page / reader (Read mode; pre-redesign capture)

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | ENTWURF loud and clear; "Blatt 1 / 2" is a status display that never changes |
| 2 | Match System / Real World | 3 | Archive German excellent; "Umfang: N Blatt" derived from digital media count — claims physical extent from scan count |
| 3 | User Control and Freedom | 3 | Crumbs + tag links + Zurück real escapes; tapping a plate dumps into a chromeless browser image |
| 4 | Consistency and Standards | 4 | One renderer per fact, role tokens throughout, both modes coherent |
| 5 | Error Prevention | n/a | Read surface; no destructive input (Löschen has its own confirm page) |
| 6 | Recognition Rather Than Recall | 3 | Cover duplicated as filmstrip plate 1 — reader must recognize the identity |
| 7 | Flexibility and Efficiency | 2 | No plate-to-caption path at full size, no next/prev, members get no navigation aids beyond back |
| 8 | Aesthetic and Minimalist Design | 3 | Quiet; but a 480px thumb upscaled to 1094px monopolizes the desktop first viewport; bare records leave a 72rem stage ~90% empty |
| 9 | Error Recovery | n/a | No reachable error states (deny = plain 404, ledger-decided) |
| 10 | Help and Documentation | n/a | Self-describing read surface |
| **Total** | | **21/28 (75%)** | **Good** |

# Design Specificity Verdict

**LLM:** authored, with one generic organ. Identity system unmistakably this product (beveled Signatur tab, hairline + double rule, small-caps wordmark, mono machine values); dark mode a true token remap. The generic organ is the record-card + filmstrip pattern itself — stock DAM furniture; the page is a catalog card wearing the house livery, not yet a reading room. (The ruled reader-brief replaces exactly this.)

**Deterministic scan:** first run degraded (regex, 0 findings); parent re-ran full-power after installing the parser deps: 1 advisory — `dl` text color computes `rgb(0,0,0)` outside the palette. Likely false positive (static engine can't see body-level inheritance), but the wave should verify computed: a raw UA black would be a themability hole.

**Visual overlays:** skipped — no browser automation tool exposed.

# Overall Impression

The phone first-view is the incumbent's best moment — calm, archival, trustworthy. Desktop leads with a wall of blurry image (a 480px thumbnail painted at 1094px) and buries the identity below the fold. Dead state machinery (plate counter/frame that never changes) and sub-floor touch targets on the member's onward links are the real defects. Three incumbent strengths are MISSING from the reader brief and must be folded in before the wave builds.

# What's Working (⚑ = absent from reader-brief — must be folded in)

1. **⚑ The Beschreibung prose section** — real paragraphs at a 65ch measure (detail.html:61-66). The brief's composition never lists the body text; for a reading surface it is the thing that is read.
2. **⚑ The browse loop** — breadcrumb chain into the workbench facet, Schlagwort links, leaf-Bestand fallback under 560px. The brief names no Einordnung display and no tag links; a research destination without onward paths is a dead end.
3. **One projection, no fork** — member tier verified live: zero archivist chrome, draft → 404; Q3 passes by construction (project() floors fields before the template). Preserve the mechanism in the wave.

# Priority Issues

**[P0] Hero is a 480px thumbnail painted at 1094px.** thumbnails.py caps at ~480px longest side; detail.css sets cover width:100% in a 72rem column → every real photograph renders ~2.3× native on desktop (1.7–3× on hi-DPR phones). Invisible on the flat-color e2e corpus (G.6). The ruled vertical roll makes it WORSE (every image full-width) — the brief inherits this P0. Fix: reader-size derivative (~1200–1600px) or srcset, decided before the wave.

**[P1] Dead plate-state machinery.** Permanent aria-current inversion frame + static "Blatt 1 / 2" (detail.html:116-118); no state machine exists behind the cue (catechism Q6). The roll dissolves this — confirm the wave deletes counter AND frame.

**[P1] Sub-floor touch targets on the member's onward links.** Measured: tag links 30×19 / 51×19px, leaf-Bestand 72×16px — under the WCAG 2.2 AA 24px floor on the phone-first surface. The --control-height knob never reaches .facts links. Fix: same knob or block-level targets.

**[P2] Media links can be nameless.** Anchor name comes solely from alt="{{ caption }}" — caption-less media yield focusable links with empty names (source-only; corpus has no caption-less media). The brief's empty-caption copy gate must cover alt.

**[P2] Desktop identity below the fold; bare records adrift.** Title at 21.6px after a viewport-height cover at 1440; bare/draft articles waste the 72rem stage. Brief's i5 (reading measure, centered sheet) + record-first ruling fix both.

# Cognitive Load / Catechism

Q6 dead cue (plate state) · Q2 one-fact-three-places (cover twice; media count twice) · Q9 weight-vs-rank inverted on desktop (plate outranks identity) · copy presumption: "Zurück zur Suche" for a link-guest who never searched.

# Emotional Journey

- Phone 390px first view: genuinely good — wordmark, framed captioned photo, title, date, first prose line.
- Desktop: 90% photograph, no title in the first viewport.
- Bare/draft article: institutional emptiness — abandoned, not minimal.
- Photo tap → chromeless raw image: small trust drop, honest but jarring.

# Persona Red Flags

**Jordan (first-time link-guest, phone):** first tappable thing silently exits the product (raw image, no chrome); "Zurück zur Suche" presumes a search never made.
**Casey (slow connection):** no width/height on img → mid-read layout shift as images arrive; loading="lazy" on the COVER delays the LCP element.
**Sam (SR + keyboard):** figure link precedes the h1 (identity arrives second); ENTWURF badge inside the h1 — heading announces "Lagerchronik Entwurf" (state-in-title at the a11y layer); nameless media links on empty captions. 14-stop walk otherwise clean, focus rings everywhere.

# Minor Observations

- Two differently-labeled buttons route to the same edit page (Bearbeiten + Veröffentlichen-as-link) — honest per ruling, odd on hover.
- Filmstrip plate 1 carries no caption span while plate 2 does — asymmetric strip.
- Archivist action row wraps to two rows at 390 and outweighs content; Bearbeiten-only ruling fixes it — but Kopieren-from-detail dies with it (watch-item for serial cataloging; ruled answer: the table is the workhorse).
- Amber boxed ENTWURF still lawful today, already superseded on paper — the wave must not copy it.
- 900/560px queries = confessed C9 debt, already assigned to the wave.

# Questions to Consider

1. Is "Umfang: N Blatt" a fact or a fabrication? It equals len(media) — scan 3 of a 30-sheet Akte and the reader states "3 Blatt."
2. Has the ruled vertical roll ever been rendered with REAL photographs at 1440? The 480px cap means the ruling may rest on renders that cannot show blur (G.6).
3. What does a member do at the END of the page? The brief's composition terminates in Bearbeiten (archivists) — for members, nothing. Onward affordance worth a ruling before the wave bakes in a dead end.

# Corpus caveat

All photographic judgments are inferential — the e2e corpus is flat-color squares (G.6); no long-roll (10+ media) article exists, so that brief state is untested.
