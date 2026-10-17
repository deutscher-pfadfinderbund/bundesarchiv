"""Patch sites in a test module: what each patch call replaces, read statically from the AST.

The test-patch gate (``tests/test_structure.py``) and ``quality:trend`` both count through it.
"""

import ast
from collections.abc import Iterator

_UNRESOLVED = "<unresolved>"
_PATCHERS = {"setattr", "delattr", "setitem", "delitem"}
_MOCK_PATCHERS = {
    f"{owner}.{name}"
    for owner in ("unittest.mock", "mocker")
    for name in ("patch", "patch.object", "patch.multiple", "patch.dict")
}
_PATCH_OPTIONS = {"target", "spec", "create", "spec_set", "autospec", "new_callable"}


def _dotted(expr: ast.expr, origin: dict[str, str]) -> str | None:
    """``expr`` with its root name replaced by its dotted origin, or ``None`` when it has none."""
    text = ast.unparse(expr)
    root = text.split(".")[0]
    return text.replace(root, origin[root], 1) if root in origin else None


def _names_in_scope(tree: ast.Module) -> dict[str, str]:
    """Each imported name, simple alias (``aw = after_write``) and annotated parameter -> its
    dotted origin."""
    origin: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                origin[alias.asname or root] = alias.name if alias.asname else root
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                origin[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Name | ast.Attribute)
            and (resolved := _dotted(node.value, origin))
        ):
            origin.setdefault(node.targets[0].id, resolved)
        elif (
            isinstance(node, ast.arg)
            and isinstance(node.annotation, ast.Name | ast.Attribute)
            and node.arg not in origin
            and (resolved := _dotted(node.annotation, origin))
        ):
            origin[node.arg] = resolved
    return origin


def _calls(
    node: ast.AST, scope: str = "<module>", loops: tuple[ast.For, ...] = (), cls: str = ""
) -> Iterator[tuple[ast.Call, str, tuple[ast.For, ...]]]:
    """Every call with its outermost enclosing function (``<module>`` outside one) and ``for``s."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call):
            yield child, scope, loops
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            inner = f"{cls}{child.name}" if scope == "<module>" else scope
            yield from _calls(child, inner, loops, cls)
        elif isinstance(child, ast.ClassDef):
            yield from _calls(child, scope, loops, f"{cls}{child.name}.")
        else:
            yield from _calls(
                child, scope, (*loops, child) if isinstance(child, ast.For) else loops, cls
            )


def _arg(call: ast.Call, index: int, *names: str) -> ast.expr | None:
    if len(call.args) > index:
        return call.args[index]
    return next((k.value for k in call.keywords if k.arg in names), None)


def _attribute_names(
    call: ast.Call, kind: str, loops: tuple[ast.For, ...]
) -> list[str | None] | None:
    """The attributes a patch replaces on its target (``[None]``: the target itself); ``None``
    when they cannot be read."""
    if kind == "patch.multiple":
        names = [k.arg for k in call.keywords if k.arg not in _PATCH_OPTIONS]
        return None if None in names else names
    if kind not in ("setattr", "delattr", "patch.object"):
        return [None]
    name = _arg(call, 1, "name", "attribute")
    if isinstance(name, ast.Constant) and isinstance(name.value, str):
        return [name.value]
    for loop in loops:
        if (
            isinstance(name, ast.Name)
            and isinstance(loop.target, ast.Name)
            and loop.target.id == name.id
            and isinstance(loop.iter, ast.Tuple | ast.List)
            and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in loop.iter.elts
            )
        ):
            return [str(e.value) for e in loop.iter.elts if isinstance(e, ast.Constant)]
    return None


def _sites(call: ast.Call, origin: dict[str, str], loops: tuple[ast.For, ...]) -> list[str]:
    """The dotted ``object.attribute`` of each replacement a patch call makes, or ``<unresolved>``
    for a site no static read resolves; ``[]`` when the call is not a patcher."""
    resolved = _dotted(call.func, origin) or ast.unparse(call.func)
    if resolved in _MOCK_PATCHERS:
        kind = resolved.removeprefix("unittest.mock.").removeprefix("mocker.")
    elif isinstance(call.func, ast.Attribute) and call.func.attr in _PATCHERS:
        kind = call.func.attr
    else:
        return []
    target = _arg(call, 0, "target", "in_dict", "name")
    base: str | None
    attrs: list[str | None] | None
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        base = target.value
        attrs = [None]
    else:
        base = _dotted(target, origin) if target else None
        attrs = _attribute_names(call, kind, loops)
    if base is None:
        return [_UNRESOLVED]
    if attrs is None:
        return [_UNRESOLVED] if base.split(".")[0] == "bundesarchiv" else []
    return [base if a is None else f"{base}.{a}" for a in attrs]


def patch_sites(tree: ast.Module) -> Iterator[tuple[str, str]]:
    """(outermost function or ``<module>``, dotted site) of each patch of a ``bundesarchiv``
    name; a site no static read resolves is ``<unresolved>``."""
    origin = _names_in_scope(tree)
    for call, scope, loops in _calls(tree):
        for site in _sites(call, origin, loops):
            if site == _UNRESOLVED or site.split(".")[0] == "bundesarchiv":
                yield scope, site
