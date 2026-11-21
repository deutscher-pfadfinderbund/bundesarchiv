"""Aggregate the declaration probe: the stylesheet declarations that change no computed value in
any gallery state, and those in rules no state activates (design-review-law C18).

Usage: mise run test:css-probe      (runs the probe, then this report)

Report only: exits 0. A declaration is effective if any pass found it effective, else inert if
any pass found it inert, else unmatched.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANK = {"effective": 3, "inert": 2, "unmatched": 1, "unprobeable": 0}


def main() -> int:
    out = Path(os.environ.get("BUNDESARCHIV_CSS_PROBE_DIR") or ROOT / "var" / "css-probe")
    files = sorted(out.glob("*.json"))
    best: dict[tuple[str, str, str], str] = {}
    for path in files:
        passes: dict[str, list[list[str]]] = json.loads(path.read_text())
        for rows in passes.values():
            for file, selector, declaration, found in rows:
                if not declaration.partition(":")[2].strip():
                    continue  # a longhand of `font: var(...)` serializes without a value
                key = (file, selector, declaration)
                status = "inert" if found.startswith("inert") else found
                if RANK[status] > RANK.get(best.get(key, ""), -1):
                    best[key] = status
    counts = {status: sum(1 for s in best.values() if s == status) for status in RANK}
    print(f"{len(files)} page-states, {len(best)} declarations: {counts}")
    for status in ("inert", "unmatched"):
        print(f"\n{status}:")
        for (file, selector, declaration), found in best.items():
            if found == status:
                print(f"  {file} | {selector} | {declaration}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
