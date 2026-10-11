---
name: writer-discipline
description: The standing discipline for a writer agent on this repo — pace, gates, TDD, stop rules, decision ownership, functional core, the deny contract, language, comments, map rows, history, simplify, the final report, and building only for what happens. Preloaded by the writer agents.
when_to_use: Any task that changes code, tests or docs in this repository.
---

# Writer discipline

How the code gets built. A writer onboards from this skill, `CLAUDE.md`, `CONTEXT.md` and the
task brief on disk — the mailbox is not the source of truth.

**What to read.** This skill is preloaded in full. Topic skills (`ui-build`,
`adversarial-input`) are preloaded by the matching agent or named by the task brief; load the ones
it names. The task brief also names the sections of other docs to read: read those, not the whole
files.

**Pace.** Model turns are the main cost, not tools. Batch related edits into one logical step, and
commit once per logical step with `mise run check` green. Run suites in the FOREGROUND: since xdist
each is under a minute, and a writer that backgrounds a suite and waits on it stalls.

## Build for what happens

Before writing code, stop at the first step that holds:
1. Does it need to exist? A need nobody has today is not built.
2. Is it already in the codebase? Reuse it; refactor first if it does not fit.
3. Does Python, Django, the platform (HTML, CSS, Postgres) or an installed dependency do it? Use
   that. No new dependency for what a few lines do.
4. Only then: the smallest code that works.

Guard only against inputs and states that can occur, and name the case: who sends it, on which
path. A case that cannot occur gets no branch, no test and no comment. Always built anyway:
validation at trust boundaries, the deny contract on leak paths, and anything that prevents data
loss.

A fix goes where all callers pass through, not into the one caller the report names. A shortcut
with a known limit is reported to the controller, never left as a marker in the code.

## One writer at a time

Exactly ONE writer holds the tree per task; reviews are fresh one-shot subagents. Never make a tree
write while another writer's wave is open. If you receive a tree-touching instruction mid-wave, ACK
it and hold — do not silently continue on a changed spec.

## Gates green

Every commit must pass `mise run check` — ruff, format, pyrefly, the no-DB tests. Before you report,
also run the suites your change could break: `test:index` / `test:db` for index, search, schema or a
new Postgres-backed test; `test:gallery` and `test:e2e` for UI. The full `mise run gate` runs once,
in the pre-push hook — not per commit and not per task (owner, 2026-10-02 and 2026-10-07). `check`
has no mypy, so a typing error surfaces at the push and is fixed forward. The task definitions in
`mise.toml` are the single source of what each runs.

In an isolated worktree, compound shell commands that contain git (a heredoc commit message,
`cmd; git …`) are refused. Write the message to a file and commit with `git commit -F <file>`.
ruff's RUF001/RUF002 reject confusable characters (en dash, bullet) that German legacy text needs:
write them as `"\N{EN DASH}"` / `"\N{BULLET}"` in code.

pyrefly is always invoked as `uv run pyrefly check src tests scripts`; a bare `pyrefly check`
resolves zero files in a worktree and passes vacuously.

The commit-stage hook runs uv-lock, ruff and pyrefly; the push-stage hook runs the full gate. Do not
`--no-verify` except on a docs-only commit where the hooks are irrelevant, and only when the full
gates ran clean on the immediately prior code commit. The exemption never covers a fixup. Noisy hook
output is trimmed with `| tail`, never silenced by skipping the hook — and a pipe returns `tail`'s
status, which hides a refused hook: run it under `set -o pipefail`, or confirm the commit landed
(`git log -1`) before going on. The baseline is whatever the ledger records — never let it drop.

## TDD

Write the failing test first, watch it fail for the right reason, then make it pass (the `tdd`
skill). Prove a security/gate test is non-vacuous by MUTATION: neuter the guard, watch the test go
red, restore. A gate that never bit is not a gate.

Ceremony follows the testing razor. Mutation proofs: for leak, deny, data-loss and security paths,
and for gates. A render diff: only for a refactor you claim is neutral. A screenshot harness: only
when the brief asks for renders before the finisher. Copy, CSS and layout changes need `check` and,
once per wave, the finisher's gallery and e2e — not per-commit proofs.
`mise run mutate -- FILE OLD NEW NODE_IDS` does all three and always restores FILE. For an e2e node
add `-m e2e` (addopts deselects it otherwise), and pass node ids as separate literal arguments (zsh
does not word-split a `$VAR`).

Restore a hand mutation by re-editing the exact lines (or commit before mutating) — never
`git checkout <file>`: it wipes every uncommitted change in that file. Run mutation checks with
`PYTHONDONTWRITEBYTECODE=1`: Python trusts a cached `.pyc` while the source's size and whole-second
mtime match, so a same-size edit and its restore within one second can run stale bytecode.

