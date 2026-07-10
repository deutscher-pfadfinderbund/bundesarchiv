# Item media semantics: articles stay leaves; cover, mixed media, captions

Status: Accepted (owner, 2026-07-10)

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
     entries in the article's ordered `media` tuple, plus sidecar files for
     derived data (e.g. `<content-hash>.ocr.txt`, Part 7). Sidecars are
     regenerable, never canonical.
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
```                                        # no caption line = uncaptioned

**Empty fields are omitted on write.** The loader defaults every missing
optional field (that is what makes old READMEs parse), so `field: null`
lines are pure noise — and READMEs are the human-readable face of the
archive in the mirror. The current codec still emits explicit nulls
(`document_type: null`); that write-side cleanup lands with the caption
change. Loaders MUST keep accepting both spellings.

## Consequences

- Old READMEs parse unchanged (`caption` defaults to `None`) — no migration.
- Captions join the article's FTS document (body weight): `build_row`
  change + `config_version` bump; the reconcile machinery rolls it out.
- The 4.7 form gets per-row caption inputs next to the reorder controls;
  the detail view renders captions under each file.
- "One item with 30 scans vs. 30 items" remains a cataloging convention
  (archivists' guidance doc), deliberately not enforced in code.
