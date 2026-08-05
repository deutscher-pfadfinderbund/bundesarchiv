# Prototype 4.0 — HTMX vs. Datastar: comparison memo

Status: DONE (Fable-built 2026-07-04). Decision input for confirming/amending ADR 0004.
**No recommendation in this memo — the owner decides.** Both prototypes are throwaway
(`src/bundesarchiv/app/web/prototype/`, deleted once the decision lands).

What was built: the upload-heavy cataloging form (*Artikel anlegen/bearbeiten*) — the one
screen the ideas-doc analysis flags as genuinely divergent — twice, over ONE shared service
layer (`prototype/shared/`), so every difference below is a framework property, not an
accident of two backends. Same fields, same German strings, same no-JS baseline, same real
service calls (`create_article` / `save_article` / `add_media` hash-on-receipt, domain
`EdtfDate` as the only date judge, distinct-index-value autocomplete).

## 1. LOC + file count

| | Variant A (HTMX) | Variant B (Datastar) | shared |
|---|---|---|---|
| files | 1 view module | 1 view module | 2 modules + urls |
| raw lines | 320 | 384 | 487 |
| code lines (no docstrings/blanks) | ~230 | ~271 | — |
| inline JS | 7 lines (progress bar paint) | 0 (but JS-ish expressions inside `data-on-*` attributes) | — |

The Datastar variant is ~18 % longer. The extra lines are almost entirely the hand-rolled
SSE writer (`_sse` / `_patch_elements` / `_patch_signals` / `_signals`, ~45 lines) — HTMX's
response format is "an HTML string", which Django already speaks. An official Datastar
Python SDK exists that would absorb those lines, at the price of one more dependency.

## 2. Dependency weight + vendoring

| | htmx.min.js 2.0.4 | datastar.js 1.0.0 |
|---|---|---|
| bytes (vendored) | 50 917 | 34 450 |
| gzipped | 16.4 KB | 13.4 KB |
| loading | classic `<script src>` | `<script type="module">` |
| server-side dep | none | none here (SDK optional) |

