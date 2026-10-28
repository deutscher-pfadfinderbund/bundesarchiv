---
name: writer-discipline
description: The standing discipline for a writer agent on this repo — what to read, building only for what happens, decision ownership, functional core, TDD, the deny contract, language, comments, gates and hooks, history, simplify, and the final report. Preloaded by the writer agents.
when_to_use: Any task that changes code, tests or docs in this repository.
---

# Writer discipline

How the code gets built, one rule per line, grouped by the moment it applies.

## Before you start

- Onboard from this skill, `CLAUDE.md`, `CONTEXT.md` and the task brief on disk; the mailbox is not the source of truth.
- This skill is preloaded in full; topic skills (`ui-build`, `adversarial-input`) come preloaded by your agent or named by the brief — load the ones it names.
- Read the sections of other docs the brief names, not the whole files.
- Exactly one writer holds the tree per task; reviews are fresh one-shot subagents. Never write to the tree while another writer's wave is open.
- A tree-touching instruction mid-wave: ACK it and hold — do not silently continue on a changed spec.
- In an isolated worktree the cwd already is the worktree: run commands plainly, never `cd` into it first (the worktree guard refuses `cd … && git …` as too complex to verify). Without isolation, use absolute paths and `git -C <worktree>`.
- The scratchpad is shared: prefix your log names with the task (`wf-e2e.log`); a generic log may hold another agent's result.

### Build for what happens

Before writing code, stop at the first step that holds:
1. Does it need to exist? A need nobody has today is not built.
2. Is it already in the codebase? Reuse it; refactor first if it does not fit.
3. Does Python, Django, the platform (HTML, CSS, Postgres) or an installed dependency do it? Use that. No new dependency for what a few lines do.
4. Only then: the smallest code that works.

- Guard only against inputs and states that can occur, and name the case: who sends it, on which path. A case that cannot occur gets no branch, no test and no comment.
- Always built anyway: validation at trust boundaries, the deny contract on leak paths, and anything that prevents data loss.
- A fix goes where all callers pass through, not into the one caller the report names.
- A shortcut with a known limit is reported to the controller, never left in the code as a marker or a deferral comment ("… if that ever grows").

## While you write

**Pace.** Model turns are the main cost, not tools: every turn re-reads your whole context. Batch related edits into one logical step; issue independent reads and searches in one turn (parallel calls); read the ranges you need, all at once, not one range per turn; never re-read what is already in your context.

### One owner per decision

Most review findings are a second caller restating a decision the first already made (the publish precondition in three places, "which fields may a Member see" in seven).
- **The second caller moves the decision**: a decision about the domain or the request (may this be published, may this viewer see this field, what is it called, what kind of request is this, what runs after a write) needed a second time first moves into the module that owns its subject, then both call it. Markup and one-line predicates (`deleted is not None`) are exempt.
- **Fix every copy**: before a fix commit, grep for siblings (same name, same literal, same shape); fix them all or list the rest under "Found, not fixed".
- **A state the user must see is shown at every caller**: when a service result carries one (index lagged, conflict, refused), every route calling the service shows it — grep the callers.
- **Delete before you guard**: before a leak or defect fix on a field, function or route, count its readers in `src/` (tests do not count); zero readers means delete it.
- **The canonical tree is untrusted input**: a README may be hand-edited, undecodable or not UTF-8 (ADR 0020); use the layer's existing policy for a bad file, never a new one — where it has none, stop and ask.
- **Words move with the code**: a change to who can reach a surface, or to what a term means, updates `CONTEXT.md` and the module docstring in the same commit.

### Functional core, imperative shell

