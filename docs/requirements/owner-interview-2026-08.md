# Owner interview 2026-08 — ratified requirements and audit consequences

Source: project-review interview with the owner (2026-08-05), conducted to
separate real requirements from accumulated assumptions. Statements below are
the owner's rulings; each section ends with the concrete consequences for the
codebase. This document is binding input in the same way as
`archivist-wishes-2025.md`.

## Rollout plan (definitive)

1. **Deployment 1** — no content: preview of the UI and capabilities for the
   archivists. **Editing (cataloging form, bulk edit) is part of this
   preview.** Search may be rudimentary; the full FTS/facet feature set is
   not preview-blocking.
2. **Deployment 2** — ingestion of the existing data (real data, not
   samples: "archivists will judge the system on their own data").
3. **Switchover** old → new system once the archivists are happy.

The preview exists so archivists "check out the system and tell me early if
they need anything else" — feedback loop first, completeness second.

## Storage

- **Target state:** Nextcloud (a Hetzner StorageBox, WebDAV) is the canonical
  long-term store. The archive server hosts only ephemeral data (search
  index, thumbnails). Everything important lives in media files and Markdown.
- **v1:** filesystem backend only. Graduation to WebDAV comes later; the
  modular persistence layer exists exactly so this switch is possible.
  Multi-tiered persistence (local read cache in front of WebDAV) is
  acknowledged as complicated and **deferred** — a target-state idea, not a
  requirement now.
- **Sole-writer holds for v1.** Humans read the store (mirror) but do not
  write it; "humans edit files in Nextcloud" is a future nice-to-have.
- **Nextcloud inbox directory (near-term):** a directory humans drop batch
  uploads into, which the app ingests. Distinct from the member-facing
  Digitale Eingangskiste web form (`archivist-wishes-2025.md`), which stays
  a future feature. Design constraint: the inbox must live **outside the
  reconciled roots** (or get an explicit carve-out), otherwise the
  reconcile delete pass would treat human drops as orphans.

Consequences:
- Keep backend modularity; do not build the cache layer now.
- Spec the inbox directory when it is scheduled; note the reconcile carve-out.
- The interim filesystem-only stage is the one window where the VPS holds
  the canonical data — it needs an explicit (simple) backup story until the
  WebDAV graduation.

## Access model

Three access paths, no fourth:

1. **Members with Keycloak accounts** — their **Keycloak groups shall be
   used** for group-restricted material. Group truth lives in Keycloak.
2. **Members without accounts** arrive via **secret links** (capability
   URLs, no login prompt), including links that carry group identity. These
   are the "anonymous" users.
3. **Archivists always log in via Keycloak.**

Rulings:
- **No public browsing, ever.** "Public" means "anyone holding a link", not
  the open internet.
- Group visibility is **not needed for the first preview** but is required
  soon after.
- Per-item links (for referencing single articles in e.g. public posts) are
  a future feature.
- The domain ladder Public ⊃ Members ⊃ Groups (GROUPS narrows Members)
  matches the owner's model and stays.

Consequences:
- ADR 0018's **guest-password path becomes capability links**: the link's
  token mints the Viewer cookie directly (revocation = revoke token) instead
  of a shared password prompt. Amend the ADR.
- Promote Keycloak group mapping from "unused for now" (ADR 0018) to
  **required soon** — today OIDC members get `groups=()` and could never see
  GROUPS-tier articles.
- Rename/redefine the `PUBLIC` tier so the code says "link-accessible", not
  "anonymous internet".

## Byte-identical-404 law: relaxed

Owner: "This can be relaxed. We aren't Fort Knox." A plain access-denied
page is acceptable; existence-hiding via byte-identical responses is not a
requirement.