Both are single self-contained files, no build step, trivially vendorable. Vendoring
friction was Datastar-only: npm's `latest` tag still points at `1.0.0-beta.11`, the npm
package does not ship the browser bundle at the documented path, and the real v1.0.0 bundle
had to come from the GitHub release tag. The v1 release also renamed the SSE events
(beta's `merge-fragments` → `patch-elements`), so beta-era examples/LLM training data are
wrong for v1. htmx 2.x has had a stable wire model for years; every htmx snippet found in
the wild ran unmodified.

## 3. The six interactions, side by side

### Live EDTF feedback (*Datierung*, plan §3.4)
- **HTMX**: `hx-get` + `hx-trigger="input changed delay:400ms"` on the input; server returns
  the echo `<span>`; `hx-swap="outerHTML"` replaces it (class flips with the text). The
  input value rides along automatically as a query param (inputs include themselves).
- **Datastar**: `data-bind-date` makes the field a signal; `data-on-input__debounce.400ms=
  "@get(…)"` fires the action; the WHOLE signal store travels as JSON in a `datastar` query
  param; server answers an SSE `patch-elements` with the same span.
- Verdict: equivalent effort, one honest asymmetry each way — HTMX sends only the one field
  (lean requests); Datastar sends every signal on every keystroke (the debounced echo
  request carries the whole form state as JSON).

### Autocomplete (media_type / document_type / tags, plan §3.8)
- Both use a native `<datalist>` + server-swapped `<option>` lists — no Alpine needed in
  either, which partially answers the ideas-doc question "does Datastar remove the Alpine
  sprinkle": for THIS combobox style (datalist), HTMX doesn't need Alpine either. A custom
  dropdown with ↑/↓/Enter would re-open that question.
- **HTMX**: the input's own `name` puts the term in the query string; one line of wiring.
- **Datastar**: the bound signal name uses dots for nesting (`data-bind-media.type` →
  `{"media":{"type":…}}`), so the server un-nests JSON to find the term. Mildly fiddly.

### Custom-row add/remove (ADR 0009 key/value rows)
- **HTMX**: add = fragment appended via `hx-swap="beforeend"`; remove = empty response over
  `hx-target="closest .custom-row"` — **no ids needed**, the DOM relation ("closest") does
  the addressing.
- **Datastar**: rows need unique ids (`crow-N`), a client-side counter signal (`$nextRow`)
  and explicit SSE patch modes (`append` / `remove`) with selectors. More moving parts for
  the same behavior; the server must know which element to name.

### Upload progress (plan §3.10 — the decisive screen)
- **HTMX**: XHR transport → real `htmx:xhr:progress` events; a `<progress>` element plus a
  7-line inline listener gives a true per-request progress bar. Works today, vendored.
- **Datastar**: fetch() transport → **the browser exposes no upload progress**. The variant
  shows an indeterminate "lädt…" indicator (`data-show="$uploading"`). A real bar would mean
  hand-writing an XHR uploader outside Datastar — at which point the framework isn't
  carrying the screen's hardest requirement.
- This is the one categorical (not stylistic) difference found.

### Autosave (per-field draft, plan §3.6)
- **HTMX**: ONE declaration — an element with `hx-trigger="change delay:600ms
  from:.autosave"` + `hx-include` posts the whole form; the response's status panel swaps in
  and OOB swaps update the hidden ulid/`expected_version`. First autosave of a new form
  creates the draft and the form silently becomes an edit form. Natural fit.
- **Datastar**: `data-on-change__debounce.600ms="@post(…, {contentType: 'form'})"` repeated
  per field (change events would also delegate at the form, so this is style not necessity).
  The `contentType: 'form'` option is required — the default posts JSON signals, which a
  multipart/Django-form endpoint doesn't want. Updating the hidden fields needed
  `patch-elements` (they aren't signals), mixing the two state models in one response.

### Conflict → "Inzwischen geändert" (ADR 0013)
- Identical in both: the shared service surfaces `Conflict` as a tagged outcome; enhanced
  path swaps/patches the warning panel; no-JS path re-renders the full page with the user's
  values intact and the store's current version in the hidden field, so the next submit
  deliberately overwrites. Framework-neutral by construction — CAS lives below the wire.

## 4. No-JS degradation honesty

Byte-for-byte the same baseline in both variants (shared logic, checked by the smoke tests):

| works without JS | how |
|---|---|
| create/edit + save | plain `<form method=post>`, PRG redirect with `?saved=1` |
| conflict handling | full-page re-render, values kept, "Inzwischen geändert" panel |
| add custom row | named submit "Weitere Zeile (ohne JS)" re-renders with one more row |
| remove custom row | blank the key — blank-key rows are dropped on save (documented in UI) |
| autocomplete | initial `<datalist>` snapshot (browser-native matching, no round-trip) |
| upload | native file input + blocking submit, no progress (accepted floor) |
| EDTF feedback | none until save (the save itself still parses server-side) |
| autosave | none (explicit save is the baseline) |

One honesty note: Datastar's attributes are inert without JS **only because** the form also
carries real `action`/`method` and the submit handler is additive. Datastar's own idiom
(bind everything, post signals as JSON) would NOT degrade; keeping the no-JS floor means
deliberately writing forms the HTMX-ish way and treating signals as an overlay. HTMX's idiom
and the no-JS idiom are the same idiom.

## 5. Readability + agent-writability

- **HTMX** reads as annotated HTML: behavior sits on the element it affects
  (locality-of-behavior), responses are plain HTML strings, and the only non-local concept
  is the OOB swap (2 uses). The error classes hit while building: choosing the right swap
  strategy for the echo span (first attempt double-rendered via a redundant OOB + fragment;
  fixed to one `outerHTML` swap), and remembering that progress needs the inline listener.
  Both were visible-in-browser, shallow errors.
- **Datastar** has ONE elegant idea (signals) but three surfaces to hold: the attribute DSL
  with modifier syntax (`data-on-input__debounce.400ms`), JS-ish expression strings inside
  attributes (`evt.preventDefault(); $uploading = true; @post(…)`), and the SSE wire format
  the server must emit exactly. Error classes hit: hand-rolling the event format (`data:
  elements` / `data: signals` line prefixes — silent no-op when wrong), dotted signal
  nesting server-side, the JSON-vs-form POST default, and hidden inputs falling outside the
  signal model. All were silent-failure-shaped until inspected.
- For an agent writing this code: both variants were writable in one session, but v1.0.0
  Datastar knowledge is thin/contradictory in the wild (the beta rename), while htmx
  answers are abundant and stable. The shared bug of the session was framework-neutral
  (media must be stored under the service-minted ulid → create-then-attach; caught by the
  smoke test).

## 6. WSGI fit

Confirmed: **no ASGI need crept in.** Every Datastar response is a finite, one-shot
`HttpResponse(content_type="text/event-stream")` — body built in memory, connection closes,
plain WSGI request/response (see `datastar/views.py::_sse`). Datastar's long-lived-stream
features simply went unused, consistent with the ideas-doc note that v1 has no realtime
requirement. HTMX is ordinary request/response by nature. Neither variant touches
`async`, channels, or streaming responses.

## 7. Neutral observations

- The screen chosen because it diverges did diverge — but in exactly ONE hard place
  (upload progress). Everything else differed in style and line count, not capability.
- Datastar's payoff (server-pushed signal patches, one state model) shows up when state
  fans out across a page; on a single form, most of its patches ended up being
  element patches — i.e., doing what HTMX does, with more envelope.
- HTMX's costs are the known ones: OOB swaps for cross-cutting updates, and any *rendering*
  of client-side state (progress bar) needs a JS sprinkle.
- The no-JS floor constrains Datastar to its least idiomatic subset; it constrains HTMX
  not at all.
- Ecosystem/maintenance (decade horizon): htmx 2.x stable, huge corpus; Datastar fresh at
  v1.0.0 with an event-protocol rename behind it and packaging still settling.
- Gates: ruff/mypy are excluded for `prototype/**` only (per-dir `E501`,`RUF001` ignores +
  `ignore_errors` for the package in `pyproject.toml`) — repo-wide config untouched.
- One change outside prototype dirs + dev_urls: `settings_dev.py` gained `DEBUG = True` +
  `ALLOWED_HOSTS = ["localhost", "127.0.0.1"]` — without it Django refuses `runserver`
  entirely, so the instructions below could not work. Dev-only by construction (prod never
  imports the module; pinned by the existing prod-safety tests).
- Verification level: full test-client round-trips for both variants (create, edit,
  conflict, upload-hash, SSE shape) + a real-browser (headless chromium) load of both pages
  with zero console errors and proof Datastar initialized (the `data-show` span is
  `display:none` in the dumped DOM). Interactive typing/uploading was NOT machine-driven —
  worth 5 minutes of hand-testing at the URLs below.

## Run instructions

```sh
cd /Users/bjebb/Developer/DPB/archive/.claude/worktrees/agent-a6d0aee48bc9aa1f5
# branch: worktree-agent-a6d0aee48bc9aa1f5

# 1. Postgres (skip if already running — `container list` shows bundesarchiv-pg)
container build -t bundesarchiv-postgres docker/postgres/
container run -d --name bundesarchiv-pg -p 5434:5432 \
  -e POSTGRES_DB=bundesarchiv -e POSTGRES_PASSWORD=postgres bundesarchiv-postgres
uv run manage.py migrate

# 2. Dev server (dev settings = prod settings + viewer switcher + prototype routes)
DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings_dev uv run manage.py runserver
```

- Variant A (HTMX): <http://127.0.0.1:8000/prototype/htmx/>
- Variant B (Datastar): <http://127.0.0.1:8000/prototype/datastar/>
- Editing an existing Artikel: follow the redirect after a save
  (`/prototype/{htmx,datastar}/artikel/<ulid>/`).
- Dev-viewer switcher: <http://127.0.0.1:8000/_dev/viewer/> — the prototype form itself is
  not viewer-gated (Archivist-only enforcement is a Part-4.5+ concern), but the switcher is
  wired and can be exercised alongside.
- No-JS check: browser dev-tools → disable JavaScript → both forms still round-trip.
- Articles land under `var/canonical/articles/<ulid>/` (README.md + media/<sha256>);
  a throwaway demo *Sammlung* is auto-seeded on first save.
- Cleanup afterwards: delete `src/bundesarchiv/app/web/prototype/`, the `prototype/` mount
  in `dev_urls.py`, `tests/app/test_prototype_smoke.py`, and the two `pyproject.toml`
  prototype excludes.
