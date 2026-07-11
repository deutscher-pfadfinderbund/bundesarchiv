## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues, managed via the `gh` CLI. External PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Design-gate / QA brief

Before reviewing any UI change: render the state gallery (`uv run pytest -m gallery -s`) and run the journeys (`uv run pytest -m e2e`), then judge on live `:8000` pages. See `docs/agents/design-gate-brief.md`.
