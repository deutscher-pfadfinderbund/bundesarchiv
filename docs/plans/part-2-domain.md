# Part 2 — Domain core (build plan)

Adds the **behaviour** over the Part 1 data shapes (`src/bundesarchiv/domain/models.py`):
Collection-tree resolution, the **pure effective-Audience function** (with field floors), and a
`can_view`-style predicate. Implements the access model of [ADR 0001](../adr/0001-audience-model.md)
and §4 of the [v1 design](../design/bundesarchiv-v1.md). Still **pure Python, no Django**
(per [conventions](../conventions.md)); all data is **injected** (Articles/Collections passed in,
group membership passed in — never fetched here).

This is the single source of truth the [v1 design](../design/bundesarchiv-v1.md) flags as the top
data-leak risk: list filters, detail authorization, the search-index filter, and the publish-time
visibility preview must all route through *this* code and nowhere else.

## Modules (→ ADR 0001)

All under `src/bundesarchiv/domain/` alongside the existing `models.py`. Pure functions /
frozen-dataclass value objects; no IO, no framework, sync. Behaviours below — concrete signatures
are left to the implementer.

- **Collection tree** — resolves an Article's owning Collection chain (Collection → parent → … →
  root) from an injected set/lookup of Collections. Single-parent tree; detects cycles and missing
  parents fail-closed.
- **Viewer** — a value object describing *who is asking*: `Archivist` | `Member` (with the Keycloak
  group names they hold) | `Public`. Inert data injected per request; this module never reads
  Keycloak.
- **Effective Audience** — the one pure resolver: Lifecycle gate → nearest-explicit-Audience up the
  Article→Collection chain (root default `Members`) → the resulting rung on the ladder
  Public ⊃ Members ⊃ named Group(s).
- **Field floors** — projects an Article down to what a Viewer at a given effective Audience may
  see; the Archivist-only fields (`physical_location`, `physical_description`, and provenance/notes
  as the model grows) are floored regardless of Audience.
- **`can_view` predicate** — given a Viewer and an Article (+ its resolved chain), a pure
  yes/no, fail-closed.

## Build steps (TDD — red → green → refactor, tiny commits)

1. **Typed domain errors** — a domain-owned hierarchy (`domain/errors.py`, its **own** base) for
   the access-model errors this part needs (e.g. a broken/cyclic Collection tree). Do **not** extend
   persistence's `ArchiveError`: the pure core must never import `persistence` (the dependency runs
   `persistence → domain`, never the reverse). No logic yet. _Commit._
2. **`Viewer` value objects** — frozen dataclasses for `Archivist`, `Member(groups=…)`, `Public`.
   Tests: construction + equality only; groups held by a Member are an immutable set/tuple. _Commit._
3. **Collection chain — happy path** — resolve an Article to its `[Collection, …, root]` chain from
   an injected lookup. Red: a 3-deep tree returns root-last (or root-first — pick and pin it).
   Green: the walk. _Commit._
4. **Collection chain — fail-closed edges** — one red→green per edge: missing parent raises (not
   silently truncates); a cycle raises rather than looping; an Article whose `collection_id` is
   unknown raises. _Commit per behaviour (3–4 tiny commits)._
5. **Nearest-explicit-Audience walk** — the cascade from ADR 0001: take the Article's own Audience
   if explicit, else the nearest ancestor Collection's, else the **root default `Members`**.
   Red→green with fixtures: Article-explicit wins; falls through one empty level; root default when
   the whole chain is silent. _Commit._
6. **Cascade may *widen*** — pin ADR 0001's "Article-level wins and may widen, not only narrow": a
   `Public` Article under a `Members` Collection resolves to `Public`. One focused test. (The
   "no silent over-exposure" guard is the publish-time **visibility preview**, step 10 — *not* a
   tighten-only rule.) _Commit._
