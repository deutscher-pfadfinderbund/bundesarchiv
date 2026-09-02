## Module map

- `MODULES.md` — which modules exist, per package (the table of contents).
- `src/bundesarchiv/<pkg>/CLAUDE.md` — that package's law + one row per module
  (responsibility, interface, tests).
- Update procedure: the `update-module-map` skill. Gate: `tests/test_module_map.py`
  (exhaustiveness + prose budgets), part of `mise run check`.
- Open architecture and process debt: `docs/tech-debt.md` (map rows cite it as `debt #n`).

## Dev environment

- Search database (Postgres, host port 5434) runs via Apple's `container`
  CLI, `docker` only when `container` is not installed. (`docker-compose.yml` is a VPS deploy artifact):
  `container system start && container start bundesarchiv-pg`
  (first-time setup: see README).
- Dev server: `mise run dev`
  (`DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings_dev uv run manage.py runserver`).
- `mise.toml` is the single source of what each command runs.

### When to run what

| Moment | Command |
| --- | --- |
| Inner loop | `mise run test:nodb` (~5s, no container), or path-scoped `uv run pytest tests/<suite>/...` |
| One suite | `mise run test:domain` / `test:persistence` / `test:index` / `test:app` |
| Before a commit | `mise run check` — ruff, format, pyrefly, no-DB tests. The pre-commit hook runs the same class of checks. |
| Change touches index, search or schema (`src/bundesarchiv/index/`, migrations, search-relevant persistence) | `mise run gate` — the full gate, mypy and every suite included |
| Before a push | `mise run gate`. The pre-push hook runs it and starts Postgres itself. |
| Postgres-backed tests only | `mise run test:db` |
| New test in `tests/app/` or `tests/index/` that uses `django_db` | also `mise run test:db` — `check` deselects it (auto-marked `requires_pg`), so `check` alone never runs it |
| UI change | `mise run test:gallery` and `mise run test:e2e`, per the design-gate brief |

Browser-suite runtimes (mise buffers pytest's progress line — a silent minute is normal, not a hang): gallery ~70s, e2e ~115s, plus a one-time chromium install.

Extra pytest flags go after `--`: `mise run test:nodb -- -k foo -x --lf`.

pyrefly is a second opinion on mypy under a zero-error policy; both are part of
the gate. Every invocation is `uv run pyrefly check src tests` — bare
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

### Design-gate / QA brief

Before reviewing any UI change: render the state gallery (`mise run test:gallery`) and run the journeys (`mise run test:e2e`), then judge on live `:8000` pages. See `docs/agents/design-gate-brief.md`.

### Writer discipline

The standing rules for a writer agent (one writer per task, gates green each commit, TDD with mutation-proof, no heavy mocking, deny = plain 404 revealing/changing nothing, German UI / English dev, comments only for what isn't apparent — cite an ADR rather than restating it, fixup+fold within your own wave, simplify your own code, report before idle). See `docs/agents/writer-brief.md`.
