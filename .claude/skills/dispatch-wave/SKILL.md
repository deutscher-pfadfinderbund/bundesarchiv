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

- State **deltas, not absolutes**; the writer reads current reality first. Cite the task's `docs/tech-debt.md` entry by number — its evidence pointers replace a grep sweep (writers rank this the highest-value line a brief carries).
- Sketch **interface invariants and the indicator, not field lists**. On a branch other writers are reshaping, every concrete signature in a sketch is a guess that reads as an instruction — two of two such guesses were wrong in one wave and following either would have shipped a behavior change. "One render, closed union, always seeded from the saved record" was sufficient; `Conflict(winner, submitted)` was a liability.
- HTML-equivalence constraint? Give the writer the render-diff recipe from `writer-brief.md` (dump states → normalize CSRF/whitespace → diff; throwaway harness named `_zz_*.py` so `check` never collects it — ruff still formats it; a fixture-free script lives outside the tree).
- Pixel-neutral wave? The gallery covers only its listed states. Ask for a computed-style probe over the touched roots too (states the gallery lacks: error modes, open folds, hover/focus) — C2 found a latent bug that way.
- A sanctioned pixel change inside a pixel-neutral wave moves the baseline: name the new baseline dir for every later slice.
- Anchor on **symbol names, never line numbers** — they drift between brief-writing and dispatch.
- **Verify every referenced test/function exists** before asserting it does; a wrong "keep the existing test green" costs the writer a search.
- Name **contracts to pin, not test instruments** — the writer reads `tests/CLAUDE.md`'s do-not-write list and picks the instrument; several past briefs prescribed forbidden mechanisms.
- When naming a library call, ask for a **signature check**, not just an import check.
- A claim about a framework's DEFAULT behaviour ("Django needs setting X for Y") gets checked in the
  framework's source before it goes into a brief: a wrong one widens a fence for nothing (Wave REST
  U3: Django renders `403_csrf.html` without `CSRF_FAILURE_VIEW`).
- **Dependency upgrades:** list the new version's changed DEFAULTS (timeouts, which responses swap,
  whether swapped scripts re-run), not only renamed APIs — the H4 brief missed two that bit. And
  verify a guard is load-bearing before pinning a contract on it: the CSRF header it asked to
  protect was redundant (every form carries the body token).
- Explicit **scope fence** + stop conditions ("if this cascades past ~N files, stop and report"). Include: "needing anything outside your fence = STOP and report; that report is a success outcome." A fence names its files **plus their necessary call sites** — an interface change drags its callers, and a fence that pretends otherwise forces the writer to judge instead of read. A brief that DELETES a symbol also fences "everything that greps for it" (prose references included), or the deletion leaves dangling names by construction.
- A deletion brief also says: collapse what the deletion makes redundant (a settings list left
  identical to prod's), and re-check every claim the touched docstrings make (one cited a test
  that never existed). Its fence also covers prose that states the removed mechanism in other
  words (an env example said "signs the Viewer cookie"), and tests that re-derive a value a
  new owner function now builds.
- Worktree writers: an `isolation: worktree` agent's worktree starts from the remote-tracking base, not local `main`, and a writer may be refused the fast-forward. While local `main` is ahead of origin, create the worktree yourself from local `main` and name its path in the brief; use `isolation: worktree` only when `main` equals origin. (The #62 writer, 2026-09-30, built and gated on a base 225 commits old.)
- Writers share one scratchpad: require task-prefixed log names (`wf-e2e.log`, not `e2e.log`); a
  stale generic log carrying `exit 0` from another agent nearly passed as a result.
- Worktree writers: cwd is NOT reliable between a writer's bash calls — instruct them to prefix every command with `cd <worktree> && `, not to cd once. A relative grep that silently hits the main checkout instead reads the WRONG code (this happened; the misread looked like a syntax error).
- The **law-beats-brief clause**: where the brief conflicts with `docs/agents/writer-brief.md` or `tests/CLAUDE.md`, law wins and the writer reports the conflict.
- Ask for **DX feedback (top 3) upfront** in the final report — it is the brief-quality feedback loop.
- Security-sensitive waves: include the adversarial checklist from the writer brief's serialization rules (round-trip tests, delimiter rule) *in the brief*, not only in review.