Consequences:
- **Keep** (real leak prevention, inside the owner's testing razor):
  filtering unauthorized content out of search results, listings, and facet
  counts (`tests/index/test_leaks*.py` concept).
- **Drop**: the byte-identical response discipline (the byte-for-byte deny
  comparisons in the route × tier leak matrix and the per-route tests) and
  the anonymous-redirect byte-uniformity contract in ADR 0018. The matrix
  itself survives slimmed — its status assertions and exhaustiveness gate
  are leak prevention (see `tests/CLAUDE.md`). Supersede
  the relevant parts of ADR 0001/0012/0018 with a short amendment.

## Testing philosophy (standing directive)

Extensive testing only for behavior that is **domain-relevant** or where a
defect means **data loss or data leak**. Everything else gets ordinary,
proportionate coverage.

Named example of overkill: the "color math" namespace
(`tests/app/web/color_math.py` + `tests/app/web/test_design_tokens.py`,
~260 lines) for colors that are chosen once. Deletion candidate.

## Migration (blocks deployment 2, not deployment 1)

- The old system's pg dump is inspected; `docs/design/migration-feasibility.md`
  is verified against the real dump (2,485 rows in
  `tests/test_data/archive_items.txt`) and is treated as correct.
- Still needed from the old system: the `document_type` lookup table export,
  the django-filer tables, and the actual media binaries.

## Operations

- Runs on the Bund's VPS; the owner has full control, and others hold root
  access as a fallback.
- The Nextcloud is a hosted Hetzner StorageBox.
- Design intent confirmed: the archive server only hosts ephemeral data;
  **the files (media + Markdown) are the only thing that must never be
  lost** — the search index is disposable and rebuildable by design.

## Addendum (owner, 2026-08-05, post-audit)

- **Backup ruling:** the WebDAV store on the StorageBox is the primary backup
  solution — the file tree is deliberately simple precisely so a full backup
  is nothing more than downloading it as a zip. This resolves the open
  "interim backup story" consequence above: run the WebDAV mirror against the
  StorageBox from day one.
- **No strict deadline** for the preview deployments.
- **Auth is the large blocker** for deployment 1 — ADR 0018 is designed but
  not built (only the dev viewer-switcher exists).
- **WhiteNoise (ADR 0016) is not merged and maybe not complete** — static
  files are still hand-served views.
- **UI ruling:** the owner is not yet happy with the UI — "agents always make
  it very complicated." Simplicity is a requirement, not a style preference:
  UI waves should remove complexity before adding capability.
- **UI construction ruling (2026-08-05):** modern (2026) semantic HTML as the
  basis; sensible components built up in a hierarchy (atoms → molecules →
  layouts → pages); no ad-hoc or redundant components; anything special is
  deliberate; consistency is paramount. Codified as "Construction law" in
  `docs/design/design-system.md`.
- **CSS methodology ruling (2026-08-05):** not fond of the `c-*`/`l-*`
  classes — either full Tailwind or proper use of the cascade; preference is
  modular and flexible, consistent through variables. Resolved to: modern
  cascade-based CSS over the existing custom-property tokens; the prefix
  taxonomy is deprecated, dissolved in one deliberate rework wave.

## UI-system interview (owner, 2026-08-06)

Round 2, scoping the CSS/markup rework wave. Rulings:

- **The wave may touch markup.** Semantic-HTML upgrades are in scope — a
  native element replacing a div construction is part of the same wave, so
  the cascade styles real semantics instead of re-labelled divs.
- **The papier variant is cut.** `components-papier.css` (~513 lines) is
  reachable only via the components-demo toggle, never by the live app; a
  second visual theme doubles every styling decision for nothing. Delete in
  the wave.
- **Bare-element wrapper components dissolve.** An include that renders one
  native element (`button.html`, `input.html`, `select.html`) is more
  complex than the tag; with the cascade styling elements directly these
  wrappers go. Atoms survive only when they bundle real structure
  (signatur_tab, facet_group, ledger_row, pagination, …).
- **Demo pages stay** — "it's like a storyboard." `components_demo` /
  `layouts_demo` are the living styleguide and MUST be updated in the same
  wave as any component change (lockstep, or they rot into stale docs).
- **Materiality ruling: paper material — "but not like the generic Google
  Material look".** The system reads as cut sheets on the gray desk, not as
  floating elevated surfaces: seed-tinted sheets, hairline edges, one 2px
  thickness cue; no shadow stacks, no ripple, no gradients-as-lighting, no
  textures. The papier variant FILE is still cut (one theme only); its
  recipe is promoted to the baseline (cue-register row 8,
  `docs/design/design-review-law.md`).
- **Bevel ruling:** single cut, leading (top-left) corner, drawer-tab family
  only (`.c-sig`, `.c-facet-tab`). Trapezoid (both top corners) is reserved
  for a possible future register-tab component for view navigation — not
  licensed until that component is approved.
- **The mail-client fold is under review.** The owner asked why the results
  table changes shape when a row opens the pane (the 2026-07-10 fold
  ruling). Candidate replacement: stable row anatomy, low-priority columns
  drop as the table narrows. Decide at the design gate on before/after
  renders — not settled here.
