# Item media semantics: articles stay leaves; cover, mixed media, captions

Status: Accepted (owner, 2026-07-10). Amended by ADR 0019 (2026-09-24: media stored under their own name), ADR 0023 (2026-10-11: derived text in Postgres) and ADR 0027 (2026-11-07: visibility per aspect of the Article, never per media entry).

## Context

Items regularly carry several media files (the old system capped attachments
at three, forcing zips and artificial splits). The archivists' 2025 wish list
asks for attachment ordering; per-file captions are expected soon; Part 7
adds OCR. The question "should articles nest — folders with per-image
READMEs inside an article?" came up and needed a decision, because every
hardened seam (audience cascade, scope grid, media auth, CAS, incremental
reindex) assumes an Article is a leaf.

## Decision

1. **Articles stay leaves.** An Article is the atomic unit of cataloging and
   visibility. No nested READMEs, no article-in-article. Sub-structure has
   exactly two sanctioned answers:
   - Sub-parts **without identity** (scan pages, tape sides, derived text):
     entries in the article's ordered `media` tuple; derived text lives in
     Postgres, keyed by content hash (ADR 0023), regenerable, never canonical.
   - Sub-parts **with identity** (photos worth their own catalog card):
     promote to a Collection with one Article per part. The batch pipeline
     (dropzone → annotate queue) is what makes this cheap.
2. **First media entry is the cover.** Order is meaning; the tuple's first
   entry represents the item (thumbnail, future result preview). Reordering
   in the form is how an archivist picks the cover.
3. **Mixed attachment types are allowed.** `Article.media_type` (Medienart)
   describes the archival object (the tape, the album); attachments are its
   digital representations and may mix MIME types (audio + case scan).
   Homogeneity is not enforced.
4. **Per-file captions live on the media entry**: `MediaRef.caption:
   str | None`, serialized in the README front matter. NOT a sidecar
   (sidecars are for derived data; a caption is canonical input, and
   sidecars key by content hash — the same bytes attached to two articles
   would wrongly share one caption) and NOT embedded metadata (mutating
   blobs breaks content addressing). Captions are article content: CAS,
   the changes log, mirror/backup and the visibility model all cover them
   with zero new machinery.

   Its sibling is `MediaRef.alt` (an optional `alt:` key on the same
   entry, images only): the description read aloud for people who cannot
   see the image. Same storage, same visibility. The page renders alt,
   else caption, else file name (`MediaTile.alt`). Old READMEs lack the
   key and stay valid.

## Reference shape

```yaml
media:
- filename: lagerchronik-seite-a.mp3      # first = cover
  content_hash: 9f2c41…
  media_type: audio/mpeg
  byte_size: 48213977
  caption: Seite A — Bericht vom Aufbau, Sprecher unbekannt
- filename: huelle-vorderseite.jpg        # mixed types under one Medienart
  content_hash: c01d9e…
  media_type: image/jpeg
  byte_size: 2011458
  stored_name: huelle-vorderseite-2.jpg    # optional: the file's name in the store (ADR 0019)
```                                        # no caption line = uncaptioned

**Empty fields are omitted on write.** The loader defaults every missing
optional field (that is what makes old READMEs parse), so `field: null`
lines are pure noise — and READMEs are the human-readable face of the
archive in the mirror. Loaders MUST keep accepting both spellings.

## Consequences

- Old READMEs parsed unchanged (`caption` defaulted to `None`) — no migration.
- Captions joined the article's FTS document (body weight) through a
  `build_row` change and a `config_version` bump.
- The form got per-row caption inputs next to the reorder controls; the
  detail view renders captions under each file.
- "One item with 30 scans vs. 30 items" remains a cataloging convention
  (archivists' guidance doc), deliberately not enforced in code.
