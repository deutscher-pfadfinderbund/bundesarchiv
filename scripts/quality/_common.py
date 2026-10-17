"""Shared by the quality tools: git access, the docstring rule, the def walk and the report."""

import argparse
import ast
import io
import json
import re
import subprocess
import tokenize
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import accumulate, pairwise
from types import TracebackType
from typing import IO, Self, cast

import complexipy

type DocOwner = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
type Def = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
DOC_OWNERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
ROOTS = ("src/", "tests/", "scripts/")
_GAP_SECONDS = 3600
_PRAGMA = re.compile(
    r"#\s*(noqa|type:|pyrefly:|pyright:|mypy:|ruff:|fmt:|isort:|pragma)", re.IGNORECASE
)


def git_bytes(*args: str) -> bytes:
    return subprocess.run(  # noqa: S603 — git with the tool's own arguments
        ["git", *args],  # noqa: S607 — git from PATH
        capture_output=True,
        check=True,
    ).stdout


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603 — git with the tool's own arguments
        ["git", *args],  # noqa: S607 — git from PATH
        capture_output=True,
        text=True,
        errors="replace",
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

    def text(self, spec: str) -> str:
        """The blob decoded with bad bytes replaced; empty when ``spec`` names nothing."""
        return (self.get(spec) or b"").decode(errors="replace")


def tree_paths(sha: str) -> list[str]:
    """Every file path in the commit's tree."""
    return git("ls-tree", "-r", "-z", "--name-only", sha).split("\0")[:-1]


def first_parents(rev: str) -> list[tuple[str, int, int]]:
    """(sha, committer time, parent count) of each first-parent commit of ``rev``, oldest first."""
    rows = git("log", "--first-parent", "--reverse", "--format=%H %ct %P", rev).splitlines()
    return [(sha, int(time), len(parents)) for sha, time, *parents in map(str.split, rows)]


def sessions(times: list[int]) -> list[int]:
    """The work session of each commit, given committer times oldest first: a new one starts after
    a gap of more than an hour."""
    return list(accumulate((int(b - a > _GAP_SECONDS) for a, b in pairwise(times)), initial=0))


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


def comments(source: str) -> list[tokenize.TokenInfo]:
    """Every comment token but the pragmas."""
    return [
        tok
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT and not is_pragma(tok)
    ]


def docstrings(tree: ast.Module) -> Iterator[tuple[str, DocOwner, ast.Expr]]:
    """Each docstring: its owner's qualname (``<module>`` for the module), the owner, the statement."""
    owners: list[tuple[str, DocOwner]] = [("<module>", tree), *defs(tree)]
    for owner, node in owners:
        match node.body:
            case [ast.Expr(value=ast.Constant(value=str())) as statement, *_]:
                yield owner, node, statement


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


def cognitive(source: str) -> dict[str, int]:
    """Cognitive complexity per top-level function and method, by dotted qualname.

    complexipy scores nested functions inside their parent and skips methods of nested classes.
    """
    return {
        f.name.replace("::", "."): f.complexity
        for f in complexipy.code_complexity(source).functions
    }


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
    if value is None:
        return "-"
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
