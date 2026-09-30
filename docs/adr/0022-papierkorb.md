# Papierkorb: a deleted Article is a state, not a missing folder

Status: Proposed (2026-09-30). Amends ADR 0020 ("Hard delete is final for the app"): the hard
delete stays, but only as the Papierkorb's "Endgültig löschen".

## Context

The archivists asked for a Papierkorb: restore what was deleted by mistake
(`docs/requirements/archivist-wishes-2025.md`). The owner took it up on 2026-09-30
(`owner-interview-2026-08.md`, "Rulings of 2026-09-30 (Papierkorb)"). Today "Löschen" removes the
Article's folder on the VPS, its index row, and then the folder on Nextcloud.

## Decision

- **Deleting marks the Article.** Its README records when and by whom it was deleted. The folder,
  its media and its history stay where they are, on the VPS and on Nextcloud. Moving the folder
  would cost a WebDAV `MOVE` per Article and would change every media key.
- **A marked Article is visible to Archivists only, and only in the Papierkorb.** The index keeps
  its row with that narrowest visibility, so search, lists, facets, the detail page, media and
  thumbnails refuse it to everyone else through the one visibility rule they already share. No
  new leak path.
  - The normal list and search leave it out for Archivists too; the Papierkorb page lists it.
  - A marked Article cannot be edited or bulk-edited; restore it first.
- **Restore removes the mark.** Delete and restore are saves: they carry the expected version
  (ADR 0013), write a history file with who did it (ADR 0019), and push like any save (ADR 0020).
- **"Endgültig löschen"** in the Papierkorb is today's hard delete, unchanged (ADR 0020).
- **Every Archivist** may delete, restore and delete for good.
- **Emptied by hand.** Automatic removal after 30 days is ruled right but waits.

## Consequences

- A deleted Article keeps using disk on the VPS and on Nextcloud until it is deleted for good.
- The delete confirm can get lighter: the step is reversible. "Endgültig löschen" keeps the red
  confirm that names the full consequence.
- Collections are not covered; deleting a Bestand stays as it is.
- Restoring an overwritten version (from `history/`) is a separate, later feature.
