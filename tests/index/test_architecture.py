"""Architecture guards — the import-direction rules from docs/conventions.md + ADR 0005/0014.

These assertions run WITHOUT a database (no ``django_db`` mark): they only parse source
and import the pure ``__init__``. The rules:

- ``domain/`` and ``persistence/`` must never import Django (framework stays at the edge).
- ``domain/`` and ``persistence/`` must never import ``bundesarchiv.index`` (nothing
  depends on the index adapter; the dependency arrow points inward only).
- The index adapter's public interface (``__all__``) is fixed now; Tasks 6-8 fill the
  stubs but must not change the exported surface.
- ``domain/``, ``persistence/`` and ``index/`` must never import ``bundesarchiv.app`` (nothing
  depends on the application-service shell; the arrow points inward, ADR 0014 Part 4.2).
- ``bundesarchiv.app`` is the ONLY package allowed to import ``bundesarchiv.index`` — it is the
  imperative shell that wires the pure core to the index adapter (ADR 0014).
"""

import ast
from collections.abc import Callable
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


def _source_files(*packages: str) -> list[Path]:
    return sorted(path for package in packages for path in (_SRC / package).rglob("*.py"))


def _pure_source_files() -> list[Path]:
    return _source_files(*_PURE_PACKAGES)


def _offending_imports(paths: list[Path], is_forbidden: Callable[[str], bool]) -> list[str]:
    """Every `path: statement` whose imported module name satisfies ``is_forbidden(module)``."""
    offenders: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            f"{path.relative_to(_SRC)}: {stmt}"
            for module, stmt in _module_names(tree)
            if is_forbidden(module)
        )
    return offenders


def _is_module(module: str, package: str) -> bool:
    """True if ``module`` is ``package`` itself or a submodule of it."""
    return module == package or module.startswith(f"{package}.")


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


# --- app-package rules (ADR 0014 Part 4.2) ---------------------------------------


def test_core_and_index_never_import_app() -> None:
    """Nothing in domain/, persistence/ or index/ may depend on the application-service shell —
    the dependency arrow points inward (app -> index/persistence/domain, never the reverse)."""
    inward = _source_files(*_PURE_PACKAGES, "index")
    assert inward, "no source files found under domain/, persistence/ or index/"
    offenders = _offending_imports(inward, lambda m: _is_module(m, "bundesarchiv.app"))
    assert not offenders, "core/index imports the app shell (arrow points inward, ADR 0014):\n" + (
        "\n".join(offenders)
    )


def test_app_is_the_only_package_that_imports_index() -> None:
    """``bundesarchiv.app`` is the sole package allowed to import ``bundesarchiv.index`` (it wires
    the core to the adapter). Domain/persistence are already barred above; this pins that no OTHER
    package under src/bundesarchiv (present or future) reaches into the index adapter."""
    everything_but_app_and_index = sorted(
        path
        for path in _SRC.rglob("*.py")
        if not _is_module_path(path, "app") and not _is_module_path(path, "index")
    )
    assert everything_but_app_and_index, "no non-app, non-index source files found"
    offenders = _offending_imports(
        everything_but_app_and_index, lambda m: _is_module(m, "bundesarchiv.index")
    )
    assert not offenders, (
        "only bundesarchiv.app may import bundesarchiv.index (ADR 0014):\n" + "\n".join(offenders)
    )


def _is_module_path(path: Path, package: str) -> bool:
    """True if ``path`` lives under ``src/bundesarchiv/<package>/``."""
    return (_SRC / package) in path.parents
