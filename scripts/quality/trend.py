"""Report: project quality over main's first-parent history, per week: escapes, debt, diff mix.

Usage: mise run quality:trend -- [--since YYYY-MM-DD] [--per week|merge] [--top N] [--json]

Escapes. A fix is a commit whose subject has the conventional ``fix`` prefix. It escaped from the
commits ``git blame -w -M`` on its parent names for the code and test lines it removes or
modifies, counted only when they were on main before the fix arrived and reached it in an earlier
session (churn's rule). A fix whose blamed lines all come from its own branch or session is
in-wave. Limits: a mislabelled commit is missed or miscounted; a fix that only adds
lines (a missing guard) blames nothing and counts as unblamed; blame names the last commit to
touch a line, which may be a move or a reformat rather than the cause.

Debt, at each bucket's last commit: entries of the allow-lists (public module-level dicts) in the
structure and module-map gates, finding rows of quality:indicators (module depth left out), items
flagged by quality:comments, and test patches of ``bundesarchiv`` names.

Diff mix, over the net diff between bucket ends: non-blank lines added (+) and removed (-) in code
(src/, scripts/), tests (tests/), full-line Python comments and docstrings (taken out of code and
tests) and prose (docs/, .claude/, *.md); migrations and vendored files are left out. The ratios
are over added lines, comments against code plus tests.

Results are cached per commit under the git dir's quality-trend-cache/, keyed by this tool's
source, so a re-run is instant.
"""

import ast
import hashlib
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from itertools import groupby
from pathlib import Path
from typing import Any

from scripts.quality._common import (
    ROOTS,
    Blobs,
    Table,
    comments,
    docstrings,
    emit,
    first_parents,
    git,
    report_parser,
    sessions,
    tree_paths,
)
from scripts.quality.comments import inventory
from scripts.quality.indicators import findings, in_scope
from scripts.quality.patches import patch_sites

_GATES = ("tests/test_structure.py", "tests/test_module_map.py")
_FIX = re.compile(r"fix(\([^)]*\))?!?:")
_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_BLAME_HEADER = re.compile(r"([0-9a-f]{40}) \d+ \d+(?: \d+)?")
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_KINDS = ("code", "test", "comment", "prose")
_COUNTERS = ("indicators", "comment_flags", "test_patches")
_TOOL_FILES = ("trend.py", "_common.py", "comments.py", "indicators.py", "patches.py")


@dataclass
class FileDelta:
    old: str | None  # None: the file does not exist on that side
    new: str | None
    removed: list[tuple[int, str]] = field(default_factory=list)  # (old line number, text)
    added: list[tuple[int, str]] = field(default_factory=list)  # (new line number, text)


def _header_path(line: str) -> str | None:
    path = line[4:].rstrip("\t")
    return None if path == "/dev/null" else path[2:]


def parse_diff(text: str) -> list[FileDelta]:
    """Files of a ``git diff -U0`` with the removed and added lines of each."""
    deltas: list[FileDelta] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.startswith("--- ") and i < len(lines) and lines[i].startswith("+++ "):
            deltas.append(FileDelta(_header_path(line), _header_path(lines[i])))
            i += 1
        elif hunk := _HUNK.match(line):
            old_start, old_n, new_start, new_n = (
                int(n) if n is not None else 1 for n in hunk.groups()
            )
            delta = deltas[-1]
            removed, added = len(delta.removed), len(delta.added)
            while len(delta.removed) - removed < old_n or len(delta.added) - added < new_n:
                body = lines[i]
                i += 1
                if body.startswith("-"):
                    delta.removed.append((old_start + len(delta.removed) - removed, body[1:]))
                elif body.startswith("+"):
                    delta.added.append((new_start + len(delta.added) - added, body[1:]))
    return deltas


def kind(path: str) -> str | None:
    if path.endswith(".md") or path.startswith(("docs/", ".claude/")):
        return "prose"
    if "/migrations/" in path or "/vendor/" in path:
        return None
    if path.startswith("tests/"):
        return "test"
    return "code" if path.startswith(("src/", "scripts/")) else None


