"""The comment-only gate never passes a diff that changes code (``scripts/quality/comments_only.py``)."""

import subprocess
from pathlib import Path

import pytest
from scripts.quality.comments_only import Change, main, problem

_SAME_MODE = ("100644", "100644")

_PY = '''"""Module doc."""


def f(x):
    """Doc."""
    # Why the offset.
    return x + 1
'''

_JS = """// Theme switch.
const url = "//cdn.example/a.js";
/* Block
   comment. */
function f(x) {
  return x + 1; // why
}
"""

_PASSES = {
    "py docstrings and comments reworded": (
        "a.py",
        _PY,
        _PY.replace("Module doc.", "Other.").replace("Doc.", "New.").replace("offset", "step"),
    ),
    "py docstring and comment removed": (
        "a.py",
        _PY,
        "\n\ndef f(x):\n    return x + 1\n",
    ),
    "py docstring removed, empty body becomes pass": (
        "a.py",
        'def f():\n    """Doc."""\n\n\nclass A:\n    """Doc."""\n',
        "def f():\n    pass\n\n\nclass A:\n    ...\n",
    ),
    "js comments reworded and removed": (
        "a.js",
        _JS,
        _JS.replace("// Theme switch.\n", "").replace("Block", "Other").replace("// why", ""),
    ),
}

_FAILS = {
    "py code token": ("a.py", _PY, _PY.replace("x + 1", "x + 2")),
    "py real pass removed from a multi-statement body": (
        "a.py",
        "def f(x):\n    x()\n    pass\n",
        "def f(x):\n    x()\n",
    ),
    "py pragma comment": ("a.py", "x = f()  # type: ignore[attr]\n", "x = f()\n"),
    "js code token": ("a.js", _JS, _JS.replace("x + 1", "x + 2")),
    "js string that holds //": ("a.js", _JS, _JS.replace("cdn.example/a", "cdn.example/b")),
    "js regex literal that holds a quote": (
        "a.js",
        "const r = /'/; const s = '//a'; f(1);\n",
        "const r = /'/; const s = '//a'; f(2);\n",
    ),
    "css comment": ("a.css", "/* a */\nb {}\n", "/* c */\nb {}\n"),
}


@pytest.mark.parametrize(("path", "before", "after"), _PASSES.values(), ids=_PASSES.keys())
def test_a_comment_only_change_passes(path: str, before: str, after: str) -> None:
    assert problem(Change(path, before.encode(), after.encode(), _SAME_MODE)) is None


@pytest.mark.parametrize(("path", "before", "after"), _FAILS.values(), ids=_FAILS.keys())
def test_a_change_beyond_comments_fails(path: str, before: str, after: str) -> None:
    assert problem(Change(path, before.encode(), after.encode(), _SAME_MODE)) is not None


@pytest.mark.parametrize(
    "change",
    [
        Change("a.py", None, b"x = 1\n", _SAME_MODE),
        Change("a.py", b"x = 1\n", None, _SAME_MODE),
        Change("a.py", b"x = 1\n", b"x = 1\n", ("100644", "100755")),
    ],
    ids=["added", "deleted", "mode"],
)
def test_a_file_added_deleted_or_rechmodded_fails(change: Change) -> None:
    assert problem(change) is not None


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 — fixed arguments
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],  # noqa: S607 — git on PATH
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c")
    return _git(repo, "rev-parse", "HEAD")


def test_the_gate_exits_on_the_verdict_over_a_real_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a git hook (the pre-push gate) exports GIT_DIR & co., which outrank -C and the cwd: unset,
    # this test and the gate it runs would write and read the pushing repo, not tmp_path
    for name in _git(tmp_path, "rev-parse", "--local-env-vars").split():
        monkeypatch.delenv(name, raising=False)
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "t")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "t@example.org")
    _git(tmp_path, "init", "-q")
    first = _commit(tmp_path, {"a.py": _PY, "b.js": _JS})
    js_comment_dropped = _JS.replace("// Theme switch.\n", "")
    comments = _commit(tmp_path, {"a.py": _PY.replace("Doc.", "New."), "b.js": js_comment_dropped})
    code = _commit(tmp_path, {"a.py": _PY.replace("x + 1", "x + 2")})
    monkeypatch.chdir(tmp_path)

    assert main([first, comments]) == 0
    assert main([comments, code]) == 1
