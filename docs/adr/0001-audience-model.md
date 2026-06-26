# Audience model: cascading inheritance from a single owning Sammlung

An Article's **Audience** is a rung on the ladder Public ⊃ Members ⊃ named Keycloak Group(s) (groups are OR-combined and always a subset of Members). Each Article belongs to **exactly one owning Sammlung**, and Sammlungen form a single-parent tree; the **effective Audience is the nearest explicit `audience` walking Article → Sammlung → parent Sammlung → … → root**, where the root defaults to `Members`. An explicit Article-level Audience **wins and may widen, not only narrow** — silent over-exposure is prevented by a **publish-time visibility preview**, not by a tighten-only rule. The **Lifecycle gate overrides everything**: a non-Published Article is Archivist-only.

## Considered options

- **Many Catalogues per Article with most-restrictive (intersection) resolution** — rejected: combining audiences across incomparable group sets is ambiguous and hard to test. Collapsing to a single owning Sammlung removes the problem; thematic many-membership survives as browse-only Collections that never affect Audience.
- **Tighten-only per-item override** — rejected in favour of cascade inheritance (Article setting wins), which is more intuitive (CSS / folder-ACL-like). The lost "can never widen" guarantee is replaced by the publish-time visibility preview ("can never widen *silently*").

## Consequences

- Effective Audience is computed by **one pure function** (Lifecycle gate → nearest-explicit-audience up the Sammlung chain → root default). That function must be the single source for list filters, detail authorization, and the search-index filter — duplicating it is the top leak risk.
- Group membership is **read from Keycloak claims per request** and never stored by the app.
