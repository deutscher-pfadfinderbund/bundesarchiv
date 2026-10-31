"""The axe-core WCAG 2.2 AA pass (design-review-law floor); axe is vendored in tests/e2e/vendor/
(MPL-2.0).
"""

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page
from tests.e2e._pages import Screen

_AXE_SOURCE = (Path(__file__).parent / "vendor" / "axe.min.js").read_text()

#: WCAG 2.2 AA and everything it builds on — the ruled floor.
_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

#: ``color-contrast`` OFF by owner ruling (2026-08 test audit; tests/CLAUDE.md). ``target-size`` ON:
#: the vendored axe ships it disabled, and selecting by tag never enables a disabled rule.
#: json.dumps, not repr: Python's True/False are not JavaScript literals.
_RULES = json.dumps({"color-contrast": {"enabled": False}, "target-size": {"enabled": True}})

#: axe reports a small target crowded by its neighbours as incomplete, not as a violation, and every
#: hit area here comes from one knob chain, so there is nothing for axe to be unsure about.
_INCOMPLETE_COUNTS = frozenset({"target-size"})

_RUN = f"""
() => axe.run(document, {{
  runOnly: {{ type: "tag", values: {_TAGS!r} }},
  rules: {_RULES},
}})
"""


def _report(where: str, kind: str, entries: list[dict[str, Any]]) -> list[str]:
    return [
        f"{where}: [{entry['id']}] {kind}: {entry['help']} — "
        + "; ".join(str(node["html"])[:120] for node in list(entry["nodes"])[:3])
        for entry in entries
    ]


def axe_findings(page: Page, screen: Screen) -> list[str]:
    page.evaluate(_AXE_SOURCE)  # not a <script> tag: the page policy refuses inline script
    result = page.evaluate(_RUN)
    findings = _report(screen.name, "violation", result["violations"])
    incomplete = [e for e in result["incomplete"] if e["id"] in _INCOMPLETE_COUNTS]
    return findings + _report(screen.name, "needs review", incomplete)
