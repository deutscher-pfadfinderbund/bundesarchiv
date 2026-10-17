"""Report: function churn per work session, hotspots, stale-docstring risk and change coupling.

Usage: mise run quality:churn -- [--under PREFIX] [--top N] [--json]

A session is a run of first-parent commits less than an hour apart (committer time). A session's
change is the net diff between its boundary snapshot and the previous one, so ten small commits
and one squashed commit count the same. A function's exposure is the sessions it lived through
after the one that created it; rates shrink toward the base rate (a prior of 5 sessions), so one
edit to a young function does not top the list. Signature (arguments, return annotation) and body
(decorators included) are counted apart. Functions follow file renames; a function that is moved
or renamed starts over. Coupling pairs .py files that change in the same sessions without an
import between them; sessions touching more than 25 files are skipped.
"""

import ast
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations, count
from pathlib import PurePosixPath

from scripts.quality._common import (
    FUNCTIONS,
    ROOTS,
    Blobs,
    Table,
    body_without_docstring,
    cognitive,
    defs,
    emit,
    first_parents,
    git,
    report_parser,
    sessions,
    tree_paths,
)

_PRIOR_SESSIONS = 5
_COUPLING_MAX_FILES = 25
_COUPLING_MIN_SUPPORT = 4


@dataclass(frozen=True)
class Fn:
    signature: str
    body: str
    doc: str | None


@dataclass
class History:
    """Counts of sessions, each after the creating one, whose net change touched this part."""

    born: int
    signature: int = 0
    body: int = 0
    changed: int = 0
    doc: int = 0
    code_only: int = 0  # code changed while the docstring stayed as it was

    def record(self, before: Fn, after: Fn) -> None:
        signature, body = before.signature != after.signature, before.body != after.body
        self.signature += signature
        self.body += body
        self.changed += signature or body
        if before.doc is not None and after.doc is not None:
            self.doc += before.doc != after.doc
            self.code_only += (signature or body) and before.doc == after.doc


