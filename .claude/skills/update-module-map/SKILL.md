---
name: update-module-map
description: Keep the module map current. Use when creating, renaming, or deleting a module, changing a module's interface, or when the module-map gate test is red.
---

# Update the module map

The map is the navigation layer for everyone (humans, architects, writers, reviewers). It stays trustworthy because of two rules: **every fact has exactly one home**, and **the exhaustiveness gate fails loudly on drift**.

## The abstraction ladder — where a fact lives

| Level | File | Holds | Never holds |
| --- | --- | --- | --- |
| L0 | `CONTEXT.md` | domain language | code structure |
| L1 | `MODULES.md` (root) | package TOC: module names + one-line hooks | signatures, behavior, rules |
| L1.5 | `src/bundesarchiv/<pkg>/CLAUDE.md` | the package's module rows + package law | other packages' content, implementation detail |
| L2 | the module's docstring | the full interface contract (invariants, error modes, ordering) | implementation narration |
| L3 | code + `docs/adr/` | implementation; why decisions were made | — |

Detail that wants into a higher level gets **bounced down**, not copied up. Indices hold addresses, not facts. The one permitted duplication is module *names* appearing in both MODULES.md and a package row — the gate pins that equality.

## Row grammar (package CLAUDE.md)

One row per module that passes the **deletion test** (deleting it would scatter complexity across callers — see the codebase-design skill if available, else: a module earns a row when it hides real behavior behind a smaller interface):

```
- `<module>.py` — <responsibility, one line> · interface: <up to ~4 names a caller learns> · tests: <test home>
```

The module name is its path inside the package, so a sub-package module is one entry: `` `adapters/localfs.py` ``.

Modules that are deliberate internals (helpers, glue that fails the deletion test) go on the package's single `Internal:` line instead:

```
Internal: `_writer.py`, `errors.py`
```

Every `.py` module in the package must appear in exactly one of the two — the gate checks.

## MODULES.md grammar (root)

Per package, names + hooks only:

```
## <package> — <package one-liner>
`<module>`, `<module>`, `<module>` · rows + law: `src/bundesarchiv/<pkg>/CLAUDE.md`
```

## Prose budgets (enforced)

`MODULES.md` ≤ 40 lines; each package `CLAUDE.md` ≤ 45 lines; every row one line ≤ 220 chars. A busted budget is **compressed, never raised** — the detail belongs a level down (docstring, ADR). Growth in an index is a finding.

## The procedure

1. Identify the change class: new module / renamed / deleted / interface changed / implementation changed.
2. **Implementation-only change → touch nothing here.** The map is interface-level by design.
3. Otherwise edit the package row (and `MODULES.md` if a name appeared or vanished) **in the same commit** as the code change. This is writer law, not courtesy.
4. New module: apply the deletion test before granting a row; internals go on the `Internal:` line.
5. Keep the hook honest: if you can't write the responsibility in one line, the module may be the problem — note it as a debt entry (`docs/tech-debt.md`), don't write a two-line hook.
6. Verify what you wrote against the tree, never from memory: the interface names against the module's public defs, the `tests:` pointer against a file that exists.
7. Run the gate: `uv run pytest tests/test_module_map.py` (also part of `mise run check` via the no-DB suite).
