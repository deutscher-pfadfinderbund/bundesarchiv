"""Mutation proof: apply one edit to a file, run tests, always restore the file.

Usage: mise run mutate -- FILE OLD NEW PYTEST_ARG [PYTEST_ARG ...]

OLD must occur exactly once in FILE. The verdict is CAUGHT when pytest fails on the mutant and
passes again after the restore; anything else exits non-zero. Leaves no files behind.
"""

import os
import signal
import subprocess
import sys
from pathlib import Path


def pytest(args: list[str]) -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(  # noqa: S603 — the caller's own pytest arguments
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args], env=env, check=False
    ).returncode


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    path, old, new, args = Path(argv[0]), argv[1], argv[2], argv[3:]
    original = path.read_bytes()
    text = original.decode()
    if (hits := text.count(old)) != 1:
        print(f"refused: OLD occurs {hits} times in {path}, not exactly once", file=sys.stderr)
        return 2
    stat = path.stat()
    # SIGTERM becomes SystemExit, so the finally below restores the file on it as on Ctrl-C.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        path.write_bytes(text.replace(old, new).encode())
        # A new mtime, so Python never trusts a .pyc compiled from the original (same size).
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        mutant = pytest(args)
    finally:
        path.write_bytes(original)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    print(f"\nrestored {path}; re-running on the original\n")
    clean = pytest(args)
    if mutant == 1 and clean == 0:
        print("CAUGHT: the mutant failed (red), the original passes (green)")
        return 0
    if mutant == 0:
        print("SURVIVED: the tests pass on the mutant (green) - they do not bite")
        return 1
    if mutant != 1:
        print(f"ERROR: pytest exited {mutant} on the mutant (not a test failure)")
        return 3
    print(f"ERROR: the original fails too (pytest exited {clean}); fix that first")
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
