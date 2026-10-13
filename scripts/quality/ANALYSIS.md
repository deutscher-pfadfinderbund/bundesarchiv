# Comment and docstring review, 2026-10-13: numbers

What a two-pass review of every comment and docstring found and changed, and which signals were worth computing. The tools in this directory reproduce the signals (`mise run quality:comments`, `quality:churn`, `quality:indicators`; `quality:comments-only` is the gate).

## Before and after

Python under `src/` and `tests/`, migrations excluded. "Lines per 100" counts docstring lines plus comment lines per 100 lines of code.

| | src before | src after | tests before | tests after |
|---|---|---|---|---|
| Docstrings | 721 | 621 | 558 | 460 |
| Docstring lines | 2,853 | 1,531 | 1,826 | 809 |
| Comment lines | 853 | 539 | 2,262 | 1,685 |
| Lines per 100 | 25.8 | 16.4 | 14.7 | 9.5 |

`quality:comments` over the repo: 3,052 comment blocks and docstrings with 755 smell-flagged (25%) before, 2,623 with 361 flagged (14%) after. The merged diff: 155 files, +819 / −4,204 lines, no code token changed (proven per commit by the AST gate).

## The passes

**Pass 1, audit.** 3,099 comments and docstrings, judged by agents with the code open:

| Verdict | Count | Checked by a skeptic | Upheld |
|---|---|---|---|
| keep | 2,132 | – | – |
| shrink | 592 | – | – |
| delete | 229 | 117 (sample) | 113 (97%) |
| wrong (false against the code) | 88 | 88 | 83 (94%) |
| refactor (cannot shrink: the function needs work) | 25 | 25 | 18 (72%) |
| debatable | 35 | – | issue #74 |

907 of the 910 wrong/delete/shrink verdicts landed; the 3 skipped are JS comments inside a Python string, which the gate counts as code.

**Pass 2, review of pass 1's own text.** All 699 comments and docstrings pass 1 wrote or changed (405 docstrings), one verdict per item: 223 keep, 221 delete, 233 shrink, 19 wrong, 3 worse (the new text dropped a constraint the old one carried, e.g. when `indexer.CONFIG_VERSION` must be bumped). Applied with a per-clause deletion test: +506 / −1,188 lines over 145 files.

**Lesson.** One agent pass leaves about two thirds of what it writes still cuttable: agents cut one clause and stop, and their proposed texts are drafts (several were false and caught only because writers re-checked every claim). Both are now writer law (`writer-discipline`, "Comment discipline").

## Signals that worked

- **Code changed while the docstring did not.** Over each docstring's history: 1.96 such edits for docstrings judged wrong, 1.28 for other findings, 0.51 for kept ones. The best staleness predictor found (`quality:churn`, "Docstrings at risk").
- **Cheap smell flags** (long, history words, concrete references, docstring as long as the body): 63% of flagged items had a finding, 21% of unflagged ones (3× lift).
- **Docstring churn.** Docstrings with findings averaged 0.8 rewrites, kept ones 0.3. Docstring churn is also the strongest predictor of code churn (rank correlation 0.58 over 625 `src` functions), stronger than any complexity metric.
- **Churn × cognitive complexity** surfaces the same functions as docstring churn: `browse_views._sentence`, `_results_context`, `workbench`, `catalog.parse_edit_form`. The `app/web` views are the hotspot.
- **Adversarial verification and one-verdict-per-item reviews.** Precision above; the per-item review is what caught the 3 regressions and 19 wrong claims in new text.
- **The AST comment-only gate.** Every writer branch passed it; zero code drift across 155 files.

## Signals that did not work, or only as a clue

- **Churn counted per commit.** It depends on commit size: August's commits run to 3,449 changed lines at the 90th percentile, September's to 402. `quality:churn` measures the net change per work session instead (a gap of over an hour ends one), so many small commits and one squash give the same result.
- **File churn against the smell-flag ratio:** rank correlation −0.2. Neither predicts the other; use both.
- **Complexity alone against churn:** correlation 0.25; only 11 of the 40 most-churned functions are among the 40 most complex. A complement, not a substitute.
- **"Logic in the shell" without type information:** an effect call list matches `dict.get` as an I/O call, so the list is noise. Needs mypy's types before it is worth running.
- **ruff `D` / `DOC` (pydocstyle, pydoclint):** about 2,000 hits pushing `Args:`/`Returns:` docstrings, the opposite of the goal.
- **A written rule alone.** The comment-discipline law of 2026-08-08 left density flat (31–32 lines per 100) for six weeks; it fell only from late September.
- **Change coupling without an import edge** (`domain/identity.py` with `persistence/readme.py` in every shared session): a clue, not yet checked against defects.

## History

Docstring and comment lines per 100 lines of `src` code over the repo's history (snapshots every 25 commits): about 24 at the end of June, 33 in July's build-out, 31–32 through mid-September, 25 on 2026-10-12, 16.4 after this review. 51% of `src` docstrings ran past three lines at the July peak, 34% before this review.

## Found along the way

- Issue #72: the Medienart/Dokumenttyp vocabulary lives in the web layer (one pinned import-linter exception).
- Issue #73: a bulk Bestand move can change inherited visibility without the over-exposure check.
- Issue #74: the 35 debatable comments.
- Assertions that cannot fail: `tests/app/web/test_workbench.py` checks the old `artikel`/`entwuerfe` params, which no link carries since the English rename; `test_collection_edit.py`'s parent-name assert passes on the "Bundesarchiv" wordmark; the `test_catalog_edit.py` field-order test filters exactly as the code does, so a reorder stays green.
- Not covered by the gate yet: Jinja template comments (`{# #}`) and JS comments inside Python strings.
