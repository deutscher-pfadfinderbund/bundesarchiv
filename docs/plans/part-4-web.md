# Part 4 — Web/UI + Worker: Plan

Status: DRAFT (Fable-designed 2026-07-04). Infra half is fully specified and
user-independent; UI half carries design constraints + open questions that
resolve at Part 4 kickoff (see `part-4-ui-ideas.md` owner questions + the
HTMX/Datastar prototype outcome). Companion ADR drafts: 0013 (CAS), 0014
(incremental reindex).

## Sequencing

```
4.0 prototype (decides ADR 0004 amendment)     [needs owner]
4.1 CAS in repositories (ADR 0013)             [user-independent]
4.2 worker + incremental reindex (ADR 0014)    [user-independent]
4.3 media auth seam + thumbnails               [user-independent]
4.4 dev-viewer mechanism                       [user-independent]
4.5 browse/search UI      ─┐
4.6 article detail + media │ [prototype winner + ideas-doc answers]
4.7 cataloging forms       │
4.8 collections mgmt + preview widget ─┘
4.9 mirror replay + reconcile jobs
4.10 hardening: staleness gate tests, leak tests for every route
```

4.1–4.4 can be built before/while the prototype decision settles — none of
them render HTML.

## 4.0 Prototype (decision task)

One screen built twice: the **cataloging form** (upload-heavy, combobox
autocomplete, per-field autosave) — the ideas-doc analysis says this is the
only screen where HTMX and Datastar genuinely diverge. Timebox; decide;
amend/confirm ADR 0004; discard both prototypes.

## 4.1 CAS (ADR 0013)

- `Article.version` surfaces through the repository; `update(ulid, mutate,
  expected_version)` raises `StaleVersion` (ArchiveError child) on mismatch.
- Same for `CollectionRepository` (collection edits are access-control edits).
- Conformance test: two racing updates → exactly one winner, loser gets
  `StaleVersion`, store at winner's `version + 1`.
- Process-wide mutex around load-check-write; single-app-process rule goes in
  the deploy runbook.

## 4.2 Worker + incremental reindex (ADR 0014)

- Postgres-backed worker (Procrastinate or django-tasks-db — implementer
  evaluates both against: Django 6 compat, table-only state, dead-simple
  deploy; records choice in the task report; no Redis, no broker).
- Jobs are REFERENCES (`reindex_article(ulid)`, `reindex_subtree(collection)`,
  `full_rebuild()`); execution recomputes from canonical. Idempotent, safe to
  re-run, no payloads.
- Synchronous in-request index updates on every canonical write path; failure
  → enqueue + UI warning, never fail the canonical write.
- Scheduled reconcile `full_rebuild()` (nightly default) + `config_version`
  check on deploy.
- THE GATE (roadmap): no member-visible route ships before the staleness test
  passes — narrow a collection audience, assert the member's next search
  excludes descendants, no worker involvement.

## 4.3 Media auth seam + thumbnails

- ONE function: `media_response(article, media_ref, request) -> HttpResponse`,
  called only after `can_view` passed for the resolved chain. Internals:
  X-Accel-Redirect to an internal-only location backed by the local store
  (nginx `internal;`), correct Content-Type from MediaRef, Range delegated to
  nginx. The public URL namespace never encodes filesystem paths; media URLs
  are `/media/<article-ulid>/<content-hash>` — resolution happens in the view.
- Denial semantics: 404 (existence-hiding), identical for "no such article",
  "no such blob", "not permitted" — mirrors search invisibility.
- Thumbnails: worker job per image blob (content-hash keyed, regenerable,
  pruned freely, NOT backed up); served through the same seam with the same
  checks (a thumbnail leaks the image).
- Per-tier media leak tests: restricted article's media + thumbnail URLs as
  every viewer tier → 404s; published-public article → bytes only via the
  gated route (attempt direct static access → connection-level failure in the
  deploy config test).
- Tier-miss stream path (Part 7 tiering) explicitly NOT built — the seam's
  shape (`media_response`) is the openness (roadmap rule).

## 4.4 Dev-viewer mechanism

Part 5 brings Keycloak; Part 4 needs viewers NOW. A `DevViewerMiddleware`
reading a signed cookie set by a dev-only switcher view. Existence gated on a
dedicated settings module (`settings_dev.py`) that the production settings
never import — not a flag inside prod settings (flags get flipped; missing
code cannot). The `request → Viewer` seam (`viewer_of(request)`) is the SAME
function Part 5 will re-implement against OIDC claims — one seam, two
adapters, UI code never knows.

## 4.5–4.8 UI tasks (constraints fixed now, layouts at kickoff)

Binding constraints regardless of prototype outcome:
- Server-rendered, progressive enhancement: every screen functions no-JS
  (decade-dormancy rule from ideas doc); URL-as-state for search (shareable,
  bookmarkable, back-button-honest).
- EVERY route resolves the viewer via `viewer_of(request)` and scopes reads
  through `search()` / `can_view` — no hand-rolled filters (§11), enforced by
  a route-level leak-test suite (4.10).
- `visible(viewer, article, chain) -> Article | None` (pair can_view+project)
  gets built at the FIRST full-Article list/detail caller (parked since
  Part 2; this is its trigger). Detail views consume `visible()`, never raw
  repository loads.
- Forms carry `expected_version`; `StaleVersion` → re-render with "Inzwischen
  geändert" diff panel (ADR 0013 UX).
- Visibility preview: ONE server-computed widget (domain `preview()` — exists
  since Part 2), reused by publish flow AND collection-move flow (ideas-doc
  theme #1). Collection move REQUIRES the over-exposure preview before commit
  (roadmap).
- Collection deletion blocked while descendants/articles exist (ADR 0014).
- German UI language per CONTEXT.md glossary; Findbuch vocabulary per ideas
  doc where it fits without inventing features.
- `is_valid_ulid` guards route params (its long-parked caller).
- Uploads: content-hash on receipt, write-once semantics — re-upload of an
  existing blob is a no-op attach.

Open at kickoff (owner input): screen layouts and interaction patterns (pick
from `part-4-ui-ideas.md` options), facet UI shape, cataloging batch-pipeline
scope (dropzone/annotate-queue now vs later), the 8 owner questions in the
ideas doc.

## 4.9 Mirror + reconcile

- Async WebDAV mirror replay via reference jobs (push key X), periodic full
  reconcile (list canonical, diff mirror, repush missing) — mirror stays a
  convenience, never a read path (roadmap rule; changes only at Part 7).

## 4.10 Hardening gate (part exit)

- Route-level leak suite: every URL × every viewer tier (incl. anonymous →
  login redirect), asserting both response status AND absence of floored
  fields in any 200 body.
- Staleness gate test green (4.2).
- Media leak tests green (4.3).
- `/simplify` + adversarial review pass (same discipline as Parts 1–3).

## Explicitly out of Part 4

Keycloak/OIDC (Part 5), restic + deploy hardening (Part 6), tiering/inbox
ingest/OCR (Part 7+, roadmap), public link-sharing, submissions inbox (post-v1).
