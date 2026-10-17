"""Pick the test suites a diff needs, print why, and run them.

Usage: mise run test:affected [-- BASE] [--dry-run]

The diff is BASE...HEAD (BASE defaults to main; with no commits there, the upstream's unpushed
commits) plus uncommitted changes. `check` is the per-commit gate and is not run here.
"""

import argparse
import ast
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROWSER_SETUP = ("tests/e2e/_corpus.py", "tests/e2e/conftest.py")
_PG_TESTS = "requires_pg and not e2e and not gallery"  # the marker expression of test:db


@dataclass(frozen=True)
class Facts:
    """What the rules need beyond a path: all three sets come from the file system and pytest."""

    browser_imports: frozenset[str]
    pg_tests: frozenset[str]
    deleted_tests: frozenset[str]


@dataclass(frozen=True)
class Rule:
    suites: tuple[str, ...]
    reason: str
    matches: Callable[[str, Facts], bool]


def _pattern(regex: str) -> Callable[[str, Facts], bool]:
    compiled = re.compile(regex)
    return lambda path, _facts: compiled.search(path) is not None


_BROWSER = ("test:gallery", "test:e2e")
_ALL = ("test:db", *_BROWSER)

# One row per condition. `test:db` runs every Postgres-backed test, tests/index and the app leak
# matrix included, so no row names `test:index` or `test:app` (their other tests run in `check`).
RULES: tuple[Rule, ...] = (
    Rule(("test:db",), "Python source", _pattern(r"^src/bundesarchiv/.*\.py$")),
    Rule(
        ("test:db",),
        "shared test fixture",  # a suite-local fixture or helper: any non-test file outside e2e
        _pattern(r"^tests/(?!e2e/)(?:.*/)?(?!test_)[^/]*(?<!\.md)$"),
    ),
    Rule(("test:db",), "Postgres-backed test", lambda path, facts: path in facts.pg_tests),
    Rule(("test:db",), "deleted test", lambda path, facts: path in facts.deleted_tests),
    Rule(_BROWSER, "UI", _pattern(r"^src/bundesarchiv/app/web/.*\.(html|css|js)$")),
    Rule(_BROWSER, "UI (view)", _pattern(r"^src/bundesarchiv/app/web/.*\.py$")),
    Rule(_BROWSER, "browser suite import", lambda path, facts: path in facts.browser_imports),
    Rule(_BROWSER, "browser suite", _pattern(r"^tests/e2e/")),
    Rule(_ALL, "dependencies", _pattern(r"^(pyproject\.toml|uv\.lock|mise\.toml)$")),
)


def select(paths: Iterable[str], facts: Facts) -> list[tuple[str, tuple[str, ...]]]:
    """Each needed suite, in rule order, with the ``path (reason)`` entries that selected it."""
    paths = sorted(set(paths))
    chosen = (
        (suite, f"{path} ({rule.reason})")
        for rule in RULES
        for path in paths
        if rule.matches(path, facts)
        for suite in rule.suites
    )
    by_suite: dict[str, list[str]] = {}
    for suite, reason in chosen:
        by_suite.setdefault(suite, []).append(reason)
    order = dict.fromkeys(suite for rule in RULES for suite in rule.suites)
    return [(suite, tuple(by_suite[suite])) for suite in order if suite in by_suite]


def browser_imports(setup: Iterable[str] = BROWSER_SETUP) -> frozenset[str]:
    """Repo paths of the first-party modules the browser suites' setup imports directly (ast)."""

    def file_of(dotted: str) -> str | None:
        parts = dotted.split(".")
        base = Path("src", *parts) if parts[0] == "bundesarchiv" else Path(*parts)
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if (ROOT / candidate).is_file():
                return candidate.as_posix()
        return None

    found: set[str | None] = set()
    for node in (n for f in setup for n in ast.walk(ast.parse((ROOT / f).read_text()))):
        match node:
            case ast.Import(names=names):
                found.update(file_of(alias.name) for alias in names)
            case ast.ImportFrom(module=str(module), level=0, names=names):
                # `from pkg import name` imports a module when `pkg.name` is one, else `pkg`.
                found.update(
                    file_of(f"{module}.{alias.name}") or file_of(module) for alias in names
                )
    return frozenset(path for path in found if path)


def _git(root: Path, *args: str) -> list[str]:
    result = subprocess.run(  # noqa: S603 — fixed command
        ["git", *args],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        sys.exit(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.splitlines()


def _ref_exists(root: Path, ref: str) -> bool:
    return (
        subprocess.run(  # noqa: S603 — fixed command
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],  # noqa: S607
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def diff_paths(base: str | None, root: Path = ROOT) -> list[str]:
    """BASE...HEAD (default main; when empty, the upstream's unpushed commits), then the working
    tree and untracked files."""
    ref = base or "main"
    if not _ref_exists(root, ref):
        sys.exit(f"unknown ref: {ref}")

    def committed(since: str) -> list[str]:
        return _git(root, "diff", "--name-only", "--no-renames", f"{since}...HEAD")

    paths = committed(ref)
    if not paths and base is None and _ref_exists(root, "@{upstream}"):
        paths = committed("@{upstream}")
    return [
        *paths,
        *_git(root, "diff", "--name-only", "--no-renames", "HEAD"),
        *_git(root, "ls-files", "--others", "--exclude-standard"),
    ]


def pg_tests_among(files: list[str]) -> frozenset[str]:
    """The test files holding a test that test:db runs (asked of pytest, not re-derived)."""
    if not files:
        return frozenset()
    collected = subprocess.run(  # noqa: S603 — fixed command
        ["uv", "run", "pytest", "--collect-only", "-q", "-m", _PG_TESTS, *files],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if collected.returncode not in (0, 5):  # 5: nothing collected
        sys.exit(
            f"pytest could not collect the changed tests:\n{collected.stdout}{collected.stderr}"
        )
    return frozenset(line.split("::")[0] for line in collected.stdout.splitlines() if "::" in line)


def run(suites: Iterable[str]) -> int:
    """Run each suite in the foreground; the first red stops the line and sets the exit code."""
    for suite in suites:
        print(f"\n== mise run {suite}", flush=True)
        code = subprocess.run(["mise", "run", suite], cwd=ROOT, check=False).returncode  # noqa: S603, S607
        if code:
            return code
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", nargs="?", help="diff against BASE...HEAD (default: main)")
    parser.add_argument("--dry-run", action="store_true", help="print the suites, run nothing")
    args = parser.parse_args()

    paths = diff_paths(args.base)
    tests = {
        p for p in paths if p.startswith("tests/") and re.fullmatch(r"test_[^/]*\.py", Path(p).name)
    }
    present = sorted(p for p in tests if (ROOT / p).is_file())
    deleted = frozenset(p for p in tests - set(present) if not p.startswith("tests/e2e/"))
    plan = select(paths, Facts(browser_imports(), pg_tests_among(present), deleted))
    for suite, reasons in plan:
        print(suite)
        print(*(f"  {reason}" for reason in reasons), sep="\n")
    if not plan:
        print("no suite selected by this diff")
    code = 0 if args.dry_run else run(suite for suite, _ in plan)
    print("`check` is not part of this: it stays the per-commit gate (mise run check)")
    return code


if __name__ == "__main__":
    sys.exit(main())
