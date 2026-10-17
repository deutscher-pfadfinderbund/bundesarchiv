"""``scripts/affected.py`` maps a diff to the suites that must run (``mise run test:affected``)."""

import subprocess
import tomllib
from pathlib import Path

import pytest
from scripts import affected

ROOT = Path(__file__).parent.parent
_DB = ["test:db"]
_BROWSER = ["test:gallery", "test:e2e"]
_FACTS = affected.Facts(
    browser_imports=frozenset({"src/bundesarchiv/app/media_text.py"}),
    pg_tests=frozenset({"tests/app/test_articles.py"}),
    deleted_tests=frozenset({"tests/app/test_gone.py"}),
)


@pytest.mark.parametrize(
    ("path", "suites"),
    [
        ("src/bundesarchiv/index/query.py", _DB),
        ("src/bundesarchiv/app/migrations/0004_x.py", _DB),
        ("src/bundesarchiv/persistence/repository.py", _DB),
        ("src/bundesarchiv/domain/audience.py", _DB),
        ("src/bundesarchiv/app/mirror.py", _DB),
        ("src/bundesarchiv/app/web/views.py", ["test:db", *_BROWSER]),
        ("src/bundesarchiv/app/media_text.py", ["test:db", *_BROWSER]),
        ("tests/app/test_articles.py", _DB),
        ("tests/app/test_gone.py", _DB),
        ("tests/conftest.py", _DB),
        ("tests/_articles.py", _DB),
        ("tests/app/web/_fixtures.py", _DB),
        ("tests/index/fixtures.py", _DB),
        ("tests/app/encrypted.pdf", _DB),
        ("src/bundesarchiv/app/web/templates/detail.html", _BROWSER),
        ("src/bundesarchiv/app/web/static/menu.js", _BROWSER),
        ("src/bundesarchiv/app/web/static/tokens.css", _BROWSER),
        ("tests/e2e/test_journeys.py", _BROWSER),
        ("tests/e2e/_corpus.py", _BROWSER),
        ("pyproject.toml", ["test:db", *_BROWSER]),
        ("uv.lock", ["test:db", *_BROWSER]),
        ("mise.toml", ["test:db", *_BROWSER]),
        ("tests/domain/test_viewer.py", []),
        ("tests/CLAUDE.md", []),
        ("scripts/affected.py", []),
        ("README.md", []),
    ],
)
def test_each_rule_selects_its_suites(path: str, suites: list[str]) -> None:
    assert sorted(s for s, _ in affected.select([path], _FACTS)) == sorted(suites)


def test_a_suite_selected_twice_runs_once_and_names_every_path() -> None:
    plan = affected.select(
        ["src/bundesarchiv/index/query.py", "src/bundesarchiv/persistence/repository.py"], _FACTS
    )

    assert [(suite, len(reasons)) for suite, reasons in plan] == [("test:db", 2)]


def test_the_browser_imports_are_the_ones_corpus_and_conftest_import_directly() -> None:
    modules = affected.browser_imports()

    assert {
        "src/bundesarchiv/app/media_text.py",
        "src/bundesarchiv/index/indexer.py",
        "tests/_pdfs.py",
        "src/bundesarchiv/app/web/viewers.py",
    } <= modules
    assert "src/bundesarchiv/app/__init__.py" not in modules


def test_every_selected_suite_is_a_mise_task() -> None:
    tasks = tomllib.loads((ROOT / "mise.toml").read_text())["tasks"]

    assert {suite for rule in affected.RULES for suite in rule.suites} <= tasks.keys()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 — fixed command
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_unpushed_commits_and_uncommitted_files_are_both_in_the_diff(tmp_path: Path) -> None:
    origin, work = tmp_path / "origin", tmp_path / "work"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", str(origin), str(work))
    (work / "a.txt").write_text("a")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "pushed")
    _git(work, "push", "-u", "origin", "main")
    (work / "unpushed.txt").write_text("u")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "unpushed")
    (work / "a.txt").write_text("dirty")
    (work / "untracked.txt").write_text("n")

    assert sorted(set(affected.diff_paths(None, work))) == [
        "a.txt",
        "unpushed.txt",
        "untracked.txt",
    ]


def test_an_unknown_ref_is_an_error_not_an_empty_diff(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")

    with pytest.raises(SystemExit, match="unknown ref: nope"):
        affected.diff_paths("nope", tmp_path)


def test_a_failing_git_call_stops_the_script_instead_of_selecting_nothing(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "commit", "--allow-empty", "-m", "a")
    _git(tmp_path, "checkout", "--orphan", "other")
    _git(tmp_path, "commit", "--allow-empty", "-m", "b")

    with pytest.raises(SystemExit, match="failed"):  # main...HEAD has no merge base
        affected.diff_paths("main", tmp_path)
