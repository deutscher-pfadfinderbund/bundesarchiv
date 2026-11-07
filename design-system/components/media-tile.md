---
sourcesHash: 1f1be8e879758221e3f3d9efc716db9af6304b21462a40a900ff75f2d2ebca40
id: media-tile
description: >-
  It shows one file, using the best stand-in the archive has for the file's
  kind, and it gives access to the file.
status: hidden
sources:
  - src/bundesarchiv/app/web/templates/components/media_tile.html
  - src/bundesarchiv/app/web/static/components.css
  - src/bundesarchiv/app/web/static/tokens.css
examples:
  - src/bundesarchiv/app/web/templates/components_demo/media_tile.html
---

# Media tile

The purpose is the owner's wording ("Rulings of 2026-10-28 (MediaTile)" in
`docs/requirements/owner-interview-2026-08.md`). Rulings cited below by date and heading are in
that file.

## When to use

- A screen shows one file of an article as something to look at and to open: the tile stands for
  that file and is the way to it. Each file shown this way is one tile; a list of files is a list
  of tiles.
- The screen holds the file's tile record (`MediaTile`, the archive's view of one file). The
  tile decides from that record what to show; the screen decides only where the tile sits and how
  large its box is.

## When not to use

- The screen shows a file's own content at full size, one at a time, with navigation between
  files: that is the Lightbox, its own component. The tile only hands it the image to open
  (ruling of 2026-10-28 (MediaTile): "Opening the Lightbox is the tile's behaviour, not part of
  the tile").
- The screen has no file to show: an article without files shows no tile and no placeholder
  (design law row 18: no placeholder where no medium is expected).
- The screen names a file only as words (a download line, a count of files): that is a link or
  text, not a tile.

## Public API

```django
{% include "components/media_tile.html" with file=tile only %}
{% include "components/media_tile.html" with file=tile label=False only %}
```

- `file` (required): one `MediaTile` record, as the archive builds it for the file. The tile reads its
  kind, name, original, thumbnail and its place in the page's Lightbox from it. A consumer never
  tells the tile which state to show; the record decides (ruling of 2026-10-28 (MediaTile): the
  stand-in follows the file's kind).
- `label` (optional, default on): the file's kind and name, shown on the placeholder (a tile
  with a thumbnail shows no label). Pass `False` where the consumer sets the file's name beside
  the tile itself; the tile then hides that text and keeps its own accessible name. The label's
  final form is an open decision (below).
- No other input. There are no variants, no ratio knob and no overrides (ruling of 2026-10-29
  (MediaTile contract): "No ratio knob for now. The container gives the box").

### The box

The container owns the tile's place, its box and the spacing around it, and sets them on the
tile's root only (`DESIGN.md`, "Contracts and public use": a composition sets knobs and places the
component, never selects inside it). The box is a maximum: the stand-in is never drawn larger
than its own pixels (owner, 2026-10-29: own pixels; today's cover). A placeholder has no pixels of
its own; it takes those of the square a thumbnail fits in. The box is given in one of three ways:

- **An inline size only.** The stand-in fills that width in its own shape, up to its own pixels;
  a placeholder is square.
- **An inline and a block size.** The stand-in fits inside the box in its own shape, up to its
  own pixels; a placeholder is the largest square that fits.
- **A block size only**, as a row of tiles of equal height gives it. The stand-in takes the
  height, up to its own pixels, and its own width; a placeholder is that square.

With no size set, the stand-in shows at its own pixels, never wider than the tile's container. The
tile owns what is inside the box: the stand-in, its edge, the label and the link.

## Behaviour and states

The file decides the state; a consumer cannot choose one.

- **A thumbnail exists** (ruled for images, PDFs and videos; a PDF's is its first page): the
  thumbnail shows in its own shape, never cropped and never letterboxed (ruling of 2026-09-28 (article media):
  "Images keep their own shape"; "A PDF shows as a thumbnail of its first page"), and never
  larger than its own pixels (owner, 2026-10-29: own pixels; today's cover). Its corners are
  square (`DESIGN.md`, Shapes). It carries no visible label (owner, 2026-10-29: the label as
  today).
- **No thumbnail** (a file whose thumbnail is not made yet, a kind that has none, an unknown
  kind): the glyph of the file's kind, centred inside a thin frame in Faint, with the kind and
  name as text (ruling of 2026-10-01 (media tiles): "A missing thumbnail never looks broken"; the
  glyphs are the owner's pick of 2026-10-31: one for video, one for audio, one for every other
  kind). The kind and name sit at the placeholder's foot; with `label=False` the placeholder
  shows the glyph alone.
- **Access**: the whole tile is one link to the original, opened in a new tab, in every state
  (ruling of 2026-10-01 (media tiles): "The original file is always one click away").
- **The Lightbox hook**: an image tile with a place in the page's Lightbox carries the hook the
  Lightbox reads, so a plain click opens the Lightbox there. A click with a modifier key stays the
  browser's (a new tab, a new window). A page without the Lightbox leaves the tile a plain link
  (ruling of 2026-10-28 (MediaTile)).
- The tile has no hover motion and no loading, selection or playback state. The underline of its
  label is the link's mark (design law row 20).
- Audio has no stand-in yet: a playback control is the ruled stand-in "once playback exists"
  (ruling of 2026-10-28 (MediaTile)); until then audio shows the placeholder.

## Accessibility

The tile provides:

- One focusable link, with the global focus ring. Its accessible name is the file's kind and
  name in every state, whether or not the label shows.
- The thumbnail keeps the record's alt text (ADR 0015: description, else caption, else file name);
  it does not take part in the link's name.
- The placeholder's kind and name are real text when the label shows; the glyph is decoration
  and has no name of its own.

The consumer provides:

- The group semantics of several tiles (a list, a figure with its caption): a tile shows one
  file (its purpose), so whatever groups files is the consumer's.
- The file's name beside the tile when it passes `label=False`, so a sighted reader still sees
  which file it is.

## Open decisions

- **The label's form** (at Public API, `label`): the owner has not decided where the label sits
  and what it says (ruling of 2026-10-29 (MediaTile contract): "The tile's label is undecided").
  As built it is the label as today (owner, 2026-10-29): no label on a thumbnail, the kind and
  name at the placeholder's foot, none with `label=False`. The demo shows the candidates: below
  every stand-in, over every stand-in's foot, and off with the name beside. With the label below
  and a block size only, the label takes part of the height, so a thumbnail is narrower than the
  tile.
- **The thumbnail's edge** (at Behaviour and states, "A thumbnail exists"): `DESIGN.md` Shapes
  settles square corners and the line width, but not whether a thumbnail has an edge or in which line
  role. As built it has a thin edge in the Edge role, so a white page does not dissolve into the
  ground.
