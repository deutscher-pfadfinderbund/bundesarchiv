"""Shared by the quality tools: git access and the docstring rule."""

import ast
import subprocess
from types import TracebackType
from typing import IO, Self, cast

type DocOwner = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
DOC_OWNERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


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
