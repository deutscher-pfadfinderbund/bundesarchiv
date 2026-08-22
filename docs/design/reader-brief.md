# Reader (detail page) + media — brief (D1)

Source: owner shape interview 2026-08-22 (rulings verbatim in
`docs/requirements/owner-interview-2026-08.md` §Reader rulings). Design
record only — no implementation scheduled by this file.

## Job and audience

THE reading surface for every tier (shared-views ruling): the link-guest's
landing, the member's research destination, the archivist's inspection
view. Phone-first by law (links arrive via chat/mail); full truth lives
here (pane = scent). Mode: Read.

## Composition (ruled: record first)

One composition for every article type, top to bottom:

1. **Identity header** — Signatur tab (register row 1's licensed context),
   Titel, Datierung, gray ENTWURF when draft (pane-lifecycle-brief.md).
2. **Media roll** — all media full-width in ADR-0015 order (first =
   cover), caption beneath each. Ruled: vertical roll, no
   lightbox/thumbnail machinery.
3. **Akte facts** — the record's key/value list. Custom fields render for
   Archivists only (ADR 0009), layered into the same list.
4. **Bearbeiten** — the reader's ONLY archivist action (ruled: "the
   workhorse for bulk edits is the table"); members see no action chrome.

## Media roll — designed essentials (ruled scope)

- **Images:** full-width in order, caption beneath.
- **Audio/video:** native players, full-width, same ordered roll
  *(inference i1)*.
- **PDF / other files:** a quiet file card in the roll (caption + type),
  opening via browser hand-off *(inference i2)*.
- **Tapping an image opens the original file** (browser-native view) — no
  in-page lightbox *(inference i3)*.
- Future release (out of scope, ruled): multi-page scan navigation,
  in-page PDF reading, waveform-class players.

## Inferences awaiting the correction round

- i1–i3 above (mixed-media roll behavior, file cards, tap-to-original).
- i4: **Bearbeiten placement** — one quiet button at the identity header's
  end (no toolbar needed for a single action).
- i5: **Desktop = the same sheet at a constrained reading measure,
  centered on the desk.** Material role (G.17): TRUE SHEET — the pane's
  sheet laid flat; register row 8 applies.

## States (for whichever wave builds this)

Draft · ohne Signatur · no media at all · single image · long roll (10+
images) · mixed media (image + audio + PDF) · custom fields present
(archivist view vs member view) · phone + desktop, both modes.

## Open decisions the builder must not invent

- ~~Audience/exposure fact on the reader~~ — RULED (owner, 2026-08-22):
  **No — edit screen only.** Exposure lives where it is changed; the
  reader carries no access chrome for any tier.
- German copy (captions' empty state, file-card labels) — gate, on renders.
- Datierung spelling on the reader (machine vs human German) — G.46
  licenses both with one renderer each; which one the reader header uses
  is settled by precedent (pane prints the machine value) unless the owner
  rules otherwise.
