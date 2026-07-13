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

## The byte-identical-404 law

Every deny / absence / malformed-param / disallowed-method on a prod route
returns the SAME 404: `media_views._not_found()` (empty body, `content_type=""`,
constant header set). A forbidden thing is indistinguishable from a missing one
(existence-hiding, plan §4.3). Never grow a distinguishable 404 on a prod route —
the leak matrix (`tests/app/web/test_leak_matrix.py`) pins this for every route,
and any new route must earn a matrix entry (the exhaustiveness assertion fails
otherwise).

## Language

Product UI copy is **German** (per the `CONTEXT.md` glossary — English code
identifiers, German UI labels). The register is informal **du** (never Sie);
neutral infinitive imperatives are fine. Everything development-facing — code,
routes, dev pages, commit messages, docs, comments — is **English**. "Findbuch"
is banned from UI copy (archaic).

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
