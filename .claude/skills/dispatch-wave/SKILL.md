---
name: dispatch-wave
description: Architect procedure for running a wave of writer subagents. Use when decomposing a feature, fix set, or refactor into per-module writer dispatches — brief mechanics, fences, sequencing, and how to read reports.
---

# Dispatch a wave

The architect thinks in modules and interfaces; writers implement one module each. A writer forced past their fence has found an architecture weakness — that report is a *deliverable*, not a failure. The writer's own rules live in `writer-discipline` and `.claude/agents/`; a brief restates none of them.

## Decompose

1. Read the relevant package `CLAUDE.md`s (root `CLAUDE.md`, "Module map"). A task that maps to no module means the module is missing: design its seam first (signature, invariants, error modes, callers), or record an architecture candidate instead of dispatching.
2. **Interface-first**: for a cross-module feature the brief ships the seam and the writer fills in behind it; seam consumers dispatch after seam owners. A seam you cannot state crisply is not ready to dispatch.
3. **Parallel when fences are disjoint**, each unit in its own worktree, merged in order. Sequence only units that share a file or consume another's seam; writers sharing one worktree always run in sequence (git index races).
4. **Model per unit**: Sonnet for mechanical units (copy, CSS moves, test helpers, docs, render checks); Opus for seams, security, leak and data-loss paths, and finishers that must judge a red. Effort `high` or lower and one writer per screen part: the stream watchdog kills a turn that streams nothing for minutes, and every retry starts over.
5. Cross-module composition tests (leak matrix, e2e, journeys) belong to the architect tier, never to a single-module writer.

## Brief mechanics (each brief is a file on disk)

- Run `python3 .claude/skills/dispatch-wave/scripts/check_brief.py BRIEF.md` before every dispatch and fix every finding; mark a path the task creates `path` (new). A name in prose the script cannot see is still yours to verify.
- **Dispatch by agent type**: `writer`, `writer-ui`, `reviewer` or `design-gate`. The brief names topic skills beyond the preloaded ones: `ui-build` for a writer touching a template; `adversarial-input` for a `writer-ui` unit that parses a form field, touches a fail-closed function or renames anything a browser sends — and it names those pairs and functions.
- **Worktrees**: dispatch with `isolation: worktree`; it branches from your current HEAD where `worktree.baseRef: "head"` is set, else from origin — then create the worktree from local `main` yourself and name its absolute path in the brief. A controller pinned by `EnterWorktree` pins every agent it dispatches to its own worktree: leave the pin first.
- State **deltas, not absolutes**; the writer reads current reality first. Cite the task's `docs/tech-debt.md` entry by number: its evidence pointers replace a grep sweep.
- **Onboarding is a cost**: name the exact sections to read (file + heading), not whole files.
- Sketch **interface invariants and the indicator, not field lists**: on a branch others are reshaping, a concrete signature is a guess that reads as an instruction.
- Name **contracts to pin, not test instruments**: the writer picks the instrument under `tests/CLAUDE.md`.
- **Verify at the source** every load-bearing claim before it enters a brief or a ruling: a library call's signature, a framework's default behaviour, the code-behaviour premise of a grilled or ADR-backed decision, and that a guard you ask to pin is load-bearing. A wrong claim widens a fence for nothing.
- A brief built on a ruling greps `docs/requirements/` for every later ruling on the same subject.
- Two items that touch the same lines: name the item that owns them.
- Review findings handed to a writer come grouped per file, each anchored on its symbol with its covering test.
- Ask for **DX feedback (top 3)** in the report: it is the brief-quality loop.

The fence:

- An explicit **scope fence** plus stop conditions ("past ~N files, stop and report"), with "needing anything outside your fence = STOP and report; that report is a success outcome". A fence names its files plus their necessary call sites.
- A signature or return-type change fences every caller from `git grep`, `tests/e2e/_corpus.py` included. `test:affected` adds e2e only for modules the browser setup imports directly; for any other module the brief names `test:e2e`.
- A UI unit's fence names its CSS (tokens, components, page sheet).
- A brief that cuts an import cycle lists the whole chain, traced in the code.
- **Deletion**: the fence covers everything that greps for the symbol, prose that states the removed mechanism in other words, and tests that re-derive a value a new owner now builds. "Plus their tests" means tests of the deleted contract only; a test that reached a live contract through the deleted symbol moves to the surviving path. Collapse what the deletion makes redundant and re-check every claim the touched docstrings make.
- Cuts of leak, deny or access tests never ride in a general deletion brief: their own dispatch, each cut owner-approved (the auto-mode classifier stops a mixed batch halfway).
- **Rename**: name every place that keys on the old name as data (gallery state names pair baseline and new screenshots), and ask for a grep of negative assertions (`"old" not in body`) for every renamed string: they pass vacuously once the old string is gone.

UI and pixels:

- A browser-behaviour finding names the platform where it fails. A fix that adds native `required` or other validation lists the tests and gallery states that submit empty fields.
- Pixel-neutral wave: the gallery covers only its listed states; ask for a computed-style probe over the touched roots too (error modes, open folds, hover, focus).
- A sanctioned pixel change inside a pixel-neutral wave moves the baseline: name the new baseline dir for every later slice. A unit that adds corpus fixtures moves every list state in `test:gallery-diff`: say so instead of "only the X states may change".

Data and runtime:

- **Dependency upgrades** list the new version's changed defaults (timeouts, which responses swap, whether swapped scripts re-run), not only renamed APIs.
- A data rewrite states its safety check at the raw level it rewrites (keys, body bytes, comments): a decoder drops what it does not model. A new validation rule names the paths it runs on.
- A brief that relies on a lock names every process that writes the same data and whether the lock reaches each.
- A live-backend run gets a diagnostic budget and prints what it observed on failure.

## Dispatch and read reports

- Read deviations first: a good writer deviates where law beats brief; verify the reason, then accept or redirect.
- Consume learnings in the same session: a brief-mechanics lesson goes into this skill, a law lesson into the law file, a pattern, missing-tool or fence report into `docs/tech-debt.md`. No retro archives.
- A fixer applying review dispositions that involve a design choice stops and asks the owner, even under an announced silence rule.
- A fix ruling from the controller gets the same scoped re-review as any fix round.
- A writer that stalls twice at the same step (watchdog, no process of its own running): drop the step from its task and run it yourself. After a third stall, a fresh finisher starts from the commits on disk and re-derives the mutation proofs.

## On failure

Any rule breach or unexpected red stops the wave line. Find the cause chain first — brief error, law gap, missing seam, wrong decomposition — and fix at that level. A mechanical gate comes last, only for a mechanically checkable failure class; a gate added without a named systemic cause is itself a debt entry.

## Close the wave

- Before merging each unit (or 2–3 tiny ones together): `ponytail-review` (what to delete), then `code-review` at `medium` or above (`low` reads the diff once, skips tests and verifies nothing), both on the explicit range `git diff main...<branch>` (given a bare branch name, a review reads code already on main). Bugs come last because cuts change code; the writer already ran `simplify`. Fix confirmed findings first; no second review round.
- Merge from the main checkout with `.claude/skills/dispatch-wave/scripts/merge.sh <branch> -- mise run check`. The writer ran `test:affected`; the full gate runs once, in the pre-push hook — never per unit or per merge.
- Land commits that append to a doc after the branches that append to the same file.
- A rename merged while other writers run: at their merge, grep each branch's new test lines for the old spelling (a negative check passes vacuously, aliases keep old GETs green).
- Wave hygiene: re-measure the indicator on every ledger entry the wave touched. Prose added to law or map files gets code scrutiny: an addition without a deletion is suspect.
