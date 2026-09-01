---
name: audit-architecture
description: Periodic semantic audit of the module map and codebase architecture. Use every few waves, after a large merge, or when asked whether the architecture/map still holds. Finds shallow modules, sibling divergence, drift tests standing in for interfaces, and stale map rows.
---

# Architecture audit

The exhaustiveness gate catches *existence* drift mechanically. This skill is the *semantic* residue: is every map row still deep, is every seam still honest. Consumers: reviewers, architects.

## Vocabulary

Use the codebase-design terms exactly: module, interface, implementation, depth (deep/shallow), seam, adapter, leverage, locality. Never: component, service, API, boundary. Core instrument — the **deletion test**: delete the module; if complexity vanishes it was a pass-through, if it reappears across N callers it earns its keep.

## Two modes

**Hot-spot audit** (default, YAGNI): deepening pays off where change happens. Walk `git log --oneline --name-only` over the recent stretch; let hot files pull attention first. If the user named a direction, take it and skip inference.

**Full sweep** (on request: "evaluate the whole project", "compile the debt list"): every package, piece by piece, one explorer per package plus one per cross-cutting level (domain language vs reality, test suite shape, process law, build/CI). Output is a debt ledger per abstraction level (see step 5), not just deepening candidates. Estimate cost and confirm before launching — a sweep is many agents.

## The incumbency lens (both modes)

A pattern's presence proves nothing. For every recurring pattern you meet, ask three questions:
1. **Is it intentional?** Recorded in an ADR, package law, or owner ruling — or did it just accrete?
2. **Has it bitten?** Check the evidence trail: the debt ledger's entries (each carries its own bite evidence — commit refs, review findings, writer fence reports) and git history around the pattern's sites. A bite is a defect, a contortion, or repeated friction traceable to the pattern. There are no retro archives to consult — learnings are implemented directly into law, skills, or ledger entries when they happen (project ruling: no archaeological remains).
3. **Would we choose it again today?**

Unintentional + has bitten = rethink candidate. Intentional (ADR-backed) + repeatedly bitten = propose reopening the ADR, explicitly. Intentional + no bites = leave alone, whatever your taste says.

**An ADR is a record, not a proof.** ADRs here are largely AI-written from owner conversations, and transcription can bake in a misunderstanding. Before treating a pattern as settled by an ADR: (a) trace the ADR's claim to its source — the owner rulings in `docs/requirements/` where it cites one — and (b) check it against what the code actually does. An ADR claim with no traceable ruling and no code reality behind it is itself a debt entry ("unverified transcription"), not a shield. Where an ADR and the code disagree, flag the disagreement — never silently trust either side, and never "fix" code to match an ADR without confirming the ADR said what the owner meant.

## Procedure

1. Read first: `CONTEXT.md`, `MODULES.md`, the package `CLAUDE.md`s in scope, ADRs touching the area, and `docs/tech-debt.md` (open entries — do not re-derive them).
2. Spawn read-only explorer subagents to walk the scope organically. Give them the vocabulary and this friction checklist:
   - Understanding one concept requires bouncing between many small modules?
   - Shallow modules — interface nearly as complex as the implementation?
   - **Sibling divergence** — two functions in one module doing the same derivation differently (one via a library, one hand-rolled)?
   - **Drift tests standing in for interfaces** — a test that pins two copies equal instead of one module owning the fact?
   - Knowledge with no owning module — the same list/string/layout declared N times?
   - Strings built by joining externally-controlled values with an in-band delimiter?
   - Pure logic reachable only through heavy stacks (DB + HTTP + HTML grep for a link-algebra assertion)?
3. Deletion-test every map row in scope; flag rows that describe pass-throughs or whose hooks no longer match reality.
4. Do not re-litigate ADRs. Flag a conflict only when friction is severe enough to reopen one, and say so explicitly.
5. Record in `docs/tech-debt.md` — the ONE checked-in ledger, one section per abstraction level (domain language, module map/package structure, interfaces, implementation patterns, tests, process law, build/CI). Every entry carries: the pattern, a measurable indicator with its date, intentional? (ADR ref or "accreted"), bite evidence inline (commit/finding refs), cost class, and options; module/interface entries additionally carry the deepening sketch and a strength rating (Strong / Worth exploring / Speculative). Apply map corrections directly (they are facts, not proposals). No fixes, no dispatches — the ledger is input to a think-first prioritization with the owner; entries chosen for action graduate to GitHub issues via the triage flow.
6. Report: candidates by strength, map corrections made, what is already deep and should be left alone. Never start fixing during an audit — evaluation and action are separate decisions.

## Maintenance duties

- **Debt trend.** Re-measure every open ledger entry's indicator; record the new number and date and mark it better / worse / stable. Close entries whose pattern is gone. A trend check is re-measurement, not recollection.
- **Records hygiene.** Law, map and ledger files are re-read for growth. Every sentence must change what a reader does — otherwise delete it. The conciseness pass is done by an agent that did NOT write the text; defending an existing sentence requires naming who reads it and when.

### Framework health

The framework itself can fail, and that failure is the expensive one. It presents as recurrence, so the trend data is the detector. Each trigger below mandates a framework investigation — not writer-scolding:

- open-debt indicators trending worse across two consecutive audits, or the ledger only growing;
- a finding class recurring after its prevention rule landed;
- map rows stale at every audit despite the same-commit rule;
- the same fence, budget or gate breached repeatedly.

A framework investigation asks which assumption broke — wrong abstraction level, wrong owner, rule unenforceable, or rule wrong — and its outcome changes the framework (a rule, a level, a seam, this skill), not just the instance. A repeatedly-violated rule is evidence against the RULE at least as much as against its violators.
