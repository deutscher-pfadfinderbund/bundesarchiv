# Subagent DX feedback (uncommitted, controller-maintained)

Every dispatch asks agents for optional, light-touch DX feedback. Controller
maintains this file:
- **Addressed → remove the entry** (this file lists only open pain, not history).
- Entries are self-contained (no wave names, no session references, no dates).
- Fields: category / count (times observed) / impact (low·med·high) / the pain
  + what would help.

## Open

- **harness** / count 8 / impact med — now also hits read-only reviewers,
  not just long pytest runs; per-agent frequency rising through the day. — long-running subagents die at the
  600s stream watchdog ("no progress for 600s") mid-task and need a manual
  resume-with-nudge from the controller; no work lost so far, but each stall
  costs a controller round-trip and delays the task by up to 10 min. What
  would help: agents emit a heartbeat line between long tool calls (e.g.
  before/after full pytest runs, the usual stall point).
