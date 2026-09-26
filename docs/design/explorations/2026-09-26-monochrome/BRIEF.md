# Exploration 2026-09-26 — monochrome, high contrast, new page compositions

Throwaway mocks, not production code. Static HTML + one CSS file per direction. No build step,
no external requests (no web fonts, no CDNs). German UI text, English code comments.

## Owner signals (binding for every direction)

- KEEP: the small-caps serif wordmark "Bundesarchiv" (ui-serif stack, `font-variant: small-caps`,
  ~0.12em tracking) and the lightweight table: hairline horizontal rules only, no zebra, no header
  band, tabular mono figures for Signatur/Datierung.
- The dark, bold, high-contrast look is liked: "very usable, feels sophisticated".
- The GRAY is rejected: gray fills/panels/buttons read as "an old, dated Office application".
  No gray surfaces as chrome. Gray is allowed only as secondary TEXT ink and as hairlines.
- The VIOLET accent is rejected: it is out of place in a monochrome look. No hue as decoration.
  Only functional color survives: red for errors/destructive, and the Entwurf (draft) mark — make
  Entwurf work in monochrome (e.g. outlined or inverted mono mark), no amber unless you argue it.
- NOT cheesy, no scout costume (no patches, lilies, campfire, maps, pennants, beige/parchment,
  warm paper). Audience: adults interested in the history of their Pfadfinderbund. It is a
  functional tool first.
- No beige, no warm tint washes ("beige looks AI"). Character comes from typography, scale
  contrast and structure.
- Keep system font stacks for sans and mono (owner was indifferent to web fonts).

## Composition problems to solve (the real brief)

Today: the home page IS a near-full-screen search table — overwhelming, no guidance; no top-level
navigation; no login button (logged out, `/` just shows "0 Treffer").

## Pages to build (each direction builds all four)

1. `door.html` — logged out. Wordmark, one sentence ("Das Archiv des Deutschen Pfadfinderbundes —
   Zugang für Mitglieder."), ONE button: solid dark gray, label exactly "Anmelden mit DPB Login"
   (owner-specified; this is the one sanctioned gray fill — make it work in both themes with
   readable text). No contact line. Nothing else.
2. `start.html` — logged in, first page. A guiding start page built from COMPARTMENTS:
   - a prominent search field,
   - Bestände (the 9 real collections with article counts),
   - Zeitleiste: decades with counts, including the "Unbekannt" bucket (347) — a compartment
     here, not a nav item,
   - Zuletzt hinzugefügt (pick ~5 real sample articles),
   - FUTURE compartments, shown as an idea only and visibly marked as such (e.g. a small
     "später" note): "Highlights" (archivist-curated) and "Empfohlen" (static recommended
     articles). Fill them with real sample titles.
   No full result table on this page.
3. `archiv.html` — the search/result page after a search: new header, active filters, the
   hairline result table (columns: Signatur · Titel · Datierung · Typ), ~25 real rows, one row
   marked Entwurf, pagination. The table must not feel like a wall: frame it, give it a clear
   heading/result count and filter context.
4. `artikel.html` — one article's read-only page (use a real sample article): title at real
   hierarchy, facts (Datierung, Typ, Urheber, Ort, Bestand, Standort, Signatur as one quiet row
   among the facts — owner: Signatur is working data, not an identity mark), a media area
   (placeholder tiles OK, labeled), a quiet "Bearbeiten" action for archivists.

## Shared chrome (every logged-in page)

Top navigation: wordmark (links to start) · Archiv · Bestände · Erfassen (archivists only) ·
compact search field (omit on start.html where the big search lives) · account at the right
(user name, e.g. "bjebb", + "Abmelden"). Keep it to one row on desktop; design the phone version
(≤ 390px) too — no horizontal scroll.

## Themes

Both themes via `@media (prefers-color-scheme: dark)` on custom-property tokens in `:root`.
Your direction states which theme is its PRIMARY (the owner leans dark), but both must be
finished — screenshots are taken in both. Hairlines must stay visible in dark.

## Data

`../data.json` — real legacy data (counts are true). Inline the values you use directly into the
HTML (no fetch). Do not invent counts or claims. Titles may be truncated with ellipsis in tables.

## Deliverable

Your folder only: `door.html`, `start.html`, `archiv.html`, `artikel.html`, `style.css`, plus a
10-line `NOTES.md`: the direction's thesis in one sentence, the token table (ground, ink, ink-2,
rule, fill-inverse, error), which theme is primary, and the 3 decisions you'd want the owner to
judge. Pages link to each other (relative links).

Self-check once with the project's Playwright Chromium (no system Chrome on this machine):
a throwaway script under your folder named `_zz_shot.py` that screenshots each page at 1440×900 and
390×844 in light and dark (`color_scheme=`), run with `uv run python`. Open the shots, fix what is
broken in ONE batch, re-shoot once, stop. Leave the PNGs in `shots/` inside your folder.

---

# Round 2 (owner verdicts on round 1, 2026-09-26)

- **Door page: X3** (`x3-register/door.html`) — settled; do not rebuild it.
- **Start page: X2 as the base**, but the Zeitleiste much smaller — one of two columns, side by
  side with Bestände, like X3 does. Not a full-width chart.
- **Round 1 was too similar.** Three variants that differ only in weight and rules are one
  direction. Round 2 must differ in STRUCTURE (topology, where navigation lives, what leads the
  page, what the eye lands on first), not only in styling.
- **No dark-only design.** Light and dark are equal citizens; design light-first, dark follows.
- **Article counts are not important.** No count at display size anywhere (no "2.506" folio,
  no "1.187" numeral, no "9" section folio). Counts are quiet secondary figures next to their
  label (ink-2, small, tabular), and may be dropped where they add nothing.
- Everything from round 1's "Owner signals" still binds (wordmark, hairline table, no gray chrome,
  no violet, not cheesy, system stacks, real data).

## Round 2 deliverable (each direction, its own folder `r2-<name>/`)

`start.html`, `archiv.html`, `artikel.html`, `style.css`, `NOTES.md` (thesis in one sentence +
how this direction differs STRUCTURALLY from the others + 3 things for the owner to judge).
Link the door to `../x3-register/door.html`. Screenshots as in round 1 (`shots/`, 1440×900 and
390×844, light and dark, full-page), throwaway `_zz_shot.py` inside your folder — one fix batch,
one re-shoot, stop.
