# Bundesarchiv

The domain of the Deutscher Pfadfinderbund (DPB) multimedia archive — a long-lived catalog of ~70 years of photos, audio, video, scans, documents and physical objects, with controlled visibility.

## Conventions

- The application UI and content are **German**; code identifiers and the canonical terms below are **English**. Each term lists its German UI label (*italic*).

## Language

### Core entities

**Article** (*Artikel*):
A single catalog record describing one archived thing — digital file(s), a physical object, or both.
_Avoid_: Item, entry, document.

**Collection** (*Sammlung*):
The single owning, nestable division an Article belongs to, and the source of its Audience. Collections form a single-parent tree. Exactly one per Article.
_Avoid_: Catalogue, Fonds; do not also use "Collection" for thematic grouping (see Album).

**Album** (*Album*) — _deferred, not in v1_:
A future thematic, browse-only grouping of Articles (many per Article, no effect on Audience). Name provisional.

**Carrier** (*Objekt*) — _deferred, not in v1_:
A distinct physical object embodying an Article when one Article has several physical copies/manifestations in different places. In v1 this is collapsed into the single `physical_location` field below; multiple Carriers come later (with Album).

**Reference code** (*Signatur*) — code field `ref_code`:
The identifier an Archivist assigns to an Article and writes on the physical object (e.g. `Foto-1955/007`). Optional, free-text, sorts numeric-aware, soft-unique (duplicates warned, not blocked). It is human-facing metadata, **not** the Article's stable identity (which is an internal ULID).
_Avoid_: signature (false friend — means autograph in English), ref_id (implies identity — the ULID is the identity), call number, ID, key.

### People & audience

**Archivist** (*Archivar:in*):
A member of the designated Keycloak group who catalogs and publishes. (Later: reviews Submissions, too.)
_Avoid_: Archivar (in code), curator, admin.

**Member** (*Mitglied*):
Any authenticated DPB member (identity via Keycloak). In v1, reads/browses/searches at the Members tier.
_Avoid_: user.

**Public** (*Öffentlich*):
An unauthenticated visitor. Public access is a _deferred_ feature for sharing a single Article by link — never a public listing, browse, or search.

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

### Lifecycle

**Lifecycle**:
An Article's workflow state. In v1: **Draft** (*Entwurf*) → **Published** (*Veröffentlicht*). Anything not Published is Archivist-only regardless of Audience.
_Avoid_: status, state.

**Submission** (*Einreichung*) — _deferred, not in v1_:
Material a Member sends to the archive; lands as a **Submitted** (*Eingereicht*) Article in the Archivist inbox, never visible to anyone but Archivists until reviewed and Published.