def functions(source: str) -> dict[str, Fn] | None:
    """Every function by qualname, or None when ``source`` does not parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return {
        name: Fn(
            ast.dump(node.args) + (ast.dump(node.returns) if node.returns else ""),
            ast.dump(ast.Module(body_without_docstring(node), []))
            + "".join(map(ast.dump, node.decorator_list)),
            ast.get_docstring(node),
        )
        for name, node in defs(tree)
        if isinstance(node, FUNCTIONS)
    }


class Walk:
    """Folds session diffs into per-function histories; a file keeps its identity across renames."""

    def __init__(self) -> None:
        self.ident: dict[str, int] = {}
        self.current: dict[int, dict[str, Fn]] = {}
        self.history: dict[tuple[int, str], History] = {}
        self.touched: list[set[int]] = []
        self._ids = count()

    def delete(self, path: str) -> None:
        fid = self.ident.pop(path)
        for name in self.current.pop(fid, {}):
            del self.history[fid, name]

    def update(self, session: int, status: str, old: str, new: str, source: str) -> int:
        """Apply one changed file; returns its identity."""
        fid = self.ident.pop(old, None) if status in "MRT" else None
        if fid is None:
            fid = next(self._ids)
        self.ident[new] = fid
        found = functions(source)
        if found is None:
            return fid
        before = self.current.get(fid, {})
        for name, fn in found.items():
            if name in before:
                self.history[fid, name].record(before[name], fn)
            else:
                self.history[fid, name] = History(born=session)
        for name in before.keys() - found.keys():
            del self.history[fid, name]
        self.current[fid] = found
        return fid

    def paths(self) -> dict[int, str]:
        return {fid: path for path, fid in self.ident.items()}


def session_boundaries() -> list[str]:
    """The last first-parent commit of each session, oldest first."""
    rows = first_parents("HEAD")
    ids = sessions([time for _, time, _ in rows])
    return [
        sha
        for (sha, _, _), here, following in zip(rows, ids, [*ids[1:], None], strict=True)
        if here != following
    ]


def _changed(prev: str | None, commit: str) -> list[tuple[str, str, str]]:
    """(status, old path, new path) of every file that differs between the two snapshots."""
    if prev is None:
        return [("A", p, p) for p in tree_paths(commit)]
    fields = git("diff-tree", "-r", "-M", "-z", "--name-status", prev, commit).split("\0")[:-1]
    out, i = [], 0
    while i < len(fields):
        status = fields[i][0]
        paths = fields[i + 1 : i + (3 if status in "RC" else 2)]
        out.append((status, paths[0], paths[-1]))
        i += 1 + len(paths)
    return out


def walk(bounds: list[str]) -> Walk:
    state, prev = Walk(), None
    with Blobs() as blobs:
        for session, commit in enumerate(bounds):
            changed = _changed(prev, commit)
            ids = set()
            for status, old, new in changed:
                if not new.endswith(".py") or not new.startswith(ROOTS):
                    continue
                if status == "D":
                    state.delete(old)
                    continue
                ids.add(state.update(session, status, old, new, blobs.text(f"{commit}:{new}")))
            state.touched.append(ids if len(changed) <= _COUPLING_MAX_FILES else set())
            prev = commit
    return state


def _shrunk(changed: int, exposure: int, base: float) -> float:
    return (changed + _PRIOR_SESSIONS * base) / (exposure + _PRIOR_SESSIONS)


def module_name(path: str) -> str:
    parts = PurePosixPath(path.removeprefix("src/")).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported(path: str, tree: ast.Module) -> set[str]:
    """Every dotted name an import in ``path`` may refer to, a module among them."""
    package = module_name(path).split(".")
    if not path.endswith("__init__.py"):
        package.pop()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def coupling(
    touched: Iterable[set[str]], imports: dict[str, set[str]]
) -> list[tuple[str, str, int, int, int, float]]:
    """Pairs changed together in at least 4 sessions with no import either way, most coupled first."""
    sessions = list(touched)
    changes = Counter(path for paths in sessions for path in paths)
    together = Counter(pair for paths in sessions for pair in combinations(sorted(paths), 2))
    rows = [
        (a, b, n, changes[a], changes[b], n / min(changes[a], changes[b]))
        for (a, b), n in together.items()
        if n >= _COUPLING_MIN_SUPPORT
        and module_name(b) not in imports.get(a, set())
        and module_name(a) not in imports.get(b, set())
    ]
    return sorted(rows, key=lambda r: (-r[5], -r[2]))


def _tables(state: Walk, sessions: int, sources: dict[str, str], under: str) -> list[Table]:
    paths = state.paths()
    fns = {
        f"{paths[fid]}::{name}": (h, sessions - 1 - h.born)
        for (fid, name), h in state.history.items()
        if paths[fid].startswith(under)
    }
    exposure = sum(e for _, e in fns.values()) or 1
    base = {
        part: sum(getattr(h, part) for h, _ in fns.values()) / exposure
        for part in ("changed", "body", "signature")
    }
    complexity = {
        f"{path}::{name}": score
        for path, src in sources.items()
        for name, score in cognitive(src).items()
    }

    def ranked(part: str) -> list[tuple[str, int, int, float]]:
        rows: list[tuple[str, int, int, float]] = [
            (key, getattr(h, part), e, _shrunk(getattr(h, part), e, base[part]))
            for key, (h, e) in fns.items()
        ]
        return sorted(rows, key=lambda r: -r[3])

    rate = {key: _shrunk(h.changed, e, base["changed"]) for key, (h, e) in fns.items()}
    hotspots = sorted(
        (
            (key, complexity[key], h.changed, e, rate[key], rate[key] * complexity[key])
            for key, (h, e) in fns.items()
            if complexity.get(key)
        ),
        key=lambda r: -r[5],
    )
    stale = sorted(
        ((key, h.code_only, h.doc, e) for key, (h, e) in fns.items() if h.code_only),
        key=lambda r: (-r[1], r[3]),
    )
    imports = {path: imported(path, ast.parse(src)) for path, src in sources.items()}
    touched = ({paths[fid] for fid in ids if fid in paths} for ids in state.touched)
    pairs = [
        r for r in coupling(touched, imports) if r[0].startswith(under) or r[1].startswith(under)
    ]
    return [
        Table(
            "Hotspots",
            "Change rate x cognitive complexity (complexipy; nested functions score inside their parent).",
            ("function", "complexity", "changed", "exposure", "rate", "score"),
            hotspots,
        ),
        Table(
            "Body churn",
            f"Sessions whose net change touched the body, shrunk rate (base {base['body']:.3f}).",
            ("function", "body", "exposure", "rate"),
            ranked("body"),
        ),
        Table(
            "Signature churn",
            f"Sessions that changed arguments or return type, shrunk rate (base {base['signature']:.3f}).",
            ("function", "signature", "exposure", "rate"),
            ranked("signature"),
        ),
        Table(
            "Docstrings at risk",
            "Sessions that changed the code but kept the docstring; stale docstrings had ~4x more.",
            ("function", "code_only", "doc_edits", "exposure"),
            stale,
        ),
        Table(
            "Change coupling",
            "Changed in the same sessions, no import between them; score = together / min(changes).",
            ("file", "partner", "together", "changes", "partner_changes", "score"),
            pairs,
        ),
    ]


def main(argv: list[str]) -> int:
    parser = report_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--under", default="src/", help="report paths under this prefix (default src/)"
    )
    args = parser.parse_args(argv)
    if git("rev-parse", "--is-shallow-repository").strip() == "true":
        print(
            "churn needs the full history, and this clone is shallow: git fetch --unshallow",
            file=sys.stderr,
        )
        return 2
    bounds = session_boundaries()
    state = walk(bounds)
    with Blobs() as blobs:
        sources = {path: blobs.text(f"{bounds[-1]}:{path}") for path in state.ident}
    print(f"{len(bounds)} sessions, {len(state.history)} functions", file=sys.stderr)
    emit(_tables(state, len(bounds), sources, args.under), args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