The e2e and gallery suites run only for UI changes (CSS/template/JS, position/overlay changes; the
"When to run what" table in `CLAUDE.md`). Never run them as general diligence in a non-UI wave — an e2e failure
outside your wave's scope is the coordinator's problem, not yours.

Proving rendered-HTML equivalence across a refactor: dump the representative states before and
after (GET, error, conflict, each overlay), normalize CSRF tokens, whitespace and static-file hashes
(`/static/…<12 hex>.css` changes with any CSS edit), diff — expect 0 lines and report the count.
Write the throwaway harness as `tests/…/_zz_snapshot.py`: the `_zz_` name keeps it out of
`python_files` so `mise run check` never collects it, while `uv run pytest <path>` still runs it
explicitly. `ruff format --check` still sees it, so run `ruff format` on it. Pixel-neutral in the
gallery: no harness, run `mise run test:gallery-diff -- <ref>`. Verify the dump is deterministic
(two identical pre-runs), then delete the harness.

## An unexpected red is a STOP, not a patch site

A gate, a test or a rule that breaks unexpectedly stops the line. Investigate how it came to be and
what would have prevented it; fix the cause; the report states both cause and prevention. Adding a
test or gate is the last resort after the systemic cause is addressed, never the reflex.

## One owner per decision

Most review findings, and the bugs behind them, are a second caller restating a decision the first
caller already made (the publish precondition in three places, "which fields may a Member see" in
seven).

- **The second caller moves the decision.** A decision answers a question about the domain or the
  request: may this be published, may this viewer see this field, what is this field called, what
  kind of request is this, what runs after a write. When you need one a second time, first move it
  into the module that owns its subject, then call it from both places. Markup and one-line
  predicates (`deleted is not None`) are exempt.
- **Fix every copy.** Before a fix commit, grep for siblings of the code you fix: the same name, the
  same literal, the same shape. Fix them all, or list the rest under "Found, not fixed".
- **A state the user must see is shown at every caller.** When a service result carries one (index
  lagged, conflict, refused), every route that calls the service shows it. Grep the callers when you
  add such a field or call such a service.
- **Delete before you guard.** Before a leak or defect fix on a field, function or route, count its
  readers in `src/` (tests do not count). Zero readers: delete it instead of guarding it.
- **The canonical tree is untrusted input.** A README may be hand-edited, undecodable or not UTF-8
  (ADR 0020 expects hand edits on the system of record). Code that reads canonical files uses its
  layer's existing policy for a bad file and never invents a new one; where the layer has none, stop
  and ask.
- **Words move with the code.** A change to who can reach a surface, or to what a term means,
  updates `CONTEXT.md` and the module docstring in the same commit.

## Tests assert derived values, never re-derived ones

A test asserting an encoding, a URL or a key layout gets the value from the production helper, or
parses the parts back out — it never re-derives the value with its own copy of the rule. A drift
test pinning two copies equal needs a stated reason why an owning interface is not the fix, and a
`docs/tech-debt.md` entry for the copy. The one standing exception is a fact that must exist in two
encodings (Python and SQL scope, ADR 0012).

## Functional core, imperative shell

Pure functions wherever possible; I/O only in a shell. The line is I/O: reading the store or the
DB, writing rows, enqueueing, the clock, logging. Parsing bytes (PDF text) is pure.

- **The core** takes plain values (bytes, an `Article`, a set of hashes), never a handle, and
  returns plain values: rows to store, jobs to enqueue, a closed union of outcomes. Each shell calls
  its effects directly: no effect library, no generic interpreter.
- **A log line someone acts on** (an alarm, an operator warning) is an outcome the core returns;
  the shell logs it, the test asserts the value. Diagnostic logging is allowed anywhere.
