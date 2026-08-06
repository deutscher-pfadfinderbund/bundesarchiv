# E2E journeys + state gallery (Part #26)

Browser-driven tests that drive the real app end to end — live server + real
Postgres index + a real browser — plus a one-invocation screenshot gallery of
every canonical UI state. This is the layer unit tests can't see (JS on, HTMX
swaps, two racing tabs) and the standard input for a design gate.

Both suites are **excluded from the default gate** (their `e2e` / `gallery`
markers); the fast pre-commit run never spends a browser render. You invoke
them here on purpose.

## Prerequisites

- Postgres up on `:5434` (the same dev DB the other DB suites use — a down
  Postgres fails, not skips, with a hint).
- The Playwright chromium browser cached (chromium-1228). It is already present
  on this machine; if a fresh checkout needs it: `uv run playwright install
  chromium`. Point `PLAYWRIGHT_BROWSERS_PATH` at an existing ms-playwright cache
  to avoid a re-download.

## Run the journeys

```
uv run pytest -m e2e            # all journeys
uv run pytest -m e2e -q         # quiet
```

Each journey builds its own corpus into a fresh store and runs against
`live_server` (pytest-django). The corpus is rebuilt per test because
`transactional_db` truncates the index between tests — which also isolates the
mutating journeys (create/edit/delete/bulk) from the read-only ones, so order
never matters.

Auth: the `archivist_page` fixture pre-sets the signed `dev_viewer` cookie (the
same value the dev switcher POST writes), so a journey lands authenticated
without a login hop. `public_page` carries no cookie; `no_js_archivist_page` is
the archivist with JavaScript disabled (the no-JS baseline).

## Render the state gallery

```
uv run pytest -m gallery -s
```

One invocation renders every canonical state to `var/gallery/` (gitignored) as
`<state>.<mode>.<width>.png` — both color modes (`light`/`dark`, via emulated
`prefers-color-scheme`) at each width (1440 desktop, 680 narrow). Stable names
so a review brief can reference a shot. Override the output dir with
`BUNDESARCHIV_GALLERY_DIR`.

The states live in `_gallery.py:STATES`: the workbench (empty / results /
filtered / pane-open / bulk cold-start + selection / public), the create + edit
forms, the 4.6 detail read view (member with cover + filmstrip / no-media /
archivist draft), and the POST-gated confirm surfaces (bulk-confirm,
delete-confirm, publish-preview) — the confirm group reached by driving the
affordance, so they appear in the gallery too. Read-only states only: no gallery
render mutates the shared corpus (so every shot shows clean canonical data).

## Add a journey

Add a `def test_*(...)` to `test_journeys.py` (the module carries
`pytestmark = pytest.mark.e2e`). Take `archivist_page` / `public_page` /
`no_js_archivist_page` + `live_workbench`, and — if you need named records —
`e2e_corpus` (a `CorpusHandles` with the draft/published/second ULIDs). Assert
user-visible outcomes (`expect(page.get_by_text(...))`), never internals. For a
flow that starts from a fresh draft, use the `_create_draft` helper.

## Add a gallery state

Add a `GalleryState(name, what, archivist, reach)` to `_gallery.py:STATES`. For
a plain GET state use `_goto("/path")`; for a POST-gated surface write a small
`reach(page, base, corpus)` that drives the affordance (see the `_reach_*`
functions). The smoke test asserts every state × mode × width produced a
non-empty PNG.

## Files

- `conftest.py` — fixtures (per-test corpus, live server, viewer cookies, pages).
- `_corpus.py` — `build_corpus` + the fixed ULIDs the journeys reference.
- `test_journeys.py` — the journeys.
- `test_a11y.py` — the axe-core WCAG 2.2 AA pass over the journey pages.
- `_gallery.py` — the state list + `render_all`.
- `test_gallery.py` — the gallery entry point + smoke test.
- `vendor/` — the vendored axe-core (MPL-2.0; pages are offline-only by design).