def parse(source: str) -> ast.Module | None:
    """The module, or None for a file no longer valid Python (history holds such files)."""
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def comment_lines(source: str) -> frozenset[int] | None:
    """Lines holding only a comment or belonging to a docstring; None when ``source`` won't parse."""
    tree = parse(source)
    if tree is None:
        return None
    full_line = {tok.start[0] for tok in comments(source) if not tok.line[: tok.start[1]].strip()}
    in_docstrings = {
        line
        for _, _, doc in docstrings(tree)
        for line in range(doc.lineno, (doc.end_lineno or doc.lineno) + 1)
    }
    return frozenset(full_line | in_docstrings)


def mix(delta: FileDelta, old_source: str | None, new_source: str | None) -> Counter[str]:
    """Non-blank lines by kind and sign (``code+``, ``comment-`` ...); sources only for Python."""
    out: Counter[str] = Counter()
    for sign, path, lines, source in (
        ("-", delta.old, delta.removed, old_source),
        ("+", delta.new, delta.added, new_source),
    ):
        base = kind(path) if path else None
        if base is None:
            continue
        doc = (
            comment_lines(source)
            if source is not None and base in ("code", "test")
            else frozenset()
        )
        if doc is None:
            continue
        out.update(("comment" if n in doc else base) + sign for n, text in lines if text.strip())
    return out


def _entries(node: ast.expr) -> int | None:
    """The number of entries in a dict expression, or None when no static read can count it."""
    match node:
        case ast.Dict(keys=keys, values=values):
            sizes = [1 if k is not None else _entries(v) for k, v in zip(keys, values, strict=True)]
            return sum(n for n in sizes if n is not None) if None not in sizes else None
        case ast.DictComp(generators=gens):
            lengths = [
                len(g.iter.elts)
                for g in gens
                if isinstance(g.iter, (ast.Tuple, ast.List, ast.Set)) and not g.ifs
            ]
            if len(lengths) == len(gens):
                return math.prod(lengths)
    return None


def allow_lists(source: str) -> dict[str, int | None]:
    """Entries per allow-list, a public module-level constant bound to a dict; None: uncountable."""
    bindings = (
        (node.targets[0], node.value) if isinstance(node, ast.Assign) else (node.target, node.value)
        for node in ast.parse(source).body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    )
    return {
        target.id: _entries(value)
        for target, value in bindings
        if isinstance(target, ast.Name)
        and target.id.isupper()
        and not target.id.startswith("_")
        and isinstance(value, (ast.Dict, ast.DictComp))
    }


def debt(sources: dict[str, str]) -> dict[str, Any]:
    """Debt counters over a snapshot's Python files under the roots (path -> source); a file that
    does not parse is left out."""
    trees = {path: tree for path, src in sources.items() if (tree := parse(src)) is not None}
    return {
        "allow": {
            name: n for p in _GATES if p in trees for name, n in allow_lists(sources[p]).items()
        },
        "indicators": sum(
            len(table.rows) for table in findings({p: t for p, t in trees.items() if in_scope(p)})
        ),
        "comment_flags": sum(1 for p in trees for i in inventory(p, sources[p]) if i.flags),
        "test_patches": sum(
            1 for p, tree in trees.items() if p.startswith("tests/") for _ in patch_sites(tree)
        ),
    }


def line_ranges(numbers: Iterable[int]) -> list[tuple[int, int]]:
    """Runs of consecutive numbers as (first, last)."""
    runs = groupby(enumerate(sorted(numbers)), key=lambda pair: pair[1] - pair[0])
    return [(group[0][1], group[-1][1]) for group in (list(g) for _, g in runs)]


def blamed(porcelain: str) -> Counter[str]:
    """Lines per commit in ``git blame --porcelain`` output."""
    return Counter(m[1] for line in porcelain.splitlines() if (m := _BLAME_HEADER.fullmatch(line)))


def ratios(lines: Counter[str]) -> tuple[float | None, float | None]:
    """Added test lines per code line, and added comment lines per code and test line."""
    code, both = lines["code+"], lines["code+"] + lines["test+"]
    return (lines["test+"] / code if code else None, lines["comment+"] / both if both else None)


def escaped_from(
    intros: list[tuple[str, int]], session: int, session_of: dict[str, int]
) -> list[tuple[str, int]]:
    """The introducers (sha, lines) a fix in ``session`` escaped from: those of other sessions."""
    return [(sha, n) for sha, n in intros if session_of[sha] != session]


@dataclass(frozen=True)
class Commit:
    sha: str
    day: date
    parents: int
    session: int


