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

## Gates green on every commit

Every commit must pass, run in this order:

```
uv run ruff check
uv run mypy            # --strict per pyproject
uv run pytest          # the fast suite; e2e + gallery are excluded by marker
```

The pre-commit hook runs these too. Do not `--no-verify` except on a docs-only
commit where the hooks are irrelevant, and only when the full gates ran clean on
the immediately prior code commit. The baseline is whatever the ledger records
(e.g. 1068 unit + 13 e2e at the Part 4 exit) — never let it drop.

## TDD

Write the failing test first, watch it fail for the right reason, then make it
pass (`superpowers:test-driven-development` / the `tdd` skill). Prove a
security/gate test is non-vacuous by MUTATION: neuter the guard, watch the test
go red, restore. A gate that never bit is not a gate.

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
(`uv run pytest -m gallery -s`) is the shared review medium. See
`design-gate-brief.md`.

## Report before you idle

Deliver a final report (per-item status, deviations, gate results, test delta,
server PID) via SendMessage to the team lead BEFORE going idle — a reviewer or
writer that idles without reporting has failed the handoff. State outcomes
honestly: if a test failed, say so with the output; if a step was skipped, say
that.
