"""Gallery before/after: render a git ref and the working tree, pixel-diff the two galleries.

Usage: mise run test:gallery-diff [-- REF]      (REF defaults to main)

The ref is checked out into a throwaway worktree under var/ (removed afterwards), both trees render
with `pytest -m gallery`, and every PNG that is changed, new (only in the tree) or missing (only in
the ref) is reported. Exits 1 on any difference.

The ref's render is cached under var/gallery-diff/ref-cache/<commit>-pw<playwright>: a commit renders
the same with the same browser build, so every diff against one main renders it once. Only the
KEEP most recently used renders stay.
"""

import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "var" / "gallery-diff"
CACHE = WORK / "ref-cache"
KEEP = 3


def render(cwd: Path, out: Path) -> None:
    shutil.rmtree(out, ignore_errors=True)
    env = {**os.environ, "BUNDESARCHIV_GALLERY_DIR": str(out)}
    print(f"rendering {cwd} -> {out}", flush=True)
    cmd = ["uv", "run", "pytest", "-m", "gallery", "-s", "-q"]
    subprocess.run(cmd, cwd=cwd, env=env, check=True)  # noqa: S603 — fixed command


def compare(ref: Path, tree: Path) -> int:
    names = sorted({p.name for p in (*ref.glob("*.png"), *tree.glob("*.png"))})
    bad = 0
    for name in names:
        a, b = ref / name, tree / name
        if not a.exists():
            verdict = "new"
        elif not b.exists():
            verdict = "missing"
        else:
            with Image.open(a) as ia, Image.open(b) as ib:
                same = (
                    ia.size == ib.size
                    and ImageChops.difference(ia.convert("RGB"), ib.convert("RGB")).getbbox()
                    is None
                )
            verdict = "identical" if same else "changed"
        bad += verdict != "identical"
        if verdict != "identical":
            print(f"{verdict:9} {name}")
    print(f"{len(names)} PNGs, {bad} differ")
    return int(bad > 0)


def git(*args: str, check: bool = True) -> str:
    done = subprocess.run(  # noqa: S603 — fixed command
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def ref_render(ref: str) -> Path:
    """The ref's gallery, rendered once per commit and browser build."""
    sha = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    cached = CACHE / f"{sha}-pw{importlib.metadata.version('playwright')}"
    if not cached.exists():
        # Named after this checkout: the test database is named after the directory (tests/conftest.py),
        # so two worktrees diffing at once must not share one.
        checkout = WORK / f"checkout-{ROOT.name}"
        git("worktree", "prune")
        git("worktree", "add", "--detach", "--force", str(checkout), sha)
        try:
            render(checkout, WORK / "ref-partial")
        finally:
            git("worktree", "remove", "--force", str(checkout), check=False)
        cached.parent.mkdir(parents=True, exist_ok=True)
        (WORK / "ref-partial").rename(cached)  # only a finished render enters the cache
    else:
        print(f"reusing {cached.name}", flush=True)
    cached.touch()
    for stale in sorted(CACHE.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[KEEP:]:
        shutil.rmtree(stale)
    return cached


def main(argv: list[str]) -> int:
    shutil.rmtree(WORK / "ref", ignore_errors=True)  # the uncached layout's leftover
    ref = ref_render(argv[0] if argv else "main")
    render(ROOT, WORK / "tree")
    return compare(ref, WORK / "tree")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
