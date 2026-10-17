"""The module map's exhaustiveness gate (leak-matrix pattern, applied to documentation).

Contract: every Python module under ``src/bundesarchiv`` is accounted for — either as a row in its
package's ``CLAUDE.md`` (a module with an interface worth knowing) or on that file's ``Internal:``
line (deliberate glue). The root ``CLAUDE.md`` "Module map" section points at every package's map,
and every ``tests:`` pointer in a row names something that exists. A new module without a row, a
deleted module with a stale row, a package the root does not point at, or a dead ``tests:`` path
all fail here, loudly, with the line to paste or the entry to delete.

The prose budgets below are the second half of the contract: an index that grows stops being an
index. They are mechanical on purpose — a busted budget is compressed, never raised.
"""

import ast
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "bundesarchiv"

#: The packages the map covers; a .py file outside these fails the sweep below, which is the
#: prompt to add the package (a new package needs a CLAUDE.md and a line in the root "Module map").
PACKAGES = ("domain", "persistence", "index", "app", "app/web")

#: Modules no package row needs to account for anywhere: package markers and Django app configs.
#: Migrations are excluded by path — they are generated, and the schema is derived (ADR 0003).
_ALWAYS_INTERNAL = {"__init__.py", "apps.py"}

PACKAGE_MAP_MAX_LINES = 45
ROW_MAX_CHARS = 220

_COMPRESS = "compress or bounce detail down a level — growth is a finding, not a default."

#: A module name as the map spells it: a package-relative POSIX path, so ``adapters/localfs.py``
#: and ``management/commands/ensure_index_current.py`` are single map entries.
_NAME = r"[a-z0-9_/]+\.py"
_ROW = re.compile(rf"^- `({_NAME})` — ", re.MULTILINE)
_ROW_LINE = re.compile(rf"^- `{_NAME}` .*$", re.MULTILINE)
_INTERNAL = re.compile(r"^Internal: (.+)$", re.MULTILINE)
_BACKTICKED = re.compile(rf"`({_NAME})`")


def _map_path(pkg: str) -> Path:
    return SRC / pkg / "CLAUDE.md"


def _package_files(pkg: str) -> set[str]:
    """Every module the package owns, as package-relative paths — sub-packages that carry their own
    map (``app/web`` under ``app``) belong to that map, not this one."""
    directory = SRC / pkg
    nested = [
        SRC / other
        for other in PACKAGES
        if other != pkg and (SRC / other).is_relative_to(directory)
    ]
    return {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*.py")
        if path.name not in _ALWAYS_INTERNAL
        and "migrations" not in path.parts
        and not any(path.is_relative_to(other) for other in nested)
    }


def _row_template(pkg: str, name: str) -> str:
    """A row in the grammar, the module docstring's first sentence as the responsibility."""
    docstring = ast.get_docstring(ast.parse((SRC / pkg / name).read_text()))
    first = (
        " ".join(docstring.split("\n\n")[0].split()).split(". ")[0].rstrip(".")
        if docstring
        else "<responsibility, one line>"
    )
    return f"- `{name}` — {first} · interface: <up to ~4 names> · tests: <test home>"


def _rows(pkg: str) -> set[str]:
    return set(_ROW.findall(_map_path(pkg).read_text()))


def _internals(pkg: str) -> set[str]:
    match = _INTERNAL.search(_map_path(pkg).read_text())
    return set(_BACKTICKED.findall(match.group(1))) if match else set()


def test_every_module_is_accounted_for() -> None:
    for pkg in PACKAGES:
        files, rows, internals = _package_files(pkg), _rows(pkg), _internals(pkg)
        assert not rows & internals, f"{pkg}: listed as both row and internal: {rows & internals}"
        unlisted = files - rows - internals
        stale = (rows | internals) - files
        assert not unlisted, (
            f"{pkg}: modules with no row and no Internal entry. Add to {_map_path(pkg).relative_to(ROOT)}"
            f" a row per module (or list it on the `Internal:` line):\n"
            + "\n".join(_row_template(pkg, name) for name in sorted(unlisted))
        )
        assert not stale, (
            f"{pkg}: delete these map entries, their files no longer exist: {sorted(stale)}"
        )


def test_no_module_outside_the_mapped_packages() -> None:
    mapped = [SRC / pkg for pkg in PACKAGES]
    strays = sorted(
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if path.name not in _ALWAYS_INTERNAL
        and "migrations" not in path.parts
        and not any(path.is_relative_to(pkg) for pkg in mapped)
    )
    assert not strays, f"modules outside every mapped package (new package? add it): {strays}"


def test_root_module_map_points_at_every_package() -> None:
    root = (ROOT / "CLAUDE.md").read_text()
    section = re.search(r"^## Module map\n(.*?)(?=^## |\Z)", root, re.MULTILINE | re.DOTALL)
    assert section, "CLAUDE.md lacks a `## Module map` section"
    missing = [
        f"- `{pkg}` — <one-liner> · `{_map_path(pkg).relative_to(ROOT)}`"
        for pkg in PACKAGES
        if f"`{_map_path(pkg).relative_to(ROOT)}`" not in section.group(1)
    ]
    assert not missing, "root CLAUDE.md Module map does not point at these packages; add:\n" + (
        "\n".join(missing)
    )


