# Audience model: cascading inheritance from a single owning Sammlung

An Article's **Audience** is a rung on the ladder Public ⊃ Members ⊃ named Keycloak Group(s) (groups are OR-combined and always a subset of Members). Each Article belongs to **exactly one owning Sammlung**, and Sammlungen form a single-parent tree; the **effective Audience is the nearest explicit `audience` walking Article → Sammlung → parent Sammlung → … → root**, where the root defaults to `Members`. An explicit Article-level Audience **wins and may widen, not only narrow** — silent over-exposure is prevented by a **publish-time visibility preview**, not by a tighten-only rule. The **Lifecycle gate overrides everything**: a non-Published Article is Archivist-only.

## Considered options

- **Many Catalogues per Article with most-restrictive (intersection) resolution** — rejected: combining audiences across incomparable group sets is ambiguous and hard to test. Collapsing to a single owning Sammlung removes the problem; thematic many-membership survives as browse-only Collections that never affect Audience.
- **Tighten-only per-item override** — rejected in favour of cascade inheritance (Article setting wins), which is more intuitive (CSS / folder-ACL-like). The lost "can never widen" guarantee is replaced by the publish-time visibility preview ("can never widen *silently*").

## Consequences

- Effective Audience is computed by **one pure function** (Lifecycle gate → nearest-explicit-audience up the Sammlung chain → root default). That function must be the single source for list filters, detail authorization, and the search-index filter — duplicating it is the top leak risk.
- Group membership is **read from Keycloak claims per request** and never stored by the app.

**Note 2026-07-11 (Part 4.8 collection audience):** the "may widen, not only narrow" rule applies at the **Sammlung level too**, not just per Article. Setting a Collection's audience to a *wider* rung than its parent — e.g. `PUBLIC` under a `MEMBERS` parent — is **legal**, exactly as an Article widening its inherited rung is legal. It is not silent over-exposure because the same backstop covers it: every Article is Draft-gated and only becomes visible after an Archivist clears the **per-article publish-time visibility preview**, which shows the article's *effective* rung (i.e. the widened one). So no article reaches a wider audience without an Archivist seeing that widened rung at publish. Collections are created with an audience (safe — the collection is empty at creation); audience-*editing* an existing collection is a visibility-changing op deferred with the move feature (it re-audiences descendants and wants its own over-exposure subtree preview).
