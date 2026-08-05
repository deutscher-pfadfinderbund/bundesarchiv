## Dev environment

- Search database (Postgres, host port 5434) runs via Apple's `container`
  CLI, `docker` only when `container` is not installed. (`docker-compose.yml` is a VPS deploy artifact):
  `container system start && container start bundesarchiv-pg`
  (first-time setup: see README).
- Full gate (run before every commit; all must pass):
  `uv run ruff check && uv run ruff format --check . && uv run mypy && uv run pytest`
- Fast type check (~0.2s second opinion; zero-error policy): `uv run pyrefly check`
- Dev server: `DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings_dev uv run manage.py runserver`
- E2E/gallery (excluded from default run): `uv run pytest -m e2e`, `uv run pytest -m gallery -s`
- CSS changes touching position/overlay on `hidden`-gated elements: run the
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

### Design-gate / QA brief

Before reviewing any UI change: render the state gallery (`uv run pytest -m gallery -s`) and run the journeys (`uv run pytest -m e2e`), then judge on live `:8000` pages. See `docs/agents/design-gate-brief.md`.

### Writer discipline

The standing rules for a writer agent (one writer per task, gates green each commit, TDD with mutation-proof, no heavy mocking, deny = plain 404 revealing/changing nothing, German UI / English dev, fixup+fold within your own wave, simplify your own code, report before idle). See `docs/agents/writer-brief.md`.
