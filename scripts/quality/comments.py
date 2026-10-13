"""Report: every comment block and docstring in src/, tests/ and scripts/, with smell flags.

Usage: mise run quality:comments -- [--top N] [--json]

The flags are regexes over the text, a clue where to read, not a verdict: long (more than 3
lines), history (narrates a change), concrete-ref (a line number, a caller, a test name), filler,
args-block (an Args:/Returns: section) and doc>=body (a docstring as long as its function).
"""

import ast
import io
import re
import sys
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from scripts.quality._common import (
    ROOTS,
    DocOwner,
    Table,
    defs,
    emit,
    is_pragma,
    report_parser,
    tracked_python,
)

_HISTORY = re.compile(
    r"\b(previously|formerly|used to|no longer|now (also|uses|handles)|changed|was (removed|added)"
    r"|fix(ed)? #?\d+|#\d{2,}|issue \d+|wave \d+|legacy of)\b",
    re.IGNORECASE,
)
_CONCRETE = re.compile(
    r"(line \d+|:\d+\b|\btest_\w+|called (by|from)|used by|see (also )?\w+\.py)", re.IGNORECASE
)
_FILLER = re.compile(
    r"\b(note that|it is important|robust(ly)?|ensures? that|this (function|method|class) (will|is"
    r" responsible))\b",
    re.IGNORECASE,
)
_ARGS_BLOCK = re.compile(
    r"^\s*(Args|Arguments|Parameters|Returns|Raises|Yields):\s*$", re.MULTILINE
)


@dataclass(frozen=True)
class Item:
    where: str
    kind: str
    owner: str
    lines: int
    flags: tuple[str, ...]


def _text_flags(text: str, lines: int) -> list[str]:
    checks = [(_HISTORY, "history"), (_CONCRETE, "concrete-ref"), (_FILLER, "filler")]
    return ([f"long:{lines}"] if lines > 3 else []) + [n for rx, n in checks if rx.search(text)]


def _docstrings(path: str, tree: ast.Module) -> list[Item]:
    owners: list[tuple[str, DocOwner]] = [("<module>", tree), *defs(tree)]
    items = []
    for owner, node in owners:
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        lines = doc.strip().count("\n") + 1
        flags = _text_flags(doc, lines)
        if _ARGS_BLOCK.search(doc):
            flags.append("args-block")
        line = 1
        if not isinstance(node, ast.Module):
            line, doc_end = node.body[0].lineno, node.body[0].end_lineno or line
            body_lines = (node.end_lineno or doc_end) - doc_end
            if body_lines and lines >= body_lines:
                flags.append("doc>=body")
        items.append(Item(f"{path}:{line}", "docstring", owner, lines, tuple(flags)))
    return items


def _comments(path: str, source: str) -> list[Item]:
    """Contiguous ``#`` lines form one block."""
    blocks: list[list[tuple[int, str]]] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT or is_pragma(tok):
            continue
        if blocks and tok.start[0] == blocks[-1][-1][0] + 1:
            blocks[-1].append((tok.start[0], tok.string))
        else:
            blocks.append([(tok.start[0], tok.string)])
    return [
        Item(
            f"{path}:{block[0][0]}",
            "comment",
            "",
            len(block),
            tuple(_text_flags("\n".join(t for _, t in block), len(block))),
        )
        for block in blocks
    ]


def inventory(path: str, source: str) -> list[Item]:
    return _docstrings(path, ast.parse(source)) + _comments(path, source)


def main(argv: list[str]) -> int:
    args = report_parser(__doc__.splitlines()[0]).parse_args(argv)
    items = [i for p in tracked_python(*ROOTS) for i in inventory(p, Path(p).read_text())]
    flagged = sorted((i for i in items if i.flags), key=lambda i: (-len(i.flags), -i.lines))
    counts = Counter(f.split(":")[0] for i in items for f in i.flags)
    emit(
        [
            Table(
                "Comment and docstring smells",
                "Most flags first. A flag marks where to read; many are fine on reading.",
                ("where", "kind", "owner", "lines", "flags"),
                [(i.where, i.kind, i.owner, i.lines, i.flags) for i in flagged],
            ),
            Table(
                "Flag counts",
                f"Over {len(items)} comment blocks and docstrings, {len(flagged)} flagged.",
                ("flag", "count"),
                counts.most_common(),
            ),
        ],
        args,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
