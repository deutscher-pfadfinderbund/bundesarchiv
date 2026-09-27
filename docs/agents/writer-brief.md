# Writer brief

The standing discipline for a writer agent working a task on this repo. A fresh
writer onboards from here (plus `CLAUDE.md`, `CONTEXT.md`, and the task's own
brief) — the mailbox is not the source of truth. Its sibling is
`design-gate-brief.md` (what a UI review runs); this is how the code gets built.

## One writer at a time

Exactly ONE writer holds the tree per task (owner call, 2026-07-11: a fresh
writer per task, reviews are fresh one-shot subagents). Never make a tree write
while another writer's wave is open. If you receive a tree-touching instruction
mid-wave, ACK it and hold — do not silently continue on a changed spec.

## Gates green

Every commit must pass `mise run check` — ruff, format, pyrefly, the no-DB
tests. The full `mise run gate` (mypy and every suite; it starts and waits for
the dev Postgres itself) is required when the change touches index, search or
schema — `src/bundesarchiv/index/`, migrations, search-relevant persistence —
and before you declare a task done. The task definitions in `mise.toml` are the
single source of what each runs.

`mise run gate` can outlast the 600s silent-stream watchdog. Run it in the background into a
log (`mise run gate > gate.log 2>&1; echo "exit $?" >> gate.log`) and wait on the log with a
background `until grep -q '^exit ' gate.log; do sleep 20; done` loop; foreground `sleep` is
blocked.

In an isolated worktree, compound shell commands that contain git (a heredoc commit message,
`cmd; git …`) are refused. Write the message to a file and commit with `git commit -F <file>`.
ruff's RUF001/RUF002 reject confusable characters (en dash, bullet) that German legacy text
needs: write them as `"\N{EN DASH}"` / `"\N{BULLET}"` in code.

pyrefly is always invoked as `uv run pyrefly check src tests`; a bare
`pyrefly check` resolves zero files in a worktree and passes vacuously.

The commit-stage hook runs uv-lock, ruff and pyrefly; the push-stage hook runs
the full gate. Do not `--no-verify` except on a docs-only commit where the hooks
are irrelevant, and only when the full gates ran clean on the immediately prior
code commit. The exemption never covers a fixup. Noisy hook output is trimmed
with `| tail`, never silenced by skipping the hook — and a pipe returns `tail`'s
status, which hides a refused hook: run it under `set -o pipefail`, or confirm
the commit landed (`git log -1`) before going on. The baseline is whatever the
ledger records — never let it drop.

## TDD

Write the failing test first, watch it fail for the right reason, then make it
pass (`superpowers:test-driven-development` / the `tdd` skill). Prove a
security/gate test is non-vacuous by MUTATION: neuter the guard, watch the test
go red, restore. A gate that never bit is not a gate.

Restore a mutation by re-editing the exact lines (or commit before mutating) —
never `git checkout <file>`: it wipes every uncommitted change in that file. Run
mutation checks with `PYTHONDONTWRITEBYTECODE=1`: Python trusts a cached `.pyc`
while the source's size and whole-second mtime match, so a same-size edit and its
restore within one second can run stale bytecode.

The e2e and gallery suites run only when the design-gate rules demand it (UI
waves: CSS/template/JS, position/overlay changes). Never run them as general
diligence in a non-UI wave — an e2e failure outside your wave's scope is the
coordinator's problem, not yours.

Proving rendered-HTML equivalence across a refactor: dump the representative
states before and after (GET, error, conflict, each overlay), normalize CSRF
tokens and whitespace, diff — expect 0 lines and report the count. Write the
throwaway harness as `tests/…/_zz_snapshot.py`: the `_zz_` name keeps it out of
`python_files` so `mise run check` never collects it, while
`uv run pytest <path>` still runs it explicitly. `ruff format --check` still
sees it, so run `ruff format` on it. A harness that needs no pytest fixture
(a Pillow gallery diff) lives outside the tree instead. Verify the dump is
deterministic (two identical pre-runs), then delete the harness.

## An unexpected red is a STOP, not a patch site

A gate, a test or a rule that breaks unexpectedly stops the line. Investigate how
it came to be and what would have prevented it; fix the cause; the report states
both cause and prevention. Adding a test or gate is the last resort after the
systemic cause is addressed, never the reflex.

## Serialization is adversarial by default

Every encode/decode or serialize/parse pair ships with an adversarial round-trip
test in the commit that introduces it: the delimiter itself, empty, unicode,
percent, leading/trailing whitespace. Joining externally-controlled values with
an in-band delimiter and no escaping is a defect, not a style call.

## Tests assert derived values, never re-derived ones

A test asserting an encoding, a URL or a key layout gets the value from the
production helper, or parses the parts back out — it never re-derives the value
with its own copy of the rule. A drift test pinning two copies equal needs a
stated reason why an owning interface is not the fix.

## No heavy mocking

Exercise the real code path, not mocks of the unit under test. The web subtree
stubs exactly two genuine external boundaries (the Postgres index write and the
worker enqueue, via the autouse conftest fixture) and nothing else — the
canonical write + CAS path stays real. Distrust a test that mostly asserts
against its own mocks.

