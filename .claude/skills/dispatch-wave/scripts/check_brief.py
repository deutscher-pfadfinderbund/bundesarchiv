"""Check a task brief before dispatch: python3 check_brief.py BRIEF.md

Prints one line per finding and exits 1 when there is any:
- a backticked repo path that does not exist (file, directory or glob), resolved against the
  git toplevel; `path::Class::name` and `path::Class.method` also need every name in that file
  (whole word); a bare name (no directory part) may sit beside the brief or match any tracked
  file or directory;
- a line-number anchor (`l.27`, `~l.27`, `line 27`, `file.py:42`);
- a missing fence section or report section (a heading naming each).

Code blocks are skipped. A path the task creates is marked `path` (new) once and then exempt
everywhere in the brief. A token naming a git ref (or a range) is not a path: it is skipped when
the ref resolves, or when it sits on the brief's own "Worktree:" line (the branch not yet made).
"""

import re
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path

EXTENSIONS = "py|md|toml|html|css|js|json|yml|yaml|sh|txt|cfg|ini|lock|sql|svg|png|pdf|ts|csv|env"
TOKEN = re.compile(r"`([^`\n]+)`(\s*\(new\))?")
PATHLIKE = re.compile(rf"^[\w.~*/\-]+(\.({EXTENSIONS})|/[\w.*\-/]*)(::\w+(\.\w+)*)*(:\d+)?$")
LINE_ANCHORS = re.compile(
    r"(?<![\w.])~?l\.\s?\d+|\bline\s+\d+\b|[\w/\-]+\.(?:" + EXTENSIONS + r"):\d+"
)
HEADING = re.compile(r"^\s*(?:#+|\*\*)\s*(.*)$", re.MULTILINE)
WORKTREE_LINE = re.compile(r"^[\s>\-*]*Worktree\b")
RANGE = re.compile(r"\w\.\.\w")


@cache
def git(*args: str) -> str | None:
    """Stdout of a git command, or None when it fails or git is missing."""
    exe = shutil.which("git")
    if exe is None:
        return None
    run = subprocess.run(  # noqa: S603 — fixed arguments
        [exe, *args], capture_output=True, text=True, check=False
    )
    return run.stdout if run.returncode == 0 else None


def root() -> Path:
    top = git("rev-parse", "--show-toplevel")
    return Path(top.strip()) if top else Path.cwd()


def prose(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def matches_of(path: str, brief_dir: Path) -> list[Path]:
    base = root()
    if "*" in path:
        anchor = Path("/") if path.startswith("/") else base
        return list(anchor.glob(path.lstrip("/")))
    candidate = base / Path(path).expanduser()
    if candidate.exists():
        return [candidate]
    if "/" in path:
        return []
    if (brief_dir / path).exists():
        return [brief_dir / path]
    tracked = (git("ls-files") or "").splitlines()
    return [
        base / f for f in tracked if f == path or f.endswith("/" + path) or f"/{path}/" in f"/{f}"
    ]


def is_ref(token: str) -> bool:
    if token.startswith("-"):
        return False
    return (
        bool(RANGE.search(token))
        or git("rev-parse", "--verify", "--quiet", token + "^{commit}") is not None
    )


def split_token(token: str) -> tuple[str, list[str]]:
    """The path of a token and the names it asks for (`::` and `.` separated)."""
    path, *parts = token.split("::")
    names = [name for part in parts for name in part.split(".") if name]
    return re.sub(r":\d+$", "", path).rstrip("/"), names


def check_path(token: str, brief_dir: Path) -> str | None:
    path, names = split_token(token)
    if path.startswith("/") and not Path("/" + path.split("/")[1]).exists():
        return None  # a URL route, not a file
    matches = matches_of(path, brief_dir)
    if not matches:
        return f"missing path: {token}"
    texts = [m.read_text(encoding="utf-8", errors="replace") for m in matches if m.is_file()]
    if names and not any(
        all(re.search(rf"\b{re.escape(name)}\b", text) for name in names) for text in texts
    ):
        return f"symbol not found: {token}"
    return None


def findings(text: str, brief_dir: Path) -> list[str]:
    body = prose(text)
    out = [
        f"line-number anchor: {m.group(0)!r} (anchor on symbol names)"
        for m in LINE_ANCHORS.finditer(body)
    ]
    worktree_line = "".join(line for line in body.splitlines() if WORKTREE_LINE.match(line))
    tokens = TOKEN.findall(body)
    created = {split_token(token)[0] for token, is_new in tokens if is_new}
    for token, _ in tokens:
        if not PATHLIKE.match(token) or split_token(token)[0] in created:
            continue
        if f"`{token}`" in worktree_line or is_ref(token):
            continue
        if finding := check_path(token, brief_dir):
            out.append(finding)
    headings = [h.lower() for h in HEADING.findall(body)]
    out += [
        f"missing section: {name}"
        for name in ("fence", "report")
        if not any(name in h for h in headings)
    ]
    return list(dict.fromkeys(out))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: check_brief.py BRIEF.md\n")
        return 2
    brief = Path(argv[1])
    result = findings(brief.read_text(encoding="utf-8"), brief.resolve().parent)
    sys.stdout.write("".join(f"{line}\n" for line in result))
    return 1 if result else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
