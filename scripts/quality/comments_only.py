"""Gate: a diff between two commits touches only comments and docstrings.

Usage: mise run quality:comments-only -- BASE [HEAD]

A Python file passes when its AST is unchanged once docstrings are dropped (a body left empty
equals ``pass`` or ``...``); a JS file when its code is unchanged once comments are dropped.
Pragma comments (``noqa``, ``type:``, ``biome-ignore`` ...) and the shebang count as code. Every
other change fails: another file type, a file added, deleted, renamed or re-chmodded, a file that
does not parse. Exit 0: comments only; 1: code changed; 2: usage or git error.
"""

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from scripts.quality._common import DOC_OWNERS, Blobs, body_without_docstring, git, is_pragma

_JS_PRAGMA = re.compile(r"biome-ignore|@ts-|eslint|@license|@preserve|^/\*!")
# What may stand before a regex literal; before anything else a slash divides.
_REGEX_AFTER = re.compile(
    r"(?:[(,=:\[!&|?{};+\-*%<>~^]|\b(?:return|typeof|case|do|else|in|of|new|delete|void|throw"
    r"|yield|await|instanceof))\s*\Z"
)
_NULL_SHA = "0" * 40


@dataclass(frozen=True)
class Change:
    path: str
    before: bytes | None  # None: the file does not exist on that side
    after: bytes | None
    modes: tuple[str, str]


def _is_placeholder(body: list[ast.stmt]) -> bool:
    match body:
        case [] | [ast.Pass()]:
            return True
        case [ast.Expr(value=ast.Constant(value=value))]:
            return value is ...
    return False


def _py_shape(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, DOC_OWNERS):
            body = body_without_docstring(node)
            node.body = [] if _is_placeholder(body) else body
    pragmas = [
        (tok.line[: tok.start[1]].strip(), tok.string)
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT and is_pragma(tok)
    ]
    return ast.dump(tree) + repr(pragmas)


def _comment_end(source: str, i: int) -> int:
    if source[i + 1] == "/":
        end = source.find("\n", i)
        return len(source) if end < 0 else end
    end = source.find("*/", i + 2)
    return len(source) if end < 0 else end + 2


def _quoted_end(source: str, i: int) -> int:
    """End of the string literal opening at ``i``; an unterminated one ends at the line."""
    quote, j = source[i], i + 1
    while j < len(source) and source[j] not in (quote, "\n"):
        j += 2 if source[j] == "\\" else 1
    return min(j + 1, len(source)) if source[j : j + 1] == quote else j


def _template_end(source: str, i: int) -> tuple[int, bool]:
    """End of the template text starting at ``i``, and whether it stops at a ``${``."""
    j = i
    while j < len(source):
        if source[j] == "\\":
            j += 2
        elif source[j] == "`":
            return j + 1, False
        elif source.startswith("${", j):
            return j + 2, True
        else:
            j += 1
    return len(source), False


def _regex_end(source: str, i: int) -> int:
    j, in_class = i + 1, False
    while j < len(source) and source[j] != "\n":
        c = source[j]
        if c == "\\":
            j += 1
        elif c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            while j < len(source) and source[j].isalpha():
                j += 1
            return j
        j += 1
    return j


class _JsScan:
    """Code with comments dropped; whitespace in code collapses, literals stay verbatim."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.parts: list[str] = []
        self.code: list[str] = []
        self.depth: list[int] = []  # open braces inside each pending template ``${``

    def shape(self) -> str:
        i = 0
        while i < len(self.source):
            i = self.step(i)
        self.literal("")
        return "".join(self.parts).strip()

    def literal(self, text: str) -> None:
        code = "".join(self.code)
        self.parts.append(re.sub(r"\s+", lambda m: "\n" if "\n" in m[0] else " ", code))
        self.parts.append(text)
        self.code.clear()

    def step(self, i: int) -> int:
        source, c = self.source, self.source[i]
        if source.startswith(("//", "/*"), i):
            end = _comment_end(source, i)
            text = source[i:end]
            if _JS_PRAGMA.search(text):
                self.literal(text)
            else:
                self.code.append("\n" if "\n" in text else " ")
            return end
        if c in "'\"":
            end = _quoted_end(source, i)
        elif c == "`" or (c == "}" and self.depth and self.depth[-1] == 0):
            if c == "}":
                self.depth.pop()
            end, opened = _template_end(source, i + 1)
            if opened:
                self.depth.append(0)
        elif c == "/" and _REGEX_AFTER.search(source[max(0, i - 12) : i]):
            end = _regex_end(source, i)
        else:
            if self.depth and c in "{}":
                self.depth[-1] += 1 if c == "{" else -1
            self.code.append(c)
            return i + 1
        self.literal(source[i:end])
        return end


def _js_shape(source: str) -> str:
    return _JsScan(source).shape()


_SHAPES: dict[str, Callable[[str], str]] = {".py": _py_shape, ".js": _js_shape}


def problem(change: Change) -> str | None:
    """Why ``change`` is more than a comment change, or None when it is not."""
    if change.before is None or change.after is None:
        return "added or deleted"
    if change.modes[0] != change.modes[1]:
        return "mode changed"
    shape = _SHAPES.get(PurePosixPath(change.path).suffix)
    if shape is None:
        return "not a Python or JS file"
    try:
        same = shape(change.before.decode()) == shape(change.after.decode())
    except UnicodeDecodeError, SyntaxError, tokenize.TokenError:
        return "does not parse"
    return None if same else "code changed"


def changes(base: str, head: str) -> list[Change]:
    raw = git("diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, head).split("\0")
    out = []
    with Blobs() as blobs:
        for meta, path in zip(raw[0:-1:2], raw[1::2], strict=True):
            old_mode, new_mode, old_sha, new_sha, _ = meta.lstrip(":").split()
            before = None if old_sha == _NULL_SHA else blobs.get(old_sha)
            after = None if new_sha == _NULL_SHA else blobs.get(new_sha)
            out.append(Change(path, before, after, (old_mode, new_mode)))
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base")
    parser.add_argument("head", nargs="?", default="HEAD")
    args = parser.parse_args(argv)
    try:
        found = changes(args.base, args.head)
    except subprocess.CalledProcessError as error:
        print(f"git failed: {error.stderr.strip()}", file=sys.stderr)
        return 2
    bad = [(c.path, reason) for c in found if (reason := problem(c))]
    print(f"{len(found)} files changed, {len(bad)} beyond comments")
    for path, reason in bad:
        print(f"  {path}: {reason}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
