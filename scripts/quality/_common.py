"""Shared by the quality tools: git access, the docstring rule, the def walk and the report."""

import argparse
import ast
import json
import re
import subprocess
import tokenize
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import IO, Self, cast

type DocOwner = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
type Def = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
DOC_OWNERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
ROOTS = ("src/", "tests/", "scripts/")
_PRAGMA = re.compile(
    r"#\s*(noqa|type:|pyrefly:|pyright:|mypy:|ruff:|fmt:|isort:|pragma)", re.IGNORECASE
)


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603 — git with the tool's own arguments
        ["git", *args],  # noqa: S607 — git from PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class Blobs:
    """Reads blobs (``REV:PATH`` or a sha) through one ``git cat-file --batch`` process."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            ["git", "cat-file", "--batch"],  # noqa: S607 — git from PATH
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        self._in = cast(IO[bytes], self._proc.stdin)
        self._out = cast(IO[bytes], self._proc.stdout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._in.close()
        self._proc.wait()

    def get(self, spec: str) -> bytes | None:
        """The blob's bytes, or None when ``spec`` names nothing."""
        self._in.write(spec.encode() + b"\n")
        self._in.flush()
        header = self._out.readline().split()
        if len(header) != 3:
            return None
        data = self._out.read(int(header[2]))
        self._out.read(1)
        return data


def body_without_docstring(node: DocOwner) -> list[ast.stmt]:
    body = node.body
    match body:
        case [ast.Expr(value=ast.Constant(value=str())), *rest]:
            return rest
    return body


def is_pragma(comment: tokenize.TokenInfo) -> bool:
    """A comment a tool reads: a lint, type or format directive, or the shebang."""
    shebang = comment.start[0] == 1 and comment.string.startswith("#!")
    return shebang or bool(_PRAGMA.search(comment.string))


def defs(tree: ast.AST, prefix: str = "") -> Iterator[tuple[str, Def]]:
    """Every function and class under ``tree`` with its dotted qualname, outermost first."""
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (*FUNCTIONS, ast.ClassDef)):
            qualname = prefix + child.name
            yield qualname, child
            yield from defs(child, qualname + ".")
        else:
            yield from defs(child, prefix)


def tracked_python(*roots: str) -> list[str]:
    """Tracked ``.py`` files under ``roots``, as repo-relative paths."""
    return git("ls-files", "-z", "--", *(f"{root}*.py" for root in roots)).split("\0")[:-1]


@dataclass(frozen=True)
class Table:
    title: str
    note: str  # how to read it, and its known noise
    columns: tuple[str, ...]
    rows: Sequence[tuple[object, ...]]


def report_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--top", type=int, default=20, help="rows per table (0: all)")
    return parser


def _cell(value: object) -> str:
    if isinstance(value, tuple):
        return " ".join(map(_cell, value))
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def emit(tables: Sequence[Table], args: argparse.Namespace) -> None:
    """Print each table's top rows, as aligned text or (``--json``) one JSON object."""
    cut = args.top or None
    if args.json:
        payload = {
            t.title: [dict(zip(t.columns, row, strict=True)) for row in t.rows[:cut]]
            for t in tables
        }
        print(json.dumps(payload, indent=1))
        return
    for table in tables:
        rows = [tuple(_cell(v) for v in row) for row in table.rows[:cut]]
        widths = [max([len(c), *(len(r[i]) for r in rows)]) for i, c in enumerate(table.columns)]
        print(f"\n== {table.title} ({len(rows)} of {len(table.rows)})\n   {table.note}")
        for row in [table.columns, *rows]:
            print(
                "  "
                + "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
            )
