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

- **Dispatch by agent type**: `subagent_type: writer` (code), `writer-ui` (templates/CSS/JS),
  `reviewer` (read-only code review) or `design-gate` (UI review). Each preloads its standing
  skills (`.claude/agents/`); the task brief names any topic skill to load beyond them
  (`adversarial-input` for a UI unit that parses a form field, `ui-build` for a writer touching a
  template).

- State **deltas, not absolutes**; the writer reads current reality first. Cite the task's `docs/tech-debt.md` entry by number — its evidence pointers replace a grep sweep (writers rank this the highest-value line a brief carries).
- Sketch **interface invariants and the indicator, not field lists**. On a branch other writers are reshaping, every concrete signature in a sketch is a guess that reads as an instruction — two of two such guesses were wrong in one wave and following either would have shipped a behavior change. "One render, closed union, always seeded from the saved record" was sufficient; `Conflict(winner, submitted)` was a liability.
- HTML-equivalence constraint? Point the writer at the render-diff recipe in the `writer-discipline` skill, "TDD" (dump states → normalize CSRF/whitespace → diff; throwaway harness named `_zz_*.py` so `check` never collects it — ruff still formats it; a fixture-free script lives outside the tree).
- Pixel-neutral wave? The gallery covers only its listed states. Ask for a computed-style probe over the touched roots too (states the gallery lacks: error modes, open folds, hover/focus) — C2 found a latent bug that way.
- A sanctioned pixel change inside a pixel-neutral wave moves the baseline: name the new baseline dir for every later slice.
- A brief that cuts an **import cycle** lists the whole chain it has to cut, traced in the code (Wave
  REST simplify: moving `FormPanel` alone left the cycle; the field registry had to move too).
- A finding about **browser behaviour names the platform where it fails** (a focus bug that only Safari shows passed every Chromium pin until the journey reproduced Safari's path). A fix that adds native `required` or other validation lists the tests and gallery states that submit empty fields.
- A brief built on a ruling **greps `docs/requirements/` for every later ruling on the same subject** first (the door brief cited the 2026-08-22 ruling and missed the 2026-09-26/27 ones that superseded two of its points; the writer caught it).
- Two items of one brief that touch the same lines: name the item that owns them (the one that rewrites
  them). Otherwise the writer spends turns working out fixup collisions (FTSFIX, 2026-10-11).
- A brief asking for map rows names the 220-character row budget; writers otherwise learn it from a
  red check.
- Review findings handed to a writer come grouped per file, each with its line and the covering
  test's line; a flat list makes the writer regroup and look lines up by hand.
- Cuts of leak, deny or access tests never ride in a general deletion brief: the auto-mode classifier
  stops the batch halfway. They get their own dispatch, after the owner approves each cut (and the
  2026-09-29 ruling keeps redundant ones, `tests/CLAUDE.md`).
- A brief that asks for fixups on a signature change whose callers sit in several stack commits:
  expect a core fixup plus a plain signature commit (no fixup can be green alone; the structure gate
  refuses a shim). Say so in the brief (PILOT, 2026-10-11).
- "Fixup where it folds cleanly, plain otherwise" plus "do not rebase" contradict once a committed
  fixup turns out not to fold. Brief it as: the writer may rebase its OWN commits to reword a fixup
  into a plain commit (REVIEWFIX, 2026-10-11).
- A unit that changes a return type or signature: its fence lists every caller from `git grep`,
  `tests/e2e/_corpus.py` included (the browser corpus calls app code), and it runs `test:e2e`. R1R5
  (2026-10-11) changed `media_text.fill` to return a dict, skipped e2e, and broke every browser test.
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
- A deletion brief says "plus their tests" only for tests of the deleted contract. A test that reached a
  LIVE contract through the deleted symbol moves to the surviving path — the #33 prune dropped the only
  replace-crash test (prior-object-or-nothing) that way, caught in review.
- A deletion brief also says: collapse what the deletion makes redundant (a settings list left
  identical to prod's), and re-check every claim the touched docstrings make (one cited a test
  that never existed). Its fence also covers prose that states the removed mechanism in other
  words (an env example said "signs the Viewer cookie"), and tests that re-derive a value a
  new owner function now builds.
- Worktree writers: an `isolation: worktree` agent's worktree starts from the remote-tracking base, not local `main`, and a writer may be refused the fast-forward. While local `main` is ahead of origin, create the worktree yourself from local `main` and name its path in the brief; use `isolation: worktree` only when `main` equals origin. (The #62 writer, 2026-09-30, built and gated on a base 225 commits old.)
- A controller session pinned to a worktree (`EnterWorktree`) pins every agent it dispatches, and the
  owner's `!` commands, to that worktree: a writer cannot write its own worktree, and `EnterWorktree`
  inside the writer does not lift it. Dispatch writers with `isolation: worktree`, or leave the pin
  first (2026-10-16).
- Writers never push (writer law). The controller merges into local `main` and pushes from the main
  checkout; never brief a writer to push from its worktree (one did, 2026-10-16 hotfix).
- Writers share one scratchpad: require task-prefixed log names (`wf-e2e.log`, not `e2e.log`); a
  stale generic log carrying `exit 0` from another agent nearly passed as a result.
- Worktree writers: cwd is NOT reliable between a writer's bash calls — instruct them to prefix every command with `cd <worktree> && `, not to cd once. A relative grep that silently hits the main checkout instead reads the WRONG code (this happened; the misread looked like a syntax error).
- A UI unit's fence names its CSS (tokens, components, page sheet): no visible state ships without it
  (MEDIATILES widened its fence by judgment to reach them).
- A rename unit names every place that keys on the old name as data, not code: gallery state names pair
  baseline and new screenshots, so a sed over them reads as a pixel diff (Wave ENGLISH U1).
- A rename brief asks for a grep of NEGATIVE assertions (`"old" not in body`) for every renamed string: they
  pass vacuously once the old string is gone everywhere (Wave ENGLISH: 4 found only by the final sweep).
- A rename of anything a browser SENDS (POST field, query param, cookie) has a deploy window: pages rendered
  before it post the old names after it. The brief asks what each consumer does with an ABSENT field — an
  absent visibility field read as "inherit" widened access (Wave ENGLISH U4, caught in review).
- A unit that adds a ROUTE names every registry that lists routes: `urls.py`, the leak matrix,
  `test_index_lag`, `test_screen_inventory` (M1 found the last two by a red check).
- A unit that adds corpus fixtures (a PDF, a new record) moves every list state in `test:gallery-diff`,
  not only its own screens: say so in the brief instead of "only the X states may change".
- The **law-beats-brief clause**: where the brief conflicts with a preloaded skill or `tests/CLAUDE.md`, law wins and the writer reports the conflict.
- Ask for **DX feedback (top 3) upfront** in the final report — it is the brief-quality feedback loop.
- Security-sensitive waves: dispatch `writer` (it preloads `adversarial-input`), or name `adversarial-input` in a `writer-ui` brief; name the pairs and fail-closed functions the unit touches.

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
  writer to one screen part. Since xdist (2026-10-06) every suite runs in under a minute: brief them
  in the FOREGROUND — a writer that backgrounds a suite and waits for it stalls (M2 did). Do NOT brief "one edit per call": turns are the main cost (`writer-discipline`,
  "Pace"), and small edits do not prevent stalls; silent long calls cause them.
- **Onboarding is a cost.** A brief names the exact sections to read (file + heading), not whole
  files; the preloaded skills are the always-read core.
- **Model per unit.** Sonnet for mechanical units (copy, CSS moves, test helpers, docs, render
  checks); Opus for seams, security and leak paths, data-loss paths, and finishers that must judge
  a red. Say which in the dispatch.
- **Parallel when fences are disjoint.** Units whose fences share no file run at once, each in its
  own worktree created from local `main`; merge them in order. Sequence only units that share a
  file or where one consumes the other's seam. (Wave REST 2026-09-30 ran U2 and U3 in sequence
  though their fences were disjoint.)
