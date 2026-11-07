# Bundesarchiv design system: closed gaps

Closed entries from `design-system/gaps.md`, moved here in full with their disposition, closure
date and basis.

### The kind glyphs have no decided icon set

- **Source:** owner ruling 2026-10-28 (MediaTile): a file without a stand-in shows a placeholder
  glyph matching its kind; owner, 2026-10-29: no icon set has been decided in this project.
- **Need:** a decided source for icons before any glyph is drawn into a component.
- **Actual result:** `src/bundesarchiv/app/web/templates/components/icon.html` calls itself "the one
  vendored inline-SVG set" on the strength of a law row no owner decision backs; the Media tile
  shows the cross for every file without a stand-in.
- **Expected result:** the owner decides the icon set (or that there is none); the Media tile's
  "No thumbnail" state gets its glyph per kind and the contract closes that open decision.
- **Evidence:** `design-system/components/media-tile.md`, "Open decisions"; the doc audit of
  2026-10-29.
- **Next step:** the icon set is one line of the doc-sanction cleanup's verdict table; after it,
  a craft round on the glyphs.
- **Disposition:** resolved. The owner picked the kind glyphs (Material Symbols for video, audio
  and every other kind; commit `1e7020bd`, 2026-10-31) and ruled that there is no single icon set:
  each icon is picked on its own (owner, 2026-11-08). The Media tile's "No thumbnail" state shows
  the glyph of its kind, and its contract has no open decision on glyphs.
- **Closed:** 2026-11-08.
- **Basis:** the Expected result holds: the owner decided that there is no icon set, and the
  placeholder shows its glyph per kind (`design-system/components/media-tile.md`; register row 9,
  `docs/design/design-system.md` Icons, `components/icon.html` restated).
