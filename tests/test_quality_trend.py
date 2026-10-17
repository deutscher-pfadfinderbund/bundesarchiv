"""The trend report's counters (``scripts/quality/trend.py``): each number counts what it names."""

from collections import Counter
from datetime import date

import pytest
from scripts.quality._common import sessions
from scripts.quality.trend import (
    Commit,
    FileDelta,
    allow_lists,
    blamed,
    buckets,
    comment_lines,
    debt,
    escaped_from,
    line_ranges,
    mix,
    parse_diff,
    ratios,
)


def test_allow_lists_count_public_dict_entries_through_unpacked_comprehensions() -> None:
    source = """
_PRIVATE: dict[str, str] = {"a": "x"}
PACKAGES = ("domain", "app")
LIMIT = 45
UNREFERENCED: dict[str, str] = {"m:a": "why", "m:b": "why"}
INTERFACE_ALLOW = {
    "m.py:x": "why",
    **{f"m.py:{n}": "why" for n in ("a", "b", "c")},
    **{f"{p}:{n}": "why" for p in ["p", "q"] for n in ("a", "b", "c")},
}
EMPTY: dict[str, str] = {}
"""
    assert allow_lists(source) == {"UNREFERENCED": 2, "INTERFACE_ALLOW": 10, "EMPTY": 0}


@pytest.mark.parametrize(
    "source",
    [
        "ALLOW = {**OTHER}",
        'ALLOW = {**{k: "why" for k in NAMES}}',
        'ALLOW = {k: "why" for k in ("a", "b") if k}',
    ],
)
def test_allow_lists_leave_an_uncountable_list_unsized(source: str) -> None:
    assert allow_lists(source) == {"ALLOW": None}


# `git diff -U0` of "keep / -- old dash / keep2 / last" (no final newline) against
# "keep / ++ new plus / added / keep2 / last": the changed lines look like file headers.
_DIFF = """diff --git a/f.py b/f.py
index 6008507..7e040be 100644
--- a/f.py
+++ b/f.py
@@ -2 +2,2 @@ keep
--- old dash
+++ new plus
+added
@@ -4 +5 @@ keep2
-last
\\ No newline at end of file
+last
diff --git a/docs/new.md b/docs/new.md
new file mode 100644
--- /dev/null
+++ b/docs/new.md
@@ -0,0 +1 @@
+text
"""


def test_parse_diff_numbers_lines_that_look_like_headers_as_content() -> None:
    assert parse_diff(_DIFF) == [
        FileDelta(
            "f.py",
            "f.py",
            [(2, "-- old dash"), (4, "last")],
            [(2, "++ new plus"), (3, "added"), (5, "last")],
        ),
        FileDelta(None, "docs/new.md", [], [(1, "text")]),
    ]


_OLD = '''"""Module doc."""


def f(x):
    return x
'''

_NEW = '''"""Module doc,
over two lines."""


def f(x):
    # Why the offset.
    y = x + 1  # trailing: still code
    # noqa: E501

    return y
'''


def test_mix_sorts_lines_into_comments_and_code_by_path() -> None:
    removed = [(1, '"""Module doc."""'), (5, "    return x")]
    added: list[tuple[int, str]] = list(enumerate(_NEW.splitlines(), start=1))
    assert mix(FileDelta("src/m.py", "tests/m.py", removed, added), _OLD, _NEW) == Counter(
        {"comment-": 1, "code-": 1, "comment+": 3, "test+": 4}
    )


@pytest.mark.parametrize(
    ("path", "counted"),
    [
        ("docs/adr/0001.md", "prose+"),
        ("src/bundesarchiv/CLAUDE.md", "prose+"),
        (".claude/skills/x/SKILL", "prose+"),
        ("src/bundesarchiv/app/web/static/site.css", "code+"),
        ("scripts/x.sh", "code+"),
        ("tests/e2e/vendor/axe.min.js", None),
        ("src/bundesarchiv/index/migrations/0001_initial.py", None),
        ("uv.lock", None),
    ],
)
def test_mix_kinds_by_path(path: str, counted: str | None) -> None:
    counts = mix(FileDelta(None, path, [], [(1, "text"), (2, "  ")]), None, None)
    assert counts == (Counter({counted: 1}) if counted else Counter())


def test_blame_counts_lines_per_commit_from_porcelain_headers() -> None:
    a, b = "a" * 40, "b" * 40
    porcelain = f"""{a} 1 1 2
author X
summary {b} 9 9 9
previous {b} f.py
filename f.py
\tline one
{a} 2 2
\tline two
{b} 7 3 1
\t{a} 1 1
"""
    assert blamed(porcelain) == Counter({a: 2, b: 1})


def test_line_ranges_join_consecutive_numbers() -> None:
    assert line_ranges([7, 2, 3, 4, 9, 10]) == [(2, 4), (7, 7), (9, 10)]


def test_buckets_group_by_week_or_end_at_each_merge() -> None:
    log = [
        Commit("a" * 40, date(2026, 10, 4), 1, 0),  # Sunday
        Commit("b" * 40, date(2026, 10, 5), 2, 1),  # Monday, a merge
        Commit("c" * 40, date(2026, 10, 9), 1, 2),
    ]
    weeks = buckets(log, "week")
    assert [(b.label, len(b.commits)) for b in weeks] == [("2026-09-28", 1), ("2026-10-05", 2)]
    merges = buckets(log, "merge")
    assert [len(b.commits) for b in merges] == [2, 1]


def test_a_fix_escapes_only_from_introducers_of_other_sessions() -> None:
    session_of = {"early": 0, "same": 3, "other": 2}
    intros = [("same", 5), ("early", 2), ("other", 1)]
    assert escaped_from(intros, 3, session_of) == [("early", 2), ("other", 1)]
    assert escaped_from([("same", 5)], 3, session_of) == []


def test_sessions_split_where_commits_are_more_than_an_hour_apart() -> None:
    assert sessions([0, 3600, 7201, 7300]) == [0, 0, 1, 1]


def test_a_python_file_under_prose_stays_prose() -> None:
    delta = FileDelta(None, "docs/example.py", [], [(1, "# a comment")])
    assert mix(delta, None, "# a comment\n") == Counter({"prose+": 1})


def test_a_file_that_does_not_parse_is_counted_nowhere() -> None:
    bad = "def (:\n    # a comment\n"
    assert comment_lines(bad) is None
    assert mix(FileDelta(None, "src/m.py", [], [(2, "    # a comment")]), None, bad) == Counter()
    patching = (
        "import bundesarchiv.app.tasks as tasks\n"
        "def test_a(monkeypatch):\n"
        '    monkeypatch.setattr(tasks, "run", None)\n'
    )
    counters = debt({"tests/test_bad.py": bad, "tests/test_ok.py": patching})
    assert counters["test_patches"] == 1


def test_ratios_are_over_added_lines_and_absent_without_a_base() -> None:
    assert ratios(Counter({"code+": 2, "test+": 2, "comment+": 1})) == (1.0, 0.25)
    assert ratios(Counter({"test+": 4, "comment+": 2})) == (None, 0.5)
    assert ratios(Counter({"comment+": 2})) == (None, None)