def test_the_index_files_stay_within_their_prose_budget() -> None:
    for pkg in PACKAGES:
        lines = len(_map_path(pkg).read_text().splitlines())
        assert lines <= PACKAGE_MAP_MAX_LINES, (
            f"{_map_path(pkg).relative_to(ROOT)}: {lines} lines, "
            f"budget {PACKAGE_MAP_MAX_LINES} — {_COMPRESS}"
        )


def test_every_row_is_one_line_within_budget() -> None:
    for pkg in PACKAGES:
        for row in _ROW_LINE.findall(_map_path(pkg).read_text()):
            assert len(row) <= ROW_MAX_CHARS, (
                f"{pkg}: row {len(row)} chars, budget {ROW_MAX_CHARS} — {_COMPRESS}\n{row}"
            )


_TESTS_SEGMENT = re.compile(r" · tests: (.*)$")


def _dead_test_pointers(pkg: str) -> list[tuple[str, str]]:
    """``(row, pointer)`` for every backticked pointer in a row's ``tests:`` segment that matches
    nothing. A full path (``tests/...``) resolves from the repo root; a bare name resolves in the
    directory of the last full path before it in the segment, or in the package's own test directory
    (``tests/<pkg>/``) when there is none. A pointer may be a glob or a directory; prose outside
    backticks is ignored."""
    pointers = []
    for row in _ROW_LINE.findall(_map_path(pkg).read_text()):
        segment = _TESTS_SEGMENT.search(row)
        directory = ROOT / "tests" / pkg
        for pointer in re.findall(r"`([^`]+)`", segment.group(1) if segment else ""):
            if pointer.startswith("tests/"):
                matches = list(ROOT.glob(pointer.rstrip("/")))
                path = ROOT / pointer.rstrip("/")
                directory = path if path.is_dir() else path.parent
            else:
                matches = list(directory.glob(pointer))
            if not matches:
                pointers.append((row, pointer))
    return pointers


def test_every_tests_pointer_in_a_row_exists() -> None:
    dead = [(row, pointer) for pkg in PACKAGES for row, pointer in _dead_test_pointers(pkg)]
    assert not dead, (
        "tests: pointers that match no file or directory — fix or delete:\n"
        + "\n".join(f"  `{pointer}` in {row[:60]}…" for row, pointer in dead)
    )


_PREFIX = "interface spelling that is not a name: "
_COLLECTION = "method of CollectionChooser, listed bare after `CollectionChooser.of`"
#: ``pkg/module.py:spelling`` -> reason: interface spellings that are not importable names.
INTERFACE_ALLOW: dict[str, str] = {
    "app/articles.py:delete_": _PREFIX + "`delete_`/`restore_`/`hard_delete_article` prefixes",
    "app/articles.py:restore_": _PREFIX + "`delete_`/`restore_`/`hard_delete_article` prefixes",
    **{
        f"app/web/collection_chooser.py:{m}": _COLLECTION
        for m in ("options", "accepts", "error", "name_of", "names", "by_ulid", "chain_of")
    },
    **{
        f"app/web/catalog_views.py:{m}": _PREFIX + "`article_create`/`_edit`/... suffix shorthand"
        for m in ("_edit", "_copy", "_delete", "_delete_permanently", "_restore")
    },
    "app/web/panels.py:*_panel": _PREFIX + "`the three *_panel builders`",
}

_INTERFACE_ROW = re.compile(rf"^- `({_NAME})` .*? interface: (.*?)(?: · tests:.*)?$", re.MULTILINE)


def _interface_names() -> set[str]:
    """``pkg/module.py:spelling`` for every backticked name in a row's ``interface:`` segment;
    ``.method`` forms belong to the name before them and are skipped."""
    return {
        f"{pkg}/{module}:{spelling}"
        for pkg in PACKAGES
        for module, segment in _INTERFACE_ROW.findall(_map_path(pkg).read_text())
        for spelling in re.findall(r"`([^`]+)`", segment)
        if not spelling.startswith(".")
    }


def _resolves(entry: str) -> bool:
    path, spelling = entry.split(":", 1)
    pkg = next(p for p in PACKAGES if path.startswith(p + "/"))
    module = path.removeprefix(pkg + "/").removesuffix(".py").replace("/", ".")
    imported = importlib.import_module(f"bundesarchiv.{pkg.replace('/', '.')}.{module}")
    return hasattr(imported, re.split(r"[.(]", spelling)[0])


def test_every_listed_interface_name_exists_on_its_module() -> None:
    stale = {e for e in _interface_names() if not _resolves(e)}
    assert not stale - set(INTERFACE_ALLOW), (
        f"interface names that do not exist on their module: {sorted(stale - set(INTERFACE_ALLOW))}"
    )
    assert not set(INTERFACE_ALLOW) - stale, (
        f"allow-list entries that now resolve: {sorted(set(INTERFACE_ALLOW) - stale)}"
    )
