"""Gallery before/after: render a git ref and the working tree, pixel-diff the two galleries.

Usage: mise run test:gallery-diff [-- REF]      (REF defaults to main)

The ref is checked out into a throwaway worktree under var/ (removed afterwards), both trees render
with `pytest -m gallery` into var/gallery-diff/{ref,tree}, and every PNG is reported identical,
changed, new (only in the tree) or missing (only in the ref). Exits 1 on any difference.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "var" / "gallery-diff"


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
        print(f"{verdict:9} {name}")
    print(f"{len(names)} PNGs, {bad} differ")
    return int(bad > 0)


def git(*args: str, check: bool = True) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=check)  # noqa: S603, S607 — fixed command


def main(argv: list[str]) -> int:
    checkout = WORK / "checkout"
    git("worktree", "prune")
    git("worktree", "add", "--detach", "--force", str(checkout), argv[0] if argv else "main")
    try:
        render(checkout, WORK / "ref")
    finally:
        git("worktree", "remove", "--force", str(checkout), check=False)
    render(ROOT, WORK / "tree")
    return compare(WORK / "ref", WORK / "tree")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
