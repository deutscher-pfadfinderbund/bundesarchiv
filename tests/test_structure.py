"""Structure gates over ``src/``: code-shape findings that stay fixed once fixed.

Each gate names a finding class with bite evidence (``docs/tech-debt.md``, the 2026-10-01 review).
Every allow-list entry cites its finding id; a gate fails on a NEW site and on an entry that no
longer occurs, so the lists only shrink.
"""

import ast
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
_TREES = {
    p.relative_to(SRC).as_posix(): ast.parse(p.read_text())
    for p in sorted(SRC.rglob("*.py"))
    if "migrations" not in p.parts
}

_MIN_NODES = 12

#: Groups of functions with an identical body (sorted ``module:qualname``) -> finding id.
DUPLICATE_BODIES: dict[tuple[str, ...], str] = {
    (
        "bundesarchiv/app/web/article_auth.py:_collections",
        "bundesarchiv/app/web/media_views.py:_collections",
    ): "debt #9",
    (
        "bundesarchiv/app/web/browse.py:_nonempty",
        "bundesarchiv/app/web/browse.py:_text",
    ): "review 2026-10-01, pattern 1",
    (
        "bundesarchiv/persistence/adapters/localfs.py:LocalFsObjectStore.list",
        "bundesarchiv/persistence/adapters/memory.py:InMemoryObjectStore.list",
        "bundesarchiv/persistence/adapters/webdav.py:WebDavObjectStore.list",
    ): "review 2026-10-01, pattern 1",
}

#: The ``HX-`` request-header names belong to the request-kind owner.
HX_OWNER = "bundesarchiv/app/web/viewers.py"
#: module outside the owner -> (number of ``HX-`` header names, finding id).
HX_READS: dict[str, tuple[int, str]] = {
    "bundesarchiv/app/web/anonymous_gate.py": (3, "W7"),
    "bundesarchiv/app/web/browse_views.py": (2, "W7"),
    "bundesarchiv/app/web/catalog_views.py": (2, "W7"),
    "bundesarchiv/app/web/collection_views.py": (2, "W7"),
}

#: Public top-level ``module:name`` that nothing in ``src/`` references -> reason.
UNREFERENCED: dict[str, str] = {
    "bundesarchiv/app/apps.py:AppServicesConfig": "Django app config, named by INSTALLED_APPS",
    "bundesarchiv/index/apps.py:IndexConfig": "Django app config, named by INSTALLED_APPS",
    "bundesarchiv/app/web/anonymous_gate.py:AnonymousGateMiddleware": "named by MIDDLEWARE",
    "bundesarchiv/app/web/viewers.py:TokenCookieMiddleware": "named by MIDDLEWARE",
    "bundesarchiv/app/management/commands/ensure_index_current.py:Command": "Django command",
    "bundesarchiv/app/management/commands/import_legacy.py:Command": "Django command",
    "bundesarchiv/app/management/commands/rebuild_index.py:Command": "Django command",
    "bundesarchiv/app/management/commands/rebuild_thumbnails.py:Command": "Django command",
    "bundesarchiv/app/management/commands/verify.py:Command": "Django command",
    "bundesarchiv/app/push_record.py:InMemoryPushRecord": "test fake",
    "bundesarchiv/persistence/adapters/memory.py:InMemoryObjectStore": "test fake",
    "bundesarchiv/app/tasks.py:mirror_reconcile": "Procrastinate task, run by name",
    "bundesarchiv/app/tasks.py:run_worker_once_in_test": "test hook, called from tests only",
}


def _functions() -> Iterator[tuple[str, str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for module, tree in _TREES.items():
        stack: list[tuple[ast.AST, str]] = [(tree, "")]
        while stack:
            node, prefix = stack.pop()
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield module, f"{prefix}{child.name}", child
                    stack.append((child, f"{prefix}{child.name}."))
                elif isinstance(child, ast.ClassDef):
                    stack.append((child, f"{prefix}{child.name}."))


def _body(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    first = fn.body[0]
    is_doc = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )
    return fn.body[1:] if is_doc else fn.body


def _duplicate_groups() -> set[tuple[str, ...]]:
    groups = defaultdict(list)
    for module, name, fn in _functions():
        body = _body(fn)
        if sum(1 for stmt in body for _ in ast.walk(stmt)) >= _MIN_NODES:
            groups["\n".join(ast.dump(stmt) for stmt in body)].append(f"{module}:{name}")
    return {tuple(sorted(names)) for names in groups.values() if len(names) > 1}


def _assert_matches[T: (str, tuple[str, ...])](found: set[T], allowed: set[T], what: str) -> None:
    assert not found - allowed, f"new {what}: {sorted(found - allowed)}"
    assert not allowed - found, (
        f"allow-list entries that no longer occur: {sorted(allowed - found)}"
    )


def test_no_two_functions_share_a_body() -> None:
    _assert_matches(_duplicate_groups(), set(DUPLICATE_BODIES), "identical function bodies")


_HX = re.compile(r"(HTTP_)?HX[-_][\w-]+")


def _hx_reads() -> Counter[str]:
    return Counter(
        module
        for module, tree in _TREES.items()
        if module != HX_OWNER
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _HX.fullmatch(node.value)
    )


def test_hx_header_names_appear_in_the_request_kind_owner_only() -> None:
    allowed = {module: count for module, (count, _) in HX_READS.items()}
    assert _hx_reads() == Counter(allowed), (
        f"HX- header names outside {HX_OWNER}: found {dict(_hx_reads())}, allowed {allowed}"
    )


def _referenced() -> set[str]:
    names: set[str] = set()
    for tree in _TREES.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add(node.name.split(".")[-1])
    return names


def _unreferenced() -> set[str]:
    referenced = _referenced()
    return {
        f"{module}:{node.name}"
        for module, tree in _TREES.items()
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and not node.name.startswith("_")
        and node.name not in referenced
    }


def test_no_public_name_is_unreferenced() -> None:
    _assert_matches(_unreferenced(), set(UNREFERENCED), "unreferenced public names")
