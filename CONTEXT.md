# Bundesarchiv

The domain of the Deutscher Pfadfinderbund (DPB) multimedia archive — a long-lived catalog of ~70 years of photos, audio, video, scans, documents and physical objects, with controlled visibility.

## Conventions

- The application UI and content are **German**; code identifiers and the canonical terms below are **English**. Each term lists its German UI label (*italic*).

## Language

### Core entities

**Article** (*Artikel*):
A single catalog record describing one archived thing — digital file(s), a physical object, or both.
_Avoid_: Item, entry, document.

**Collection** (*Bestand*):
The single owning, nestable division an Article belongs to, and the source of its Audience. Collections form a single-parent tree (shallow in practice: a handful of top Bestände, ≤2–3 levels — owner 2026-08-22). Exactly one per Article. May carry an optional description (owner 2026-08-22).
_Avoid_: Sammlung (superseded UI label — owner ruling 2026-08-22: "Bestand" is law), Catalogue, Fonds; do not also use "Collection" for thematic grouping (see Album).

**Album** (*Album*) — _deferred, not in v1_:
A future thematic, browse-only grouping of Articles (many per Article, no effect on Audience). Name provisional.

**Carrier** (*Objekt*) — _deferred, not in v1_:
A distinct physical object embodying an Article when one Article has several physical copies/manifestations in different places. In v1 this is collapsed into the single `physical_location` field below; multiple Carriers come later (with Album).

**Reference code** (*Signatur*) — code field `ref_code`:
The identifier an Archivist assigns to an Article and writes on the physical object (e.g. `F12/3-b2`). Optional, free-text, sorts numeric-aware, soft-unique (duplicates warned, not blocked). It is human-facing metadata, **not** the Article's stable identity (which is an internal ULID). Audience note (owner, 2026-08-23): Signaturen matter to Archivists; **Members don't really care for them at all** — on shared views the mark's visual rank follows the archivist's need, never above a member's disinterest. **Shape (owner, 2026-08-07):** a Signatur carries **no spaces**, and **8 characters is the practical ceiling** ("they could get longer, but I don't expect them to") — demo corpora and layout renders use codes at or under that ceiling; where a layout needs stressing, the unbounded field is the Titel.
_Avoid_: signature (false friend — means autograph in English), ref_id (implies identity — the ULID is the identity), call number, ID, key.

**Archive** (code term, no UI label):
One archive as one value: the canonical files-store (the `ObjectStore` port) together with the repositories over it. Built per request or job and passed down — the seam the application layer reads and writes the archive through, so a service takes an Archive and never a bare store. `Archive.canonical()` is the one place the canonical store is built from settings.
_Avoid_: context (template context), session (DB session), store (the persistence port it holds).

### People & audience

**Archivist** (*Archivar:in*):
A member of the designated Keycloak group who catalogs and publishes. (Later: reviews Submissions, too.)
_Avoid_: Archivar (in code), curator, admin.

**Member** (*Mitglied*):
Any authenticated DPB member (identity via Keycloak). In v1, reads/browses/searches at the Members tier.
_Avoid_: user.

**Public** (*Öffentlich*):
**Link-accessible**, not the open internet: a visitor holding a capability link, with no login prompt. Anonymous internet browsing does not exist — no public listing, browse, or search, ever (owner ruling 2026-08, `docs/requirements/owner-interview-2026-08.md`). The `PUBLIC` code identifier keeps its name for now.

**Viewer** (code term, no single UI label):
*Who is asking* — the union of Archivist, Member, and Public. The value object the access model takes (with the asker's Group names) to decide what they may see; data only, never reads Keycloak itself.
_Avoid_: user (ambiguous — see Member), requester.

**Audience** (*Sichtbarkeit*):
Who may see an Article — a rung on the ladder Public ⊃ Members ⊃ named Group(s). An Article or Collection may leave its Audience **unset** to *inherit* the nearest one set walking up its owning Collection chain (root default: Members; see ADR 0001) — leaving it unset is distinct from explicitly setting Members, which blocks a wider ancestor. A well-formed Audience names one or more Groups **iff** it is the Groups rung; Public and Members name none.
_Avoid_: visibility (in prose, ambiguous), permissions.

**Effective Audience** (code term):
The single resolved rung an Article actually has, after the Lifecycle gate (a non-Published Article is Archivist-only, above the ladder) and the inherit cascade. Computed by one pure function that every visibility decision routes through (ADR 0001) — never recomputed ad hoc.

**Group** (*Gruppe*):
A Keycloak group. Naming one (or several, OR-combined) in an Audience narrows Members to that subset. Membership comes from Keycloak only.

### Cataloging

**Media-type** (*Medienart*) and **Document-type** (*Dokumenttyp*):
Descriptive classifications of an Article. Free-text with autocomplete, seeded with default values, open to new ones. Not managed entities.

**Tag** (*Schlagwort*):
Free-text keyword with autocomplete.

**Physical location** (*Standort*):
Where an Article's physical original is kept, as free text with a path convention (`Magazin 2 / Regal B / Mappe 14`) + autocomplete. The object's description lives in the Article body, not a separate field.

**Custom fields**:
Arbitrary key/value metadata an Archivist can attach for things the predefined fields don't cover. Always Archivist-only — never shown to Members or the public. To show a field to others, it must become a predefined field (a code change). See ADR 0009.

**EDTF date** (*Datierung*) — code field `date`:
An archival date as an EDTF Level 0/1 string: plain year (`1967`), year-month (`1967-03`), full date (`1967-03-15`), unspecified digit (`196X`), interval (`1960/1969`), or open interval (`1960/..`). Qualifiers `?`, `~`, `%` flag uncertainty/approximation. Stored verbatim; bounds are derived for facet search. Any other EDTF feature is out of scope for v1.

**Date added** (*Hinzugefügt am*) — code field `added_at`:
When an Article entered the archive, UTC. Set once at creation (the legacy import carries the old `pub_date`) and never changed by an edit; a copy is a new Article with its own. Not an archival date — that is the EDTF date. Unknown for trees written before the field existed.

**Index** (*Suchindex*):
The derived, disposable Postgres table rebuilt from the canonical `README.md` files. Holds each Article's resolved effective-audience columns (materialized at build time, ADR 0012) and searchable text. Rebuilt in full by `rebuild()`; queried by `search()`. Never canonical — the README is.

### Lifecycle

**Lifecycle**:
An Article's workflow state. In v1: **Draft** (*Entwurf*) → **Published** (*Veröffentlicht*). Anything not Published is Archivist-only regardless of Audience.
_Avoid_: status, state.

**Submission** (*Einreichung*) — _deferred, not in v1_:
Material a Member sends to the archive; lands as a **Submitted** (*Eingereicht*) Article in the Archivist inbox, never visible to anyone but Archivists until reviewed and Published.
