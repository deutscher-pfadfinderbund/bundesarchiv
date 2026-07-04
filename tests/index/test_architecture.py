"""Architecture guards — the import-direction rules from docs/conventions.md + ADR 0005.

These assertions run WITHOUT a database (no ``django_db`` mark): they only parse source
and import the pure ``__init__``. The rules:

- ``domain/`` and ``persistence/`` must never import Django (framework stays at the edge).
- ``domain/`` and ``persistence/`` must never import ``bundesarchiv.index`` (nothing
  depends on the index adapter; the dependency arrow points inward only).
- The index adapter's public interface (``__all__``) is fixed now; Tasks 6-8 fill the
  stubs but must not change the exported surface.
"""

import ast
from pathlib import Path

import bundesarchiv.index

_SRC = Path(__file__).resolve().parents[2] / "src" / "bundesarchiv"
_PURE_PACKAGES = ("domain", "persistence")


def _module_names(node: ast.AST) -> list[tuple[str, str]]:
    """Every imported module name in a source tree, paired with the statement source."""
    # Syntactic guard only: catches import/from statements, not dynamic imports
    # (importlib.import_module / __import__) — those would need a runtime check.
    names: list[tuple[str, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            names.extend((alias.name, f"import {alias.name}") for alias in child.names)
        elif isinstance(child, ast.ImportFrom) and child.module is not None:
            names.append((child.module, f"from {child.module} import ..."))
    return names


def _pure_source_files() -> list[Path]:
    return sorted(path for package in _PURE_PACKAGES for path in (_SRC / package).rglob("*.py"))


def test_pure_packages_have_source_files() -> None:
    # Guard against the globs silently matching nothing (a green-for-the-wrong-reason bug).
    assert _pure_source_files(), "no source files found under domain/ or persistence/"


def test_domain_and_persistence_never_import_django() -> None:
    offenders: list[str] = []
    for path in _pure_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            f"{path.relative_to(_SRC)}: {stmt}"
            for module, stmt in _module_names(tree)
            if module == "django" or module.startswith("django.")
        )
    assert not offenders, "django imported in the pure core (see ADR 0005):\n" + "\n".join(
        offenders
    )


def test_domain_and_persistence_never_import_index() -> None:
    offenders: list[str] = []
    for path in _pure_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            f"{path.relative_to(_SRC)}: {stmt}"
            for module, stmt in _module_names(tree)
            if module == "bundesarchiv.index" or module.startswith("bundesarchiv.index.")
        )
    assert not offenders, "pure core imports the index adapter (arrow points inward):\n" + (
        "\n".join(offenders)
    )


def test_index_public_interface_is_pinned() -> None:
    assert bundesarchiv.index.__all__ == [
        "rebuild",
        "search",
        "SearchPage",
        "SearchHit",
        "SearchFilters",
    ]
    # Every exported name must actually exist (no dangling __all__ entries).
    for name in bundesarchiv.index.__all__:
        assert hasattr(bundesarchiv.index, name), f"__all__ names missing attribute: {name}"
