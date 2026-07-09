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

## 4.1 CAS (ADR 0013 v2 — reconciled with built code)

- Article CAS already exists: web form path calls `save(mutated,
  expected_version_from_form)` and lets the FIRST existing-`Conflict`
  propagate. No new error type. The retrying `update()` gets a docstring
  warning: internal idempotent mutations only, never form saves.
- **Collections: real sized work** — `Collection.version` field + collection
  README codec round-trip + versioned load result + `save(collection,
  expected_version)` with `Conflict`, plus conformance tests mirroring the
  Article shape (they have NO version today).
- Conformance test: two racing form saves → one winner; loser's save raises
  `Conflict`; README version (not `changes/*.json`) ends at winner's +1.
- Process-wide mutex + single-app-process rule → deploy runbook. ADR 0013
  supersedes the `.lock` object reserved by ADR 0002/0005.

## 4.2 Worker + incremental reindex (ADR 0014)

- Postgres-backed worker (Procrastinate or django-tasks-db — implementer
  evaluates both against: Django 6 compat, table-only state, dead-simple
  deploy; records choice in the task report; no Redis, no broker).
- New indexer surface (does not exist yet): `index_article(store, ulid)` +
  `index_subtree(store, collection_ulid)`, routing through the SAME
  `build_row` + fail-closed branch as `rebuild()`. Jobs are REFERENCES;
  execution recomputes from canonical. Idempotent, no payloads.
- Every index writer takes the same `pg_advisory_xact_lock` (one project key)
  — closes the rebuild-vs-upsert clobber race (ADR 0014 v2).
- Synchronous in-request index updates on every canonical write path; failure
  → enqueue + a SPECIFIC UI warning ("Sichtbarkeitsänderung noch nicht
  wirksam"), never fail the canonical write.
- Scheduled reconcile `full_rebuild()` (**hourly** default — bounds the
  crash-window over-exposure honestly) + `config_version` comparison at
  deploy/startup (comparison code is new; only the column exists).
- Job-table retention/prune knob in the runbook.
- THE GATE (roadmap): no member-visible route ships before the ADVERSARIAL
  staleness test passes — it calls ONLY the production edit entry point
  (`rebuild()` forbidden inside the test), then asserts the member's next
  search excludes the narrowed content.

## 4.3 Media auth seam + thumbnails

- ONE function: `media_response(article, media_ref, request) -> HttpResponse`,
  called only after `can_view` passed for the resolved chain. Internals:
  X-Accel-Redirect to an internal-only location backed by the local store
  (nginx `internal;`), correct Content-Type from MediaRef, Range delegated to
  nginx. The public URL namespace never encodes filesystem paths; media URLs
  are `/media/<article-ulid>/<content-hash>` — resolution happens in the view.
- Denial semantics: 404 (existence-hiding), **byte-identical** across "no such
  article" / "no such blob" / "not permitted" — same headers, no Content-Type/
  Content-Length divergence — and authorization runs and denies BEFORE any
  blob/thumbnail existence lookup (no timing/metadata oracle).
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
code cannot). The dev cookie is signed with a dedicated dev-only key defined
in `settings_dev.py` — never the production `SECRET_KEY` — so the cookie is
worthless against any prod deployment even if code paths leak. The `request → Viewer` seam (`viewer_of(request)`) is the SAME
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
  (roadmap). The widget is **Archivist-only** (`preview()` surfaces group
  names by design); preview/publish/move endpoints join the 4.10 leak suite —
  Member/Public hitting them → redirect/404, never widget content.
- Collection deletion blocked while descendants/articles exist (ADR 0014).
- German UI language per CONTEXT.md glossary, plain and modern. (REVERSED
  2026-07-10: "Findbuch" banned from UI copy — archaic. Development-facing
  language — code, routes, dev pages, docs — is English.)
- `is_valid_ulid` guards route params (its long-parked caller).
- Uploads: content-hash on receipt, write-once semantics — re-upload of an
  existing blob is a no-op attach.

Decided at kickoff (owner, 2026-07-05): **HTMX confirmed** (prototype evidence,
`prototype-4.0-memo.md`; ADR 0004 stands). Hybrid start page (search field on
top, Tektonik/Bestand entry points below). Results: card list default,
auto-flip to thumbnail grid for photo-heavy result sets. Cataloging:
single-article form first; the batch dropzone→annotate-queue pipeline is its
own follow-up task once the form ships. Upload: progress bar in v1; resumable/
chunked deferred until it hurts. Defaults (owner-delegated): "Ohne Datum" is a
first-class facet value (data honesty); visibility preview speaks human German
("Alle Mitglieder", named groups), not ladder rungs; curated entry points
fixed in code for v1.

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