@dataclass(frozen=True)
class Bucket:
    label: str
    commits: tuple[Commit, ...]  # first-parent commits, oldest first


def buckets(log: list[Commit], per: str) -> list[Bucket]:
    """First-parent commits, oldest first, grouped by week or ended at each merge."""
    if per == "week":
        weeks = groupby(log, key=lambda c: c.day - timedelta(days=c.day.weekday()))
        return [Bucket(monday.isoformat(), tuple(group)) for monday, group in weeks]
    ends = [i for i, c in enumerate(log) if c.parents > 1 or i == len(log) - 1]
    return [
        Bucket(f"{log[end].day} {log[end].sha[:8]}", tuple(log[start : end + 1]))
        for start, end in zip([0, *(e + 1 for e in ends)], ends, strict=False)
    ]


def _diff(base: str, head: str) -> str:
    return git(
        "-c",
        "core.quotePath=false",
        "diff",
        "-U0",
        "-M",
        "--no-color",
        "--no-ext-diff",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        base,
        head,
    )


class Cache:
    def __init__(self) -> None:
        here = Path(__file__).parent
        version = hashlib.sha256(b"".join((here / f).read_bytes() for f in _TOOL_FILES))
        root = Path(git("rev-parse", "--git-common-dir").strip()) / "quality-trend-cache"
        self.dir = root / version.hexdigest()[:12]
        self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, compute: Callable[[], Any]) -> Any:
        path = self.dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        value = compute()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value))
        tmp.replace(path)
        return value


def _snapshot(blobs: Blobs, sha: str) -> dict[str, str]:
    return {
        p: blobs.text(f"{sha}:{p}")
        for p in tree_paths(sha)
        if p.endswith(".py") and p.startswith(ROOTS)
    }


def _python(blobs: Blobs, sha: str, path: str | None) -> str | None:
    if path is None or not path.endswith(".py"):
        return None
    return blobs.text(f"{sha}:{path}")


def _mix(blobs: Blobs, base: str, head: str) -> dict[str, int]:
    total: Counter[str] = Counter()
    for delta in parse_diff(_diff(base, head)):
        total += mix(delta, _python(blobs, base, delta.old), _python(blobs, head, delta.new))
    return dict(total)


def _escape(sha: str, main_before: str | None) -> dict[str, Any]:
    """What a fix commit's removed code and test lines blame to, kept to commits on main."""
    lines: Counter[str] = Counter()
    for delta in parse_diff(_diff(f"{sha}^", sha)):
        if delta.old is None or kind(delta.old) not in ("code", "test") or not delta.removed:
            continue
        ranges = [
            arg for a, b in line_ranges(n for n, _ in delta.removed) for arg in ("-L", f"{a},{b}")
        ]
        lines += blamed(
            git("blame", "--porcelain", "-w", "-M", *ranges, f"{sha}^", "--", delta.old)
        )
    escaped = lines.most_common()
    if main_before is not None:
        on_main = set(git("rev-list", main_before).split())
        escaped = [(c, n) for c, n in escaped if c in on_main]
    return {"blamed": sum(lines.values()), "escaped": escaped}


def _arrivals(first_parent: Commit) -> list[tuple[str, bool]]:
    """Commits that reach main with this first-parent commit, each with whether it is a merge."""
    if first_parent.parents < 2:
        return [(first_parent.sha, False)]
    rows = git("rev-list", "--parents", f"{first_parent.sha}^1..{first_parent.sha}")
    return [(sha, len(parents) > 1) for sha, *parents in map(str.split, rows.splitlines())]


@dataclass(frozen=True)
class Main:
    """What every bucket reads of main's history."""

    info: dict[str, tuple[int, str]]  # sha -> (committer time, subject)
    arrivals: dict[str, list[tuple[str, bool]]]  # first-parent sha -> _arrivals
    session_of: dict[str, int]  # sha -> session of the first-parent commit it arrived with


@dataclass(frozen=True)
class Rows:
    """One bucket's share of each table."""

    debt: tuple[object, ...]
    mix: tuple[object, ...]
    escapes: list[tuple[object, ...]]
    allow: dict[str, int]


