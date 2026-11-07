# Bundesarchiv design system: open gaps

Keep unresolved design-system gaps here (`design-system` skill, "gaps"). Move closed entries in
full to `design-system/gaps-archive.md` with their disposition, closure date and basis. Resolution
requires demonstrating the original Expected result.

## Open gaps

### The controls have no settled design

- **Source:** owner, 2026-10-28: the controls stay one recorded gap until the clean-room design of
  the control primitives. The Button pilot of 2026-10-27 left the decisions below open.
- **Need:** a component whose CSS styles a control is adopted on a settled design of that control.
- **Actual result:** the native controls (the button and its looks, input, select, textarea,
  checkbox and radio, the file selector, summary) are styled in the elements layer of
  `src/bundesarchiv/app/web/static/components.css`, with no contract. Components that style a
  control cannot be adopted.
- **Expected result:** each control primitive has an approved contract from a clean-room design,
  and the components that style a control can be adopted on it.
- **Evidence:** the ruling above; the elements layer of `components.css`.
- **Next step:** design the control primitives clean-room, then propose their contracts for the
  owner's approval.
- **Decision needed:** when an action outside a menu takes a text look; the button size (DESIGN.md
  and the mock against the shipped CSS); a disabled state for the framed looks.

### The Lightbox has no contract and is not on every page with image tiles

- **Source:** owner ruling 2026-10-28 (MediaTile): opening the Lightbox is the tile's behaviour;
  the Lightbox is its own component.
- **Need:** a Media tile that promises "a plain click opens the Lightbox" needs the Lightbox
  wherever image tiles are composed.
- **Actual result:** the Lightbox (`workbench/_lightbox`) is included and scripted on the article
  page only; on other pages an image tile is a plain link. It depends on a control (its buttons),
  so it waits for the controls gap above.
- **Expected result:** a Lightbox contract; every page that composes image tiles includes it, or
  the tile's contract states the pages that do not.
- **Evidence:** `design-system/components/media-tile.md`, "The Lightbox hook".
- **Next step:** after the control primitives, a Lightbox adoption round.

### A large tile shows a soft picture

- **Source:** owner ruling 2026-09-28 (article media): images keep their own shape.
- **Need:** a thumbnail that fills a wide box (the article page's cover) stays sharp.
- **Actual result:** the tile's stand-in is the thumbnail (about 480px wide); the tile record
  carries no width for the display rendition, so the tile cannot offer it to the browser as a
  larger candidate. Since the cover's migration onto the tile, the cover shows the thumbnail at
  its own size, so a photo cover is smaller than the full original it showed before, until a
  display rendition is listed.
- **Expected result:** the record carries the display rendition's width; the tile offers it in
  `srcset`; the browser picks it for a wide box.
- **Evidence:** the writer-ui report of 2026-10-29 (Media tile round).
- **Next step:** the migration of the cover onto the tile adds the width to the record.

### Audio and video have no playback

- **Source:** owner ruling 2026-10-28 (MediaTile): a playback control is audio's stand-in once
  playback exists; the Lightbox may later take other kinds (an inline video player).
- **Need:** playing a recording in place.
- **Actual result:** audio and video open as downloads in a new tab; audio has no thumbnail.
- **Expected result:** a decided player surface (in the Lightbox or the tile) and the tile's
  playback state.
- **Evidence:** `design-system/components/media-tile.md`, "Behaviour and states", last item.
- **Next step:** a product decision; no round planned.
