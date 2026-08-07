# Design-gate / QA brief

What a design-gate or QA reviewer runs FIRST on any UI change, before reading a
single line of the diff. Two commands cover every canonical screen and every
common flow, so a review no longer re-derives them by hand.

## 1. Render the state gallery

```
uv run pytest -m gallery -s
```

One invocation writes every canonical UI state to `var/gallery/` as a PNG in
BOTH color modes (`<state>.light.png` / `<state>.dark.png`). The states are the
workbench (empty / results / filtered / pane-open / bulk-selection / public),
the create + edit forms, the read view, and the POST-gated confirm surfaces
(bulk-confirm, delete-confirm, publish-preview).
These are the shots that go to the owner for async review — one representative
shot per state, both modes.

Override the output dir with `BUNDESARCHIV_GALLERY_DIR` (e.g. a scratchpad).

## 2. Run the journeys

```
uv run pytest -m e2e
```

The canonical flows driven end to end in a real browser (live server + Postgres
index): search+filter+pane, create draft, edit+save, CAS conflict, Kopieren,
Löschen confirm, publish preview gate, bulk select→confirm→apply. A red journey
is a broken flow — fix it before judging pixels.

Both suites are excluded from the default gate (their `gallery` / `e2e`
markers), so they never slow the fast pre-commit run; you invoke them here on
purpose.

## 3. Then judge on live pages

The gallery is the supplement, not the verdict. Final judgment — interact,
resize, both modes — happens on the live `:8000` pages. Judge against the
review catechism and cue register in `docs/design/design-review-law.md`
(questions 2–4 and 6–8 are the human half; the lintable subset becomes a
test in the rework wave). Restart the dev server
after ANY commit (`:8000` runs `--noreload` and serves stale code otherwise),
then review the URLs the change touches.

## What the gate reports back

Findings come back to the writer as `--fixup` commits targeting the writer's own
wave commits, folded in one `--autosquash` cycle (the owner's clean-history
standing order). Security review is a separate pass and clean-or-blocking on its
own.
