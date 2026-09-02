---
name: dispatch-wave
description: Architect procedure for running a wave of writer subagents. Use when decomposing a feature, fix set, or refactor into per-module writer dispatches — brief mechanics, fences, sequencing, and how to read reports.
---

# Dispatch a wave

The architect thinks in modules and interfaces; writers implement one module each. A writer forced past their fence has found an architecture weakness — that report is a *deliverable*, not a failure.

## Decompose

1. Read `MODULES.md` and the relevant package `CLAUDE.md`s. A task maps to modules; a task that maps to no module means the module is missing — design its seam first (interface: signature + invariants + error modes + who calls it), or record an architecture candidate instead of dispatching.
2. **Interface-first**: for cross-module features, the brief ships the seam; the writer fills in behind it. Seam consumers dispatch after seam owners. If you cannot state the seam crisply, you are not ready to dispatch.
3. One writer per task. Writers sharing a worktree run **sequentially** (git index races); parallel writers need disjoint worktrees.

## Brief mechanics (each brief is a file on disk)

- State **deltas, not absolutes**; the writer reads current reality first.
- Anchor on **symbol names, never line numbers** — they drift between brief-writing and dispatch.
- **Verify every referenced test/function exists** before asserting it does; a wrong "keep the existing test green" costs the writer a search.
- Name **contracts to pin, not test instruments** — the writer reads `tests/CLAUDE.md`'s do-not-write list and picks the instrument; several past briefs prescribed forbidden mechanisms.
- When naming a library call, ask for a **signature check**, not just an import check.
- Explicit **scope fence** + stop conditions ("if this cascades past ~N files, stop and report"). Include: "needing anything outside your fence = STOP and report; that report is a success outcome." A fence names its files **plus their necessary call sites** — an interface change drags its callers, and a fence that pretends otherwise forces the writer to judge instead of read. A brief that DELETES a symbol also fences "everything that greps for it" (prose references included), or the deletion leaves dangling names by construction.
- Worktree writers: cwd is NOT reliable between a writer's bash calls — instruct them to prefix every command with `cd <worktree> && `, not to cd once. A relative grep that silently hits the main checkout instead reads the WRONG code (this happened; the misread looked like a syntax error).
- The **law-beats-brief clause**: where the brief conflicts with `docs/agents/writer-brief.md` or `tests/CLAUDE.md`, law wins and the writer reports the conflict.
- Ask for **DX feedback (top 3) upfront** in the final report — it is the brief-quality feedback loop.
- Security-sensitive waves: include the adversarial checklist from the writer brief's serialization rules (round-trip tests, delimiter rule) *in the brief*, not only in review.

## Dispatch and read reports

- Writer requirements: TDD with mutation proof, `mise run check` green per commit, full `mise run gate` for the wave's last writer, per-commit summary + gate output verbatim + deviations with reasons.
- Read deviations first — a good writer deviates where law beats brief; verify the reason, then accept or redirect.
- Missing-tool / fence reports feed `docs/tech-debt.md`.
- Consume learnings immediately: a brief-mechanics lesson goes into THIS skill, a law lesson into the law file, a pattern lesson into the ledger entry — in the same session. No retro archives (project ruling: implement learnings directly; archives are archaeological remains).
- Map rows: writers update them same-commit (see update-module-map skill); check the report mentions it when a module or interface changed.
- Cross-module composition tests (leak matrix, e2e, journeys) are the architect tier's to own — never assigned to a single-module writer.

## On failure

Any rule breach or unexpected red stops the wave line. Investigate the cause chain first — brief error, law gap, missing seam, wrong decomposition — and fix at that level. Only then consider a mechanical gate, and only for a failure class that is mechanically checkable; a gate added without a named systemic cause is itself a debt entry. Blindly adding tests or gates treats symptoms.

## Close the wave

Wave hygiene: re-measure the indicator on any ledger entry the wave touched. Prose added to law/map files gets the same scrutiny as code — an addition without a deletion is suspect.
