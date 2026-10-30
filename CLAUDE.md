## Module map

Each package has a `CLAUDE.md` with its law and one row per module (responsibility, interface,
tests); pick the package(s) a task touches:

- `domain` — pure core: values, access decisions; no IO, no Django · `src/bundesarchiv/domain/CLAUDE.md`
- `persistence` — files-canonical storage: README codecs, repositories, the ObjectStore port; no Django · `src/bundesarchiv/persistence/CLAUDE.md`
- `index` — derived, disposable Postgres search index · `src/bundesarchiv/index/CLAUDE.md`
- `app` — application services: the write shell, background jobs, the Archive handle · `src/bundesarchiv/app/CLAUDE.md`
- `app/web` — Django+HTMX surface: views, auth seam, form parsing, media serving · `src/bundesarchiv/app/web/CLAUDE.md`

- Update procedure: the `update-module-map` skill. Gate: `tests/test_module_map.py`
  (every module has a row or an `Internal:` entry, every `tests:` pointer exists, this section
  points at every package, prose budgets), part of `mise run check`.
- Open architecture and process debt: `docs/tech-debt.md` (map rows cite it as `debt #n`).

## Dev environment

- Search database (Postgres 18, host port 5434) is a native mise daemon (`[daemons]` in
  `mise.toml`), one server for all worktrees, owned by the main checkout: `mise run pg`
  starts it from any worktree (tasks that need it do so themselves); stop it with
  `mise daemons stop postgres` in the main checkout. There is no dev compose file;
  `compose.yml` is the VPS deploy stack.
- Dev server: `mise run dev`
  (`DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings_dev uv run manage.py runserver`).
- `mise.toml` is the single source of what each command runs.

### When to run what

| Moment | Command |
| --- | --- |
| Inner loop | `mise run test:nodb` (~6s under `-n 4`, no Postgres; `-- -n 0` runs it serially, for `--pdb` and debugging), or path-scoped `uv run pytest tests/<suite>/...` |
| One suite | `mise run test:domain` / `test:persistence` / `test:index` / `test:app` |
| Suites a diff needs | `mise run test:affected [-- BASE] [--dry-run]` — runs the suites `BASE...HEAD` plus uncommitted changes need, stops at the first red; not `check`. |
| Change touches index, search or schema (`src/bundesarchiv/index/`, migrations, search-relevant persistence) | `mise run test:index` and `mise run test:db` — the full gate runs once, at the push |
| Before a push | `mise run gate`. The pre-push hook runs it and starts Postgres itself. |
| Postgres-backed tests only | `mise run test:db` |
| New test in `tests/app/` or `tests/index/` that uses `django_db` | also `mise run test:db` — `check` deselects it (auto-marked `requires_pg`), so `check` alone never runs it |
| UI change | `mise run test:gallery` and `mise run test:e2e`, per the `design-gate` agent |
| A change meant to touch only comments or docstrings (Python, JS) | `mise run quality:comments-only -- BASE` — exit 0 proves no code changed |

Each checkout has its own test database (`test_bundesarchiv_<dir>`), so Postgres-backed
runs in two worktrees may overlap; within one checkout, run them one at a time.

Browser-suite runtimes (mise buffers pytest's progress line — a silent minute is normal, not a hang): both run under `-n 4` (pytest-xdist: one test database, corpus and live server per worker): gallery ~27s, e2e ~37s (serial: ~96s, ~113s), plus a one-time chromium install. Worker DBs are `test_bundesarchiv_<dir>_gwN`; pass `-n 0` after `--` to run serially.

Extra pytest flags go after `--`: `mise run test:nodb -- -k foo -x --lf`.

pyrefly is a second opinion on mypy under a zero-error policy; both are part of
the gate. Every invocation is `uv run pyrefly check src tests scripts` — bare
`pyrefly check` resolves zero files in a worktree.

A raw `uv run pytest -m requires_pg` drags in the browser suites: a command-line
`-m` replaces the addopts e2e/gallery exclusion. Use `mise run test:db`.

Reach the browser suites through their mise tasks, never through a raw
`uv run pytest -m e2e`: the tasks depend on `e2e:browsers`, which installs the
chromium build the current Playwright wants. A dependency bump moves that build,
and only the task path picks the new one up.

CSS changes touching position/overlay on `hidden`-gated elements: run the
e2e suite, not just the gallery — snapshots render but never click
(regression class: fixed-position banner whose `display` rule overrode
`[hidden]` and intercepted clicks).

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues, managed via the `gh` CLI. External PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Binding requirements

Owner rulings live in `docs/requirements/` (`archivist-wishes-2025.md`, `owner-interview-2026-08.md` — access model, rollout stages, storage). Check them before inferring scope or requirements.

### Testing razor

Test depth is proportional to risk: extensive coverage only where a defect is domain-relevant, loses data, or leaks data (owner ruling 2026-08). The do-not-write list, the deny contract (`assert_denied`), and the per-suite ownership map: `tests/CLAUDE.md`.

### Design gate / QA

Before accepting any UI change: render the state gallery (`mise run test:gallery`) and run the journeys (`mise run test:e2e`), then judge on live `:8000` pages. The `design-gate` agent (`.claude/agents/design-gate.md`) runs it; `reviewer` does code review.

### Writer discipline

Writers are the `writer` and `writer-ui` agents (`.claude/agents/`); they preload the `writer-discipline` skill (one writer per task, gates green each commit, TDD with mutation-proof, build for what happens, functional core, imperative shell (tests never patch our own code), deny = plain 404 revealing/changing nothing, German UI / English dev, comments only for what isn't apparent — cite an ADR rather than restating it, fixup+fold within your own wave, simplify your own code, report before idle) plus `adversarial-input` or `ui-build`. Further topic skills are named per task in the task brief.
