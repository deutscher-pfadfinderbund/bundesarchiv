#!/bin/bash
# SessionStart hook: make a fresh Claude Code on the web sandbox test-ready. Local sessions
# (no CLAUDE_CODE_REMOTE) exit immediately — local dev environments are hand-managed (README).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
uv sync --quiet
bash scripts/dev-pg-cloud.sh