- Pure functions wherever possible; I/O only in a shell. The line is I/O: the store or the DB, writing rows, enqueueing, the clock, logging. Parsing bytes (PDF text) is pure.
- The core takes plain values (bytes, an `Article`, a set of hashes), never a handle, and returns plain values: rows to store, jobs to enqueue, a closed union of outcomes.
- Each shell calls its effects directly: no effect library, no generic interpreter.
- A log line someone acts on (an alarm, an operator warning) is an outcome the core returns; the shell logs it, the test asserts the value. Diagnostic logging is allowed anywhere.
- Resources come in as arguments: a shell takes the `Archive`; only an edge (a task, a management command, a view) builds it, in one line (`Archive.canonical()`).
- Postgres (the ORM) and the queue (Procrastinate's `app`) stay framework globals. `Archive` holds the canonical archive only; a new resource is its own argument.
- A function does the one act its name says: an "extract" does not also store.
- **Test depth follows the layer**: the core gets the many cases; a shell (an app service such as `save_article`, which orders effects under a contract) a few, through the real store and queue on `Archive.of(InMemoryObjectStore(), InMemoryIndex)` (`index/refresh.py`); on Postgres (`Archive.of(store)`) only where the test checks search rows, the index lock or timeout, or SQL; an edge none.
- **Tests never patch our own code**: a core is tested on its returned value, a shell over `Archive.of(InMemoryObjectStore(), InMemoryIndex)`, the queue through Procrastinate's in-memory connector (`tests/_queue.py`).
- `monkeypatch` stays only at true externals a test cannot run (the clock, a remote service, a simulated crash); existing patches of our code go when their module is touched. Distrust a test that mostly asserts against its own mocks.

Example, `app/media_text.py`: the core `readable(media)` (the files text is read from, one per hash) and `parse(data, content_hash)` (`Pages | Unreadable | HashMismatch`); the single-item shells `read` (one file) and `record` (one outcome: rows, or the alarm); `fill` composes them with a comprehension. Likewise `articles.derived_jobs` returns the jobs and `_enqueue_derived` enqueues them.

### TDD

- Write the failing test first, watch it fail for the right reason, then make it pass (the `tdd` skill).
- Prove a security or gate test non-vacuous by mutation: neuter the guard, watch it go red, restore. A gate that never bit is not a gate.
- Ceremony follows the testing razor: mutation proofs for leak, deny, data-loss and security paths and for gates; a render diff only for a refactor you claim is neutral; a screenshot harness only when the brief asks for renders.
- `mise run mutate -- FILE OLD NEW NODE_IDS` mutates, runs and always restores FILE; for an e2e node add `-m e2e`, and pass node ids as separate literal arguments (zsh does not word-split a `$VAR`). One mutant per call, OLD and NEW as plain literals: the sandbox refuses a call that mixes shell variables with code text.
- Restore a hand mutation by re-editing the exact lines (or commit first), never `git checkout <file>` — it wipes every uncommitted change in that file.
- Run mutation checks with `PYTHONDONTWRITEBYTECODE=1`: a same-size edit and its restore within one second can otherwise run stale `.pyc`.
- Render diff for a neutral refactor: dump representative states (GET, error, conflict, each overlay) before and after, normalize CSRF tokens, whitespace and static-file hashes (`/static/…<12 hex>.css`), diff, expect and report 0 lines.
- Its harness is a throwaway `tests/…/_zz_snapshot.py` (outside `python_files`, so `check` skips it; `uv run pytest <path>` runs it; `ruff format` it); check the dump is deterministic (two identical pre-runs), then delete it.
- Pixel-neutral in the gallery needs no harness: `mise run test:gallery-diff -- <ref>`.
- Tests assert derived values, never re-derived ones: an encoding, URL or key layout comes from the production helper, or is parsed back out.
- A drift test pinning two copies equal needs a stated reason why an owning interface is not the fix, and a `docs/tech-debt.md` entry; the one standing exception is a fact in two encodings (Python and SQL scope, ADR 0012).

### The deny contract

- Every deny, absence, malformed param or disallowed method on a prod route is a plain 404 that reveals and changes nothing (`docs/requirements/owner-interview-2026-08.md`), via the shared `not_found()` — one constant German page, rendered once.
- Unauthorized content stays out of search results, listings and facet counts.
- How a deny is tested and how a new route joins the leak matrix: `tests/CLAUDE.md`, "The deny contract".

### Language

- Product UI copy is German (the `CONTEXT.md` glossary), informal du, never Sie; neutral infinitive imperatives are fine. "Findbuch" is banned from UI copy (archaic).
- Everything development-facing is English: code, routes, dev pages, commit messages, docs, comments, log messages and their field names, and URLs (paths, query parameter names, fixed values such as sort labels).
- Vocabulary values (a Medienart, a Bestand name) are content and stay as stored.

### Comment discipline

- A comment says only what the code at that spot cannot: an exception, a non-obvious constraint, a value someone would otherwise "fix".
- Narration, restated law and history are defects — git holds the history, the law, ADRs and requirements hold the decisions; deleting code does not license a comment about the deletion.
- A decision gets a pointer, never a paraphrase (`law C8`, `register row 9`, `ADR 0015`), once, where a reader needs it; a "why it is right" belongs in the law, cited here.
- Before keeping a comment, delete it and re-read the code: if only your confidence is gone it was noise; if a future writer could now break something, keep it at one line. Run that test per clause, not per comment, and again after every cut: one cut does not finish a comment.
- Test docstrings name the contract under test, never the assertions; if the test name says it, write nothing.
- Never advertise a gate that does not exist: when a planned test is dropped, grep for comments promising it.
- A comment may not deform the code: if a trailing comment splits a one-line call across three, move it above or drop it.

## Each commit

- One commit per logical step; the commit hook runs what `mise run check` runs, so each commit is green.
- One git command per call: in an isolated worktree a compound containing git is refused, and the destructive-git hook greps whole commands, heredoc text included. Write files and commit messages with the Write tool, then `git commit -F <file>`.
- ruff's RUF001/RUF002 reject confusables (en dash, bullet) that German legacy text needs: write `"\N{EN DASH}"` / `"\N{BULLET}"` in code.
- No `--no-verify` except on a docs-only commit right after a code commit whose gates ran clean — never on a fixup.
- Trim noisy hook output with `| tail` under `set -o pipefail` (a pipe returns `tail`'s status), or confirm with `git log -1` that the commit landed; the baseline is what the ledger records — never let it drop.
- A ruling that changes standing law (a testing rule, the deny shape, a workflow) updates `.claude/agents/`, `.claude/skills/`, `CLAUDE.md` and `tests/CLAUDE.md` in the same wave, because a contradicting definition regenerates the old behavior.
- Wave-internal fixes land as `git commit --fixup <sha>` and fold at wave end with `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <wave-base>` (without `-i`, git before 2.44 folds nothing yet reports success), strictly over your own unaccepted commits. A signature change whose callers sit in several of your commits lands as a core fixup plus one plain signature commit: no single fixup is green alone, and the structure gates refuse a compatibility shim.
- Never rebase a commit you did not create in this wave or one already accepted; no flip-flops in the log; no push, `reset --hard`, `clean` or `branch -D` (a hook blocks them).

## Before you report

- Run `mise run test:affected` in the foreground, once per wave (not per commit): it picks the suites your diff needs from its paths, browser suites included (each is under a minute; a backgrounded suite stalls the writer). An e2e failure outside your scope is the coordinator's.
- The full `mise run gate` runs once, in the pre-push hook, never per commit or task. `mise.toml` is the single source of what each task runs.
- An unexpected red (gate, test or rule) stops the line: find how it came to be and what would have prevented it, fix the cause, report both. A new test or gate is the last resort, never the reflex.
- Before the final commit, simplify your own new code (`/simplify`: reuse, simplification, efficiency, altitude); zero behavior change, skip silently if it finds nothing.
- Deliver the final report as your last message before idling — per-item status, deviations, gate results, test delta, server PID; a writer that idles without it has failed the handoff.
- State outcomes honestly: a failed test with its output, a skipped step as skipped.
- Include **Found, not fixed**: every improvement seen outside your fence (a variant in disguise, a restated value, a dead rule, a missing component) with file and symbol; inside the fence you fix it, outside you report it for `docs/tech-debt.md` or the next brief.