## Dispatch and read reports

- Writer requirements: TDD with mutation proof, `mise run check` green per commit, full `mise run gate` for the wave's last writer, per-commit summary + gate output verbatim + deviations with reasons.
- Read deviations first — a good writer deviates where law beats brief; verify the reason, then accept or redirect.
- Consume learnings immediately: a brief-mechanics lesson goes into THIS skill, a law lesson into the law file, a pattern lesson or a missing-tool / fence report into `docs/tech-debt.md` — in the same session. No retro archives (project ruling: implement learnings directly; archives are archaeological remains).
- Map rows: writers update them same-commit (see update-module-map skill); check the report mentions it when a module or interface changed.
- Cross-module composition tests (leak matrix, e2e, journeys) are the architect tier's to own — never assigned to a single-module writer.
- A fixer applying review dispositions that involve a DESIGN choice stops and asks the owner, even when a silence rule was announced — dispositions are owner decisions, not writer judgment.
- A fix ruling from the controller gets the same scoped re-review as any fix round. One such ruling, to sweep every prefix-delete leftover in a folder, raced concurrent deletes of other prefixes; only the re-review caught it.
- A writer that stalls twice at the same step (a harness stream-watchdog stall, no process of its own still running): drop that step from its task instead of retrying, and the controller runs it itself (it may be a required one, such as the gate). After a third stall, hand the task to a fresh finisher agent that starts from the commits on disk and re-derives the mutation proofs.
- A workflow writer stalls when one turn goes silent for 3 minutes (the watchdog counts streamed
  output, not work). A large merged unit at full effort did that six times in a row (Wave LIST U3,
  2026-09-30, ~2.5 h lost; each retry starts over). Pass `effort: 'high'` or lower, keep one
  writer to one screen part, and brief "plan in a few lines, one edit per call, commit after each
  green check".
- A live-backend run gets a diagnostic budget and prints what it observed on failure. "Run once" plus a silent failing assert turned one finding into a guess.
- Before treating a grilled or ADR-backed decision as settled, verify the load-bearing code-behaviour claim against source (today: "Bestand required" was traced to 24 sites before ruling).

## On failure

Any rule breach or unexpected red stops the wave line. Investigate the cause chain first — brief error, law gap, missing seam, wrong decomposition — and fix at that level. Only then consider a mechanical gate, and only for a failure class that is mechanically checkable; a gate added without a named systemic cause is itself a debt entry. Blindly adding tests or gates treats symptoms.

## Close the wave

Integrating parked branches: when the wave added an **exhaustiveness gate over a directory** (module map, leak matrix), list every in-flight branch's new files in that directory before merging. A rebase or `merge-tree` dry run sees overlapping TEXT only, so a gate that asserts over a whole package is invisible until it runs — four unrowed `app/web` modules stopped one integration exactly here.

A dry run (`merge-tree`, rebase preview) describes the tree it was run against. Re-run it
immediately before the merge it sizes; commits landed in between — a docs addendum appended
to a file the branch also appends to — turn a clean file into a conflict per commit. Order
integration so doc-appending commits land after the branch merges when possible.

`rerere` is on in this repo. A replayed resolution stages the result with no unmerged paths,
so `git rebase --continue` refuses with "there are staged changes"; a loop polling
`--diff-filter=U` reads that as "not finished" and stalls. Handle the resolved-but-uncommitted
state, and verify what rerere auto-applied against the original commit — it replays a
judgment onto different surrounding text.

Wave hygiene: re-measure the indicator on any ledger entry the wave touched. Prose added to law/map files gets the same scrutiny as code — an addition without a deletion is suspect.
