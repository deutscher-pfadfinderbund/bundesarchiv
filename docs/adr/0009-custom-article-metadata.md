# Article metadata: predefined fields plus an Archivist-only custom escape hatch

## Context

A long-lived archive will need fields we did not plan for. Archivists should be able to add
them without waiting for a release. But who may see a field is a leak risk — the field floor
([ADR 0001](0001-audience-model.md)) decides it. A field that was visible by default would leak.
So: let archivists add fields freely, but keep every new field safe by default.

## Decision

Article metadata has two tiers.

- **Predefined fields** — defined in code. Each is marked Archivist-only or visible (to anyone
  who can already see the Article). Two states, no more. (The Article's Audience is what decides
  who sees the Article at all.)
- **Custom fields** — a free escape hatch. An archivist can attach any key/value the predefined
  fields do not cover.

Two rules:

- **Custom fields are always Archivist-only.** There is no per-field setting; the whole custom
  set is hidden from non-Archivists.
- **To make a field visible, promote it to a predefined field — a code change, reviewed.**
  Nothing at runtime, and no default, can expose a new field.

## Consequences

- **Safe by default.** A new field is Archivist-only the moment it exists. Widening it is always
  a reviewed change, never a toggle a typo could flip. Same rule as the rest of the access model:
  unknown means most-restrictive.
- Archivists can record whatever a piece needs right away, as Archivist-only, with no release.
  The trade: showing a field to others costs a code review.
- **Search index (Part 3):** custom fields are Archivist-only, so they can be indexed and searched
  only in an Archivist-scoped view — never one a Member or the public can query.
- **Rejected — per-field visibility levels.** The Article's Audience already says who sees the
  Article. A second per-field ladder is more than we need.
- **Rejected — letting archivists define fields at runtime.** Showing a field is a security choice.
  It belongs in a reviewed change, not a live toggle.
