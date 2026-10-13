"""Report: syntactic design indicators over src/ (migrations excluded), each a clue where to look.

Usage: mise run quality:indicators -- [--top N] [--json]

Pass-throughs (one statement that forwards every parameter to another call), data clumps
(parameter groups recurring in signatures across files), conditions and string literals repeated
across modules, functions that mutate an argument, and module depth (code lines per unit of public
interface, shallowest first). No type information: a mutated argument may be a builder by design,
a repeated literal a vocabulary value.
"""

import ast
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path

from scripts.quality._common import (
    FUNCTIONS,
    Table,
    body_without_docstring,
    cognitive,
    defs,
    emit,
    report_parser,
    tracked_python,
)

type Function = tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]  # ("path::qualname", node)

_UNTELLING_PARAMS = frozenset({"self", "cls", "request", "args", "kwargs"})
_MUTATORS = frozenset(
    {
        "append",
        "extend",
        "update",
        "pop",
        "insert",
        "remove",
        "clear",
        "setdefault",
        "add",
        "discard",
    }
)
_WORD = re.compile(r"[a-z_][a-z0-9_\-]*")


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    a = fn.args
    return [x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs] if x.arg not in ("self", "cls")]


def pass_throughs(functions: Iterable[Function]) -> list[tuple[str, str]]:
    rows = []
    for key, fn in functions:
        match body_without_docstring(fn):
            case [ast.Return(value=ast.Call() as call) | ast.Expr(value=ast.Call() as call)]:
                values = [*call.args, *(k.value for k in call.keywords)]
                forwarded = {v.id for v in values if isinstance(v, ast.Name)}
                params = set(_params(fn))
                if params and params <= forwarded and len(values) - len(forwarded) <= 1:
                    rows.append((key, ast.unparse(call.func)))
    return rows


def data_clumps(functions: Iterable[Function]) -> list[tuple[str, int, int]]:
    """Parameter pairs and triples in at least 4 signatures across at least 2 files."""
    count: Counter[tuple[str, ...]] = Counter()
    files: defaultdict[tuple[str, ...], set[str]] = defaultdict(set)
    for key, fn in functions:
        names = sorted(set(_params(fn)) - _UNTELLING_PARAMS)
        for combo in [*combinations(names, 2), *combinations(names, 3)]:
            count[combo] += 1
            files[combo].add(key.split("::")[0])
    found = {c: n for c, n in count.items() if n >= 4 and len(files[c]) >= 2}
    maximal = [
        c
        for c, n in found.items()
        if not any(len(t) > len(c) and set(c) < set(t) and m >= n - 1 for t, m in found.items())
    ]
    rows = [(", ".join(c), found[c], len(files[c])) for c in maximal]
    return sorted(rows, key=lambda r: -r[1] * len(r[0].split(", ")))


def repeated(
    trees: dict[str, ast.Module],
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int]]]:
    """Conditions (25+ characters) in 2+ modules, and word-like literals in 4+ modules."""
    conditions: defaultdict[str, set[str]] = defaultdict(set)
    literals: defaultdict[str, set[str]] = defaultdict(set)
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.IfExp, ast.While)):
                tests = [node.test]
            elif isinstance(node, ast.comprehension):
                tests = node.ifs
            else:
                tests = []
            for test in tests:
                if len(text := ast.unparse(test)) >= 25:
                    conditions[text].add(path)
            match node:
                case ast.Constant(value=str(value)) if 4 <= len(value) <= 40 and _WORD.fullmatch(
                    value
                ):
                    literals[value].add(path)
    cond_rows = [(c, len(p), " ".join(sorted(p)[:3])) for c, p in conditions.items() if len(p) >= 2]
    lit_rows = [(lit, len(p)) for lit, p in literals.items() if len(p) >= 4]
    return sorted(cond_rows, key=lambda r: -r[1]), sorted(lit_rows, key=lambda r: -r[1])


def _mutated(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    params = set(_params(fn))
    hits: set[str] = set()
    for node in ast.walk(fn):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTATORS
        ):
            targets = [node.func]
        hits.update(
            ast.unparse(t)
            for t in targets
            if isinstance(t, (ast.Attribute, ast.Subscript))
            and isinstance(t.value, ast.Name)
            and t.value.id in params
        )
    return hits


def module_depth(
    sources: dict[str, str], trees: dict[str, ast.Module]
) -> list[tuple[str, int, int, int, int, float]]:
    """Modules over 30 code lines with a public interface, by code lines per interface unit."""
    rows = []
    for path, tree in trees.items():
        public = [
            n
            for n in tree.body
            if isinstance(n, (*FUNCTIONS, ast.ClassDef)) and not n.name.startswith("_")
        ]
        interface = sum(1 + (len(_params(n)) if isinstance(n, FUNCTIONS) else 0) for n in public)
        lines = [line.strip() for line in sources[path].splitlines()]
        code_lines = sum(1 for line in lines if line and not line.startswith("#"))
        if public and code_lines > 30:
            complexity = sum(cognitive(sources[path]).values())
            rows.append(
                (path, len(public), interface, complexity, code_lines, code_lines / interface)
            )
    return sorted(rows, key=lambda r: r[5])


def main(argv: list[str]) -> int:
    args = report_parser(__doc__.splitlines()[0]).parse_args(argv)
    sources = {p: Path(p).read_text() for p in tracked_python("src/") if "/migrations/" not in p}
    trees = {path: ast.parse(src) for path, src in sources.items()}
    functions = [
        (f"{path}::{name}", node)
        for path, tree in trees.items()
        for name, node in defs(tree)
        if isinstance(node, FUNCTIONS)
    ]
    conditions, literals = repeated(trees)
    mutations = [
        (key, " ".join(sorted(hits)[:3])) for key, fn in functions if (hits := _mutated(fn))
    ]
    emit(
        [
            Table(
                "Pass-throughs",
                "One statement forwarding every parameter: a layer that may add nothing.",
                ("function", "calls"),
                pass_throughs(functions),
            ),
            Table(
                "Data clumps",
                "Parameters that travel together: a missing value object, or a shared vocabulary.",
                ("parameters", "signatures", "files"),
                data_clumps(functions),
            ),
            Table(
                "Repeated conditions",
                "The same test in several modules: a decision without one owner.",
                ("condition", "modules", "first modules"),
                conditions,
            ),
            Table(
                "Repeated literals",
                "Word-like strings in 4+ modules: a name or key without a constant, or plain vocabulary.",
                ("literal", "modules"),
                literals,
            ),
            Table(
                "Argument mutation",
                "Writes through a parameter: hidden output, unless the parameter is a builder.",
                ("function", "mutated"),
                mutations,
            ),
            Table(
                "Module depth",
                "Code lines per unit of public interface (names + parameters), shallowest first.",
                ("module", "public", "interface", "complexity", "code_lines", "lines_per_unit"),
                module_depth(sources, trees),
            ),
        ],
        args,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
