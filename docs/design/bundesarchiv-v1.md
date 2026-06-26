# Bundesarchiv — v1 Design

A consolidated overview of the first version. Domain terms follow [`CONTEXT.md`](../../CONTEXT.md); decisions are recorded in [`docs/adr/`](../adr/). This document stitches them together and fixes scope.

## 1. Purpose

A long-lived multimedia archive (photos, audio, video, scans, documents) with controlled visibility and German-language cataloging. Replaces an older system whose UI was bound to the Django Admin and embedded in a website. Constraints: self-hosted on a single VPS, German data sovereignty, a decades maintenance horizon, a small maintaining team.

## 2. Scope

| In v1 | Deferred |
|---|---|
| Keycloak login; Archivists catalog directly (`draft → published`) | Member submission + Archivist review inbox (`submitted` state) |
| Full Article data model (below) | Thematic **Albums** (browse-only grouping) |
| Collections with nesting + cascade audience | Multiple physical **Carriers** per Article |
| Member browse + faceted search (Members/group tier) | **Public** single-Article link sharing (+ the no-Keycloak public path) |
| Files-canonical storage + swappable port (local-FS primary) | OCR / full-content search (index shape reserves a "document body" field) |
| Derived Postgres index (German FTS) | Structured physical-location tree |
| Image thumbnails; native browser players | git-backed history upgrade |
| Media originals kept byte-exact | |

Migration of the old dataset is a **one-off administrative task** (import script), not an app feature.

## 3. Actors

- **Public** — unauthenticated; deferred (link-share only, never a listing).
- **Member** — authenticated DPB member (Keycloak); browses/searches at Members tier.
- **Archivist** — a designated Keycloak group; catalogs, manages vocabularies, publishes.

## 4. Access model  (→ ADR 0001)

Two independent axes:
- **Lifecycle:** `draft → published`; anything not Published is Archivist-only. "Withdraw" = back to `draft`. Delete = rare, recoverable trash action (`status` flag; the object never moves).
- **Audience:** a ladder `Public ⊃ Members ⊃ named Keycloak group(s)` (groups OR-combined within a Collection). Each Article belongs to **exactly one owning Collection**; Collections form a single-parent tree. **Effective audience = the nearest explicit `audience` walking Article → Collection → parent → … → root** (root default = `Members`). An explicit Article-level audience **wins and may widen**; a **publish-time visibility preview** prevents silent over-exposure.
- **Field floors:** `physical_location`, `provenance`, internal notes are **Archivist-only regardless of audience**, applied as a projection inside the one effective-audience function.
- This is **one pure, test-guarded function**, the single source for list filters, detail auth, the search-index filter, and the visibility preview.

## 5. Domain model  (→ `CONTEXT.md`)

**Article** fields: `ref_code` (*Signatur* — optional, free text, numeric-aware sort, soft-unique, **not** the identity), `title`, `creator`, `provenance`, `subject_place`, `physical_location` (free text + autocomplete, path convention) + optional `physical_description`, `date_edtf` (EDTF → derived `date_lo`/`date_hi`/`uncertain`), `media_type` + `document_type` (free-text + autocomplete, seeded defaults), `tags` (free + autocomplete), owning `collection`, `lifecycle`, `audience` (+ `audience_groups`), an **ordered** `gallery` of N media with captions, free-text Markdown `description`. Identity = an immutable **ULID**.

**Collection** (*Sammlung*): owning, nestable division; carries the base audience.

## 6. Storage & persistence  (→ ADR 0002)

- **Canonical = plain files on disk.** One directory per Article (named by ULID): a **`README.md`** (YAML front-matter + Markdown body = source of truth; auto-rendered by file browsers / Git hosts / Nextcloud Rich Workspace, with a "managed by the app" marker), write-once `media/`, append-only `changes/<ulid>.json`, and `.snapshots/` for shallow undo.
- **Swappable storage port** — 6 ops: `read`, `writeAtomic`, `putLarge`, `list(prefix)`, `exists`, `delete` (no append/move/lock). Adapters: **local-FS (v1 primary)**, WebDAV/Nextcloud, S3.
- **App is the sole writer** — durable per-Article lock object + pinned write order (media first, README.md last = the commit). Atomic write per adapter (FS = temp→fsync→rename→fsync-dir).
- **Backup = restic** (rehearsed restore). **Nextcloud** = optional strictly-read-only browse mount + backup hedge; never canonical, never writable.

## 7. Search & index  (→ ADR 0003)

Derived, rebuildable **PostgreSQL** index. German FTS (`to_tsvector('german')` + `unaccent` + Hunspell compounds), facets (Collection tree, media/document-type, tags, EDTF date range/decade), ICU numeric `ref_code` sort. Every query is scoped by the effective-audience function and is **field-floor-aware** (a viewer can't match an Article via a field above their floor). `bin/reindex` rebuilds from `README.md` files.

## 8. Media

Originals byte-exact, write-once. Image thumbnails (+ optional PDF first page) as derivatives. Native browser `<img>`/`<video>`/`<audio>`; PDF inline/download. No transcoding (odd formats convert-on-ingest, an admin task).

## 9. Framework  (→ ADR 0004)

**Django + HTMX** (server-rendered; Alpine.js only for local UI). The Django **admin is not the cataloging UI** (it would bypass the storage port + sole-writer lock); Archivist screens are custom forms through the port. Background jobs on a single **Postgres-backed worker** (no Redis). Keycloak OIDC via `mozilla-django-oidc`.

## 10. Components to plan (the build "parts")

Each is a unit with one clear responsibility and a defined seam — to be planned and built independently:

1. **Persistence port + local-FS adapter** — the 6-op interface, atomic write, sole-writer lock, README.md + media + changes/snapshots layout. *Foundational; everything sits on it.*
2. **Domain core** — Article/Collection model, EDTF handling, and the **pure effective-audience function** (with field floors). Framework-light.
3. **Index & search** — Postgres projector, `reindex`, German FTS, facets, field-floor-aware queries.
4. **Web & UI** — Django views + HTMX templates: cataloging forms, browse/search, detail + media, visibility preview.
5. **Auth** — Keycloak OIDC login + group-claim extraction feeding the audience function.
6. **Task worker** — Postgres-backed jobs: thumbnails, reindex (later OCR).
7. **Migration** — one-off admin import from the old Django + django-filer dataset.

## 11. Key risks

- **Dormancy, not framework churn, is the real killer** → reproducible deploy config; serve Public+Published without a Keycloak round-trip so a dead IdP degrades to "can't log in," not "archive offline."
- **Duplicated effective-audience logic leaks data** → one pure function + fixture tests per viewer tier.
- **Unverified backups** → restic from day one + a rehearsed restore runbook.
- **German search quality** (compounds, OCR noise) → validate against real data; the index is swappable.