7. **Lifecycle gate overrides everything** — a non-`PUBLISHED` Article resolves to **Archivist-only**
   regardless of its (or its chain's) Audience. Red: a `Public` *Draft* is Archivist-only. This gate
   runs first / wins. _Commit._
8. **Group narrowing** — when the effective tier is `GROUPS`, resolve against the named groups
   (OR-combined): a Member in any one named group qualifies; a Member in none does not; an Archivist
   always does. Red→green per case. _Commit._
9. **`can_view(viewer, article, …)` predicate** — compose effective-Audience + Viewer into a
   fail-closed boolean. Fixture matrix across the three Viewer kinds × {Public, Members, Groups} ×
   {Draft, Published}. The fail-closed default (unknown/ambiguous → `False`) is its own test. _Commit._
10. **Field-floor projection** — given a Viewer + Article, return the Article projected to the fields
    that Viewer may see; Archivist-only fields (`physical_location`, `physical_description`, …) are
    floored for non-Archivists even when they can otherwise view the Article. Red→green per floored
    field; an Archivist sees everything. _Commit._
11. **Visibility preview** — a pure "if published now, who sees this and which fields" summary built
    from the same resolver (the ADR 0001 anti-over-exposure mechanism). Thin — it only *reads* the
    functions above; the test asserts it agrees with `can_view`/the projection for each tier. _Commit._
12. **Refactor / consolidate** — extract the shared resolver so steps 9–11 demonstrably call **one**
    function (the "single source" invariant). A test (or type seam) that makes duplicating the logic
    hard. _Commit._

## Test strategy

- **Fixture-driven, no IO** — build small `Collection` trees and `Article`s in-memory and inject
  them; no `ArticleRepository`, no disk, no Keycloak. (`ArticleRepository` from Part 1 is *consumed*
  by the imperative shell in later parts, not by these pure functions.)
- **One viewer-tier matrix** — the core safety net is a parametrized table: Viewer kind × effective
  tier × Lifecycle, asserting `can_view` and the field projection together. This is the regression
  guard against the §11 "duplicated audience logic leaks data" risk.
- **Fail-closed is asserted, not assumed** — each edge (broken tree, unknown collection, silent
  chain, non-Published, group-mismatch) has an explicit test that the answer is the *less-visible*
  one.
- **Replace, don't layer** — behaviours are tested through the public functions, not their internals.

## Done when

- An Article resolves to its Collection chain, with cycles / missing parents / unknown collection
  failing closed.
- Effective Audience matches ADR 0001: Lifecycle gate first → nearest-explicit cascade (may widen)
  → root default `Members` → group OR-combination.
- `can_view` is one pure, fail-closed predicate covering Archivist / Member-with-groups / Public,
  green across the full fixture matrix.
- Field floors keep Archivist-only fields out of non-Archivist projections.
- The visibility preview and `can_view` provably share one resolver (single source).
- No Django dependency anywhere; no Keycloak, Submissions, Albums, or Carriers touched.

## Deferred (not Part 2)

- **Keycloak / OIDC** — extracting real group claims into a `Viewer` is **Part 5 (Auth)**; here the
  Viewer's groups are injected test data.
- **Public link-sharing** — the `Public` Viewer exists in the model, but the no-Keycloak public
  serving path is deferred (v1 design §2).
- **Submissions** (`Submitted` state / Archivist inbox), **Albums** (browse-only grouping),
  **Carriers** (multiple physical objects) — all post-v1; out of scope and not modeled here.
- **EDTF date handling** — listed under "Domain core" in the design; tracked separately and not
  required by the access model, so it is *not* gated by this plan.

## Roadmap (Parts 2–4)

- **Part 2 (this doc)** — pure domain core: Collection tree + effective-Audience + field floors +
  `can_view`. Still framework-free.
- **Part 3** — derived **Postgres** index + **German FTS** (`to_tsvector('german')`, facets,
  numeric `ref_code` sort), every query scoped by *this* part's resolver. **Django arrives here.**
- **Part 4** — **web / HTMX** UI (cataloging forms, browse/search, detail + media, visibility
  preview) + the **Postgres-backed background worker** (async WebDAV mirror replay, restic DR).
