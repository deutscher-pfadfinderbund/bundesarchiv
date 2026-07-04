# Roadmap — v1 release

Overarching plan from Part 3 to go-live. Grounded in `docs/design/bundesarchiv-v1.md`,
ADRs 0001–0009, and the 2026-07-04 adversarial plan review (17 confirmed findings folded
in below, each with an owner part). Parts 1–2 are built and green.

Deploy target: single Linux VPS, docker-compose.

## Part 3 — index & search (current)

Pre-tasks (block the index build):

- **Domain fields**: `Article.date` (EDTF value object, Level 0/1 subset, pure bounds
  function), `Article.creator`, `Article.subject_place` (optional, member-visible).
  README codec + factory ripple. Captions live in the body; provenance and the rest of
  the old-system columns live in `custom` (ADR 0009) and may graduate to real fields
  when a member need is proven.
- **Collections persistence**: per-Collection `README.md` tree mirroring the Article
  pattern (name, parent_id, audience) + codec + repository. Without it the cascade has
  no canonical source and the indexer has nothing to walk. Needs an ADR.
- **FTS gating spike**: stock German Hunspell does *not* compound-split under Postgres
  ispell, and unaccent-before-dictionary breaks umlaut lookups. Measure `ts_lexize`
  recall on real corpus (`tests/test_data/archive_items.txt` — multi-MB, read only the
  head) and gate the text-search config on the result.
- **Migration feasibility mapping**: hand-map ~10 real exported records into the new
  model; absorb gaps while the pre-task can still add fields cheaply.

Then: Django 6 arrives as adapter (`src/bundesarchiv/index/`), derived Postgres index,
materialized audience scope, two floor-partitioned tsvectors, `search()`/`rebuild()`
interface, leak tests per tier + SQL ≡ `can_view` equivalence test. Facet counts and
totals are computed over the scoped set only. A `config_version` column stamps rows
against future dictionary changes. Full-rebuild-only sync in v1.

Exit: test-proven query layer against real Postgres (compose). No views, no URLs.

## Part 4 — web/UI + worker

Opens with the HTMX-vs-Datastar prototype (one screen built twice, decide on evidence,
confirm or amend ADR 0004).

- Cataloging forms through the storage port (Django admin stays off), browse/search
  through `search()`, Article detail, visibility preview UI.
- Collection management screens: create, edit, **move** — a move is a visibility-changing
  operation and runs the same preview/over-exposure check as publishing.
- **Media authorization (review: critical)**: every media/thumbnail byte is served by an
  authenticated view that resolves the chain and calls `can_view` before streaming
  (X-Accel-Redirect); the media tree is never web-root reachable. Per-tier media leak
  tests (403/404, existence-hiding) symmetric with row-level leak tests.
- Postgres-backed worker: thumbnails, **incremental reindex**, WebDAV mirror replay,
  periodic full mirror reconcile. The worker forces a full rebuild when `config_version`
  changes.
- **Gate (review)**: no member-visible serving before subtree reindex on Collection
  audience edits exists — materialized scope must not go stale against live viewers.
- Multi-writer arrives: per-Article lock/CAS (parked since Part 1), `visible()`
  combinator at the first full-Article list caller, `is_valid_ulid` gets its route.
- **Media tiering (sketch, decide at Part 4 kickoff):** VPS disk is small; Nextcloud is
  large. Proposal: Nextcloud becomes primary *cold* storage for media blobs, local FS a
  size-capped read-through cache. Content-addressed write-once blobs make this clean
  (no invalidation; eviction safe once cold-verified) — a `TieredObjectStore` adapter
  composing the existing LocalFs + WebDav adapters; port/repository/codec unchanged.
  READMEs/collections stay local-canonical. Serving: Range passthrough + background
  caching for video. **Open before adoption:** durability ownership moves to Nextcloud
  ("byte-exact originals" promise + restic can't back what the VPS doesn't hold — needs
  a cold-side backup answer), and the WebDAV overwrite window gets promoted to a
  correctness item. Alternative to price: attached volume (~€0.04/GB/mo) buys no new
  architecture. The mirror-is-never-a-read-path rule becomes cache-miss-only.

## Part 5 — auth

- Keycloak OIDC (`mozilla-django-oidc`), group claims → real `Viewer`, Archivist group.
- **Keycloak hosting (review: critical)**: compose service + its DB on the VPS, realm/
  client/group bootstrap, realm export into the restic backup set, RAM budget checked.
- First-Archivist bootstrap + grant/revoke runbook (out-of-app by design).
- **Dead-IdP decision (review)**: either accept "IdP down = members can't log in" and
  re-scope design §11 explicitly, or build the minimal cached read path. Decide here.

## Part 6 — release hardening + go-live

- Deploy config is a first-class versioned deliverable, assembled per part along the way
  (Postgres joins in Part 3, app+proxy in Part 4, Keycloak in Part 5): compose files,
  Dockerfiles, TLS, secrets, bring-up runbook.
- **Restic + rehearsed restore = go-live gate** (resolves the "from day one" vs Part 7
  doc conflict: day one of production, not of development). Backup set: canonical file
  tree + Keycloak realm export. The index is disposable and is not backed up.
- Capacity note: corpus estimate vs VPS disk (canonical + mirror + restic ×3), disk-full
  alarm, thumbnails regenerable and prunable.
- Postgres image pinned; major upgrades = deliberate index drop-and-rebuild + documented
  dump/restore for queue state.
- Full-seam security/leak review. Go-live with an empty archive; cataloging starts.

## Part 7 — old-dataset migration (post-release)

One-off import script: old Django + django-filer dataset → README tree. Feasibility
already de-risked by the Part 3 mapping spike. EDTF and creator/place fields exist by
construction. OCR remains deferred; the index shape reserves a body field (ADR 0003).

## Release definition

Archivists catalog, Members browse/search behind Keycloak, backups restore-tested,
deploy reproducible from the repo. Deferred past v1: submissions inbox, Albums,
Carriers, public link sharing, OCR/full-content search.