- **Resources come in as arguments.** A shell takes the `Archive`; only an edge (a task, a
  management command, a view) builds it, in one line (`Archive.canonical()`), and an edge gets no
  test of its own. Postgres (the ORM) and the queue (Procrastinate's `app`) stay framework globals.
  `Archive` holds the canonical archive only; a new resource is its own argument.
- **A function does the one act its name says**: an "extract" does not also store.

Example, `app/media_text.py`: `unread(media, done)` names the files still to read;
`parse(data, content_hash)` returns `Pages | Unreadable | HashMismatch`; `fill(archive, ulid)`
loads, reads, calls both, writes the rows and logs the mismatch. Likewise `articles.derived_jobs`
returns the jobs and `_enqueue_derived` enqueues them.

**Tests never patch our own code.** A core is tested on its returned value, a shell over
`Archive.of(InMemoryObjectStore())` and the real ORM, the queue through Procrastinate's in-memory
connector (`tests/_queue.py`). `monkeypatch` stays only at true externals a test cannot run: the
clock, a remote service, a simulated crash. Existing patches of our code (the web suite's autouse
index and enqueue stubs among them) go when their module is touched. Distrust a test that mostly
asserts against its own mocks.

## The deny contract

Every deny / absence / malformed-param / disallowed-method on a prod route is a plain 404 that
reveals and changes nothing (`docs/requirements/owner-interview-2026-08.md`); the shared
`not_found()` — one constant German page, rendered once — is the implementation. In tests, a deny is
`tests/app/web/_asserts.assert_denied` (status 404 + the one constant `404.html` page) plus a
nothing-was-written assert on write routes. Any new route must earn a leak-matrix entry
(`tests/app/web/test_leak_matrix.py` — the exhaustiveness assertion fails otherwise), and
unauthorized content must stay filtered out of search results, listings, and facet counts.

## Language

Product UI copy is **German** (per the `CONTEXT.md` glossary — English code identifiers, German UI
labels). The register is informal **du** (never Sie); neutral infinitive imperatives are fine.
Everything development-facing — code, routes, dev pages, commit messages, docs, comments, log
messages and their field names — is **English**. URLs are technical and English too: paths, query
parameter names and fixed values such as sort labels. Vocabulary values (a Medienart, a Bestand
name) are content and stay as stored. "Findbuch" is banned from UI copy (archaic).

## Comment discipline

A comment earns its place only by saying what the code at that spot cannot: an exception, a
non-obvious constraint, or a value someone would otherwise "fix". Narration, restated law and
history are defects — git holds the history; `docs/design/design-review-law.md`, `docs/adr/` and
`docs/requirements/` hold the decisions.

In code a decision gets a **pointer**, never a paraphrase (`law C8`, `register row 9`, `ADR 0015`)
— and it appears once, at the one place a reader needs it. If you are explaining *why* a decision is
right, you are writing in the wrong file: put it in the law and cite it here.

Before keeping a comment, delete it and re-read the code. If only your confidence is gone, it was
noise; if a future writer could now break something, keep it — at one line. Deleting code does not
license a comment about the deletion.

- **Test docstrings name the contract under test**, never the assertions. If the test name already
  says it, write nothing.
- **Never advertise a gate that does not exist.** When a planned test is dropped, grep for comments
  promising it — a false promise is worse than silence, and it survives as apparent coverage.
- **A comment may not deform the code it describes.** If a trailing comment forces a one-line call
  across three, move it above or drop it.
- **No deferral comments** ("… if that ever grows", "per-key locks if …"): a shortcut is fixed or
  reported, never left as a note.

## Map rows move with the code

Creating, renaming or deleting a module, or changing its interface, updates that module's row in
`src/bundesarchiv/<pkg>/CLAUDE.md` — and `MODULES.md` when a name appeared or vanished — in the SAME
commit. A row stays within the 220-character budget. An implementation-only change touches no map.
Procedure: the `update-module-map` skill; gate: `tests/test_module_map.py`.

## Standing law changes update the agent definitions and skills in the same wave

When a ruling changes standing law (a testing rule, a contract like the deny shape, a workflow),
update the agent definitions and skills (`.claude/agents/`, `.claude/skills/`, `CLAUDE.md`,
`tests/CLAUDE.md`) in the same wave as the code. A definition that contradicts the code regenerates
the old behavior in the next wave.

## Clean history within your own wave

Wave-internal fixes land as `git commit --fixup <sha>` and fold at wave end, non-interactively,
scoped STRICTLY to your own unaccepted commits:

```
GIT_SEQUENCE_EDITOR=: git rebase --autosquash <wave-base>
```

Never rebase a commit you did not create in this wave, and never rebase an already-accepted/reviewed
commit. No flip-flops in the log. NO push, NO `reset --hard`, NO `clean`, NO `branch -D` (a git hook
blocks them; rebase is permitted).

## Simplify your own code before the final commit

Run the simplify discipline (`/simplify` or its four angles — reuse, simplification, efficiency,
altitude) over your OWN new code before the wave's final commit. Zero behavior change; skip silently
if it finds nothing.

## Report before you idle

Deliver a final report (per-item status, deviations, gate results, test delta, server PID) as your
final message — the hand-back to whoever dispatched you — BEFORE going idle; a writer that idles
without reporting has failed the handoff. State outcomes honestly: if a test failed, say so with the
output; if a step was skipped, say that.

Include **Found, not fixed**: every improvement you saw outside your fence (a variant in disguise,
a restated value, a dead rule, a missing component), with file and symbol. Inside your fence you fix
it; outside you only report it — the coordinator files it into `docs/tech-debt.md` or the next
brief.