def _bucket(bucket: Bucket, base: str, cache: Cache, blobs: Blobs, main: Main) -> Rows:
    head = bucket.commits[-1].sha
    counters = cache.get(f"debt-{head}", lambda: debt(_snapshot(blobs, head)))
    lines = Counter(cache.get(f"mix-{base}-{head}", lambda: _mix(blobs, base, head)))
    arrived = [
        (fp, sha) for fp in bucket.commits for sha, merge in main.arrivals[fp.sha] if not merge
    ]
    fixes = [
        (
            sha,
            cache.get(
                f"fix-{sha}", partial(_escape, sha, f"{fp.sha}^1" if fp.parents > 1 else None)
            ),
        )
        for fp, sha in arrived
        if _FIX.match(main.info[sha][1])
    ]
    escapes = [
        (sha, intros)
        for sha, fix in fixes
        if (intros := escaped_from(fix["escaped"], main.session_of[sha], main.session_of))
    ]
    blamed_fixes = sum(1 for _, fix in fixes if fix["blamed"])
    info = main.info
    return Rows(
        (
            bucket.label,
            len(arrived),
            len(fixes),
            len(escapes),
            blamed_fixes - len(escapes),
            len(fixes) - blamed_fixes,
            sum(n for n in counters["allow"].values() if n is not None),
            *(counters[k] for k in _COUNTERS),
        ),
        (
            bucket.label,
            *(lines[f"{k}{s}"] for k in _KINDS for s in "+-"),
            *ratios(lines),
        ),
        [
            (
                bucket.label,
                f"{sha[:8]} {info[sha][1]}",
                f"{intro[:8]} {info[intro][1]}",
                (info[sha][0] - info[intro][0]) // 86400,
                n,
                len(intros) - 1,
            )
            for sha, intros in escapes
            for intro, n in intros[:1]
        ],
        counters["allow"],
    )


def main(argv: list[str]) -> int:
    parser = report_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=date.min,
        help="YYYY-MM-DD: buckets ending on or after it",
    )
    parser.add_argument("--per", choices=("week", "merge"), default="week")
    args = parser.parse_args(argv)
    first = first_parents("main")
    log = [
        Commit(sha, datetime.fromtimestamp(time, UTC).date(), parents, session)
        for (sha, time, parents), session in zip(
            first, sessions([time for _, time, _ in first]), strict=True
        )
    ]
    arrivals = {c.sha: _arrivals(c) for c in log}
    history = Main(
        {
            sha: (int(time), subject)
            for sha, time, subject in (
                line.split("\0")
                for line in git("log", "--format=%H%x00%ct%x00%s", "main").splitlines()
            )
        },
        arrivals,
        {sha: c.session for c in log for sha, _ in arrivals[c.sha]},
    )
    cache = Cache()
    every = buckets(log, args.per)
    bases = [_EMPTY_TREE, *(b.commits[-1].sha for b in every[:-1])]
    with Blobs() as blobs:
        rows = [
            _bucket(bucket, base, cache, blobs, history)
            for bucket, base in zip(every, bases, strict=True)
            if bucket.commits[-1].day >= args.since
        ][::-1]
    names = sorted({name for row in rows for name in row.allow})
    emit(
        [
            Table(
                "Escapes and debt",
                "Escapes: fixes blaming a line from an earlier session on main; in-wave: from the"
                " fix's own session or branch; unblamed: no code or test line removed.",
                (
                    "bucket",
                    "commits",
                    "fixes",
                    "escapes",
                    "in_wave",
                    "unblamed",
                    "allow",
                    *_COUNTERS,
                ),
                [row.debt for row in rows],
            ),
            Table(
                "Diff mix",
                "Non-blank lines added/removed between bucket ends; ratios over added lines.",
                ("bucket", *(f"{k}{s}" for k in _KINDS for s in "+-"), "test:code", "comment:code"),
                [row.mix for row in rows],
            ),
            Table(
                "Escapes",
                "The commit that last touched most of the lines a fix changed, and how long before.",
                ("bucket", "fix", "escaped_from", "days", "lines", "more"),
                [escape for row in rows for escape in row.escapes[::-1]],
            ),
            Table(
                "Allow-lists",
                "Entries per ratchet allow-list at the bucket's last commit; - before the list existed.",
                ("bucket", *names),
                [(row.debt[0], *(row.allow.get(name) for name in names)) for row in rows],
            ),
        ],
        args,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