## The deny contract

Every deny / absence / malformed-param / disallowed-method on a prod route is a
plain 404 that reveals and changes nothing. (The old byte-identical-404 law was
relaxed by the owner, 2026-08 — see `docs/requirements/owner-interview-2026-08.md`;
the shared empty `_not_found()` remains the implementation convention, but tests
no longer compare response bytes.) In tests, a deny is
`tests/app/web/_asserts.assert_denied` (status 404 + empty body) plus a
nothing-was-written assert on write routes. Any new route must earn a leak-matrix
entry (`tests/app/web/test_leak_matrix.py` — the exhaustiveness assertion fails
otherwise), and unauthorized content must stay filtered out of search results,
listings, and facet counts.

## UI work

UI is built under the Construction law in `docs/design/design-system.md`
(owner, 2026-08-05): semantic HTML first, compose existing components
(atoms → molecules → layouts → pages), no ad-hoc or redundant components,
every visible element traces to a wish/ruling/spec section, one pattern per
problem. A UI wave ends with before/after gallery renders for the owner's
verdict — never with prose claiming the UI is good.

## Language

Product UI copy is **German** (per the `CONTEXT.md` glossary — English code
identifiers, German UI labels). The register is informal **du** (never Sie);
neutral infinitive imperatives are fine. Everything development-facing — code,
routes, dev pages, commit messages, docs, comments — is **English**. "Findbuch"
is banned from UI copy (archaic).

## Comment discipline (owner, 2026-08-08)

A comment earns its place only by saying what the code at that spot cannot: an
exception, a non-obvious constraint, or a value someone would otherwise "fix".
Narration, restated law and history are defects — git holds the history;
`docs/design/design-review-law.md`, `docs/adr/` and `docs/requirements/` hold
the decisions.

In code a decision gets a **pointer**, never a paraphrase (`law C8`,
`register row 9`, `ADR 0015`) — and it appears once, at the one place a reader
needs it. If you are explaining *why* a decision is right, you are writing in
the wrong file: put it in the law and cite it here.

Before keeping a comment, delete it and re-read the code. If only your
confidence is gone, it was noise; if a future writer could now break something,
keep it — at one line. Deleting code does not license a comment about the
deletion.

Measured baseline when this rule landed (form wave): 33.8% of the stylesheets
and 31.2% of the templates were comment, and the wave's own additions were 69%
(CSS) and 98% (templates) comment lines. That is the habit this rule exists to
break.

Three specifics that follow from the same rule:

- **Test docstrings name the contract under test**, never the assertions. If the
  test name already says it, write nothing.
- **Never advertise a gate that does not exist.** When a planned test is dropped,
  grep for comments promising it — a false promise is worse than silence, and it
  survives as apparent coverage.
- **A comment may not deform the code it describes.** If a trailing comment forces
  a one-line call across three, move it above or drop it.

## Map rows move with the code

Creating, renaming or deleting a module, or changing its interface, updates that
module's row in `src/bundesarchiv/<pkg>/CLAUDE.md` — and `MODULES.md` when a name
appeared or vanished — in the SAME commit. An implementation-only change touches
no map. Procedure: the `update-module-map` skill; gate: `tests/test_module_map.py`.

## Standing law changes update the briefs in the same wave

When a ruling changes standing law (a testing rule, a contract like the deny
shape, a workflow), update the agent briefs (`CLAUDE.md`, `docs/agents/`,
`tests/CLAUDE.md`) in the same wave as the code. A brief that contradicts the
code regenerates the old behavior in the next wave.

## Clean history within your own wave

Wave-internal fixes land as `git commit --fixup <sha>` and fold at wave end,
non-interactively, scoped STRICTLY to your own unaccepted commits:

```
GIT_SEQUENCE_EDITOR=: git rebase --autosquash <wave-base>
```

Never rebase a commit you did not create in this wave, and never rebase an
already-accepted/reviewed commit. No flip-flops in the log. NO push, NO
`reset --hard`, NO `clean`, NO `branch -D` (the owner's git hook blocks them;
rebase is permitted).

## Simplify your own code before the final commit

Owner standing order (2026-07-11): run the simplify discipline (`/simplify` or
its four angles — reuse, simplification, efficiency, altitude) over your OWN new
code before the wave's final commit. Zero behavior change; skip silently if it
finds nothing.

## Screenshots via the gallery, review on live pages

For any UI change: restart the dev server after EVERY commit (`:8000` runs
`--noreload` and serves stale code otherwise), then judge on the live pages —
never ship PNGs to the owner (he browses live himself). Agents keep their own
internal screenshot self-verification loop; the state gallery
(`mise run test:gallery`) is the shared review medium. See
`design-gate-brief.md`.

## Report before you idle

Deliver a final report (per-item status, deviations, gate results, test delta,
server PID) as your final message — the hand-back to whoever dispatched you —
BEFORE going idle; a reviewer or writer that idles without reporting has failed
the handoff. State outcomes honestly: if a test failed, say so with the output;
if a step was skipped, say that.