- A live-backend run gets a diagnostic budget and prints what it observed on failure. "Run once" plus a silent failing assert turned one finding into a guess.
- A brief for a data migration states its safety check at the raw level it rewrites: raw keys, body
  bytes and comments, not only "decodes to the same record". A decoder drops what it does not model,
  so a record-level check let a rewrite delete unknown keys (README relayout, 2026-10-16). A brief that
  adds a validation rule names which paths it runs on. A rule on new writes must not run on the
  decode of stored data, or old files stop loading.
- A brief that relies on a lock names the processes that write the same data, and states whether the
  lock reaches all of them: `WRITER_LOCK` is a `threading.Lock`, so a management command holding it
  does not block gunicorn. The README marker-move brief (2026-10-16) put that guard to the owner
  as a safeguard. The safe rule turned out to be "run with the app stopped".
- Before treating a grilled or ADR-backed decision as settled, verify the load-bearing code-behaviour claim against source (today: "Bestand required" was traced to 24 sites before ruling).

## On failure

Any rule breach or unexpected red stops the wave line. Investigate the cause chain first — brief error, law gap, missing seam, wrong decomposition — and fix at that level. Only then consider a mechanical gate, and only for a failure class that is mechanically checkable; a gate added without a named systemic cause is itself a debt entry. Blindly adding tests or gates treats symptoms.

## Close the wave

After each merged unit (or 2–3 tiny ones together): run the `simplify` skill on that diff, then the
`code-review` skill; fix confirmed findings before the next unit (owner rule 2026-10-01). Pass both an
explicit range (`git diff main...<branch>`): given a bare branch name, one review read code already
on main and missed the branch's own (2026-10-01). Run `code-review` at `medium` or above: `low` is one
diff read with test files skipped and no verification, and its `(none)` says little (2026-10-06). The full `mise run gate` runs ONCE, in the
pre-push hook (owner, 2026-10-02, again 2026-10-07): writers and the controller run `check` plus the suites
the diff could break, never a full gate per unit or per merge. `check` has no mypy, so a mypy red surfaces
at the push — fix forward.

Integrating parked branches: when the wave added an **exhaustiveness gate over a directory** (module map, leak matrix), list every in-flight branch's new files in that directory before merging. A rebase or `merge-tree` dry run sees overlapping TEXT only, so a gate that asserts over a whole package is invisible until it runs — four unrowed `app/web` modules stopped one integration exactly here.

A dry run (`merge-tree`, rebase preview) describes the tree it was run against. Re-run it
immediately before the merge it sizes; commits landed in between — a docs addendum appended
to a file the branch also appends to — turn a clean file into a conflict per commit. Order
integration so doc-appending commits land after the branch merges when possible.

A path or name rename merged while other writers run: at their rebase, grep each branch's NEW test
lines for the old spelling. A negative check (`"/bearbeiten" not in url`) passes vacuously after a
rename and a positive wait hangs; aliases keep old GETs green, so the suite will not tell you (URLS +
CASFIX, 2026-10-01).

`rerere` is on in this repo. A replayed resolution stages the result with no unmerged paths,
so `git rebase --continue` refuses with "there are staged changes"; a loop polling
`--diff-filter=U` reads that as "not finished" and stalls. Handle the resolved-but-uncommitted
state, and verify what rerere auto-applied against the original commit — it replays a
judgment onto different surrounding text.

Wave hygiene: re-measure the indicator on any ledger entry the wave touched. Prose added to law/map files gets the same scrutiny as code — an addition without a deletion is suspect.
