# Review & verification brief

Standing rules for review and verification agents (fresh one-shot subagents).
Read `REVIEW-LEDGER.md.local` first; never re-report anything listed there.

## Findings

1. **No plausible pile.** Report a finding only with file:line evidence you
   read yourself at current HEAD. Drop or verify "likely/probably" findings
   before reporting — every unverified finding costs a second full pass later
   (the 2026-07-16 triage re-verified 18 parked findings; several were wrong
   in location, count, or direction).
2. **Verify at fix-time.** Line numbers, counts, and file names in older
   reports rot as waves land. Re-check every literal before it enters a brief.
3. **Stable IDs + verdicts.** Each finding gets an ID (`P1`, `T2`, `GH20`
   style) and exactly one verdict: CONFIRMED / FIXED-ALREADY /
   SUPERSEDED-DEFER / OWNER-DECISION / NOT-A-BUG. Confirmed findings route to
   a fix wave; consolidation-shaped ones to the consolidation issue;
   deploy-shaped ones to the deploy part.
4. **Dedup findings need caller-side analysis.** "Extract a shared partial"
   without checking the feeding views' context keys underestimates effort —
   the bulk-chooser "verbatim copy" was diverged markup plus mismatched
   context-key names across two views.
5. **Distrust wholesale monkeypatching.** A test that stubs the unit under
   review does not exercise it (the #20 client leak sat behind a
   `mirror_store` monkeypatch). Check what a test actually runs before citing
   it as coverage.
6. **Propose a pin for repeating defect classes — but only inside the testing
   razor** (domain-relevant / data-loss / data-leak; see the recurring
   anti-patterns in `docs/plans/test-audit-2026-08.md`). House idiom:
   {# #}-hygiene grep-tests. Style sweeps and load-count pins were removed in
   the 2026-08 audit as overkill — do not propose them again.

## Conduct

- Read-only: no edits, no commits, no test-suite mutations.
- Deliver the report before idling — structured output when the dispatch
  provides a schema; a report file on disk plus a message otherwise.
- Expected-verdict hints in a dispatch are hypotheses to refute, not
  conclusions to confirm.
- Empty is a valid result. Say "no findings" and stop; do not pad.
