"""The axe-core WCAG 2.2 AA pass (design-review-law floor) over every inventory screen; axe is
vendored in tests/e2e/vendor/ (MPL-2.0). Rule overrides: ``_RULES``.
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page
from tests.e2e._corpus import CorpusHandles
from tests.e2e._pages import Screen, screens_for

pytestmark = pytest.mark.e2e

_AXE_SOURCE = (Path(__file__).parent / "vendor" / "axe.min.js").read_text()

#: WCAG 2.2 AA and everything it builds on — the ruled floor.
_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

#: ``color-contrast`` OFF by owner ruling (2026-08 test audit; tests/CLAUDE.md). ``target-size`` ON:
#: the vendored axe ships it disabled, and selecting by tag never enables a disabled rule.
#: json.dumps, not repr: Python's True/False are not JavaScript literals.
_RULES = json.dumps({"color-contrast": {"enabled": False}, "target-size": {"enabled": True}})

#: Rules whose "needs review" results count as findings: axe reports a small target crowded by its
#: neighbours as incomplete, not as a violation, and every hit area here comes from one knob chain,
#: so there is nothing for axe to be unsure about.
_INCOMPLETE_COUNTS = frozenset({"target-size"})

_RUN = f"""
() => axe.run(document, {{
  runOnly: {{ type: "tag", values: {_TAGS!r} }},
  rules: {_RULES},
}})
"""


def _report(screen: Screen, kind: str, entries: list[dict[str, object]]) -> list[str]:
    return [
        f"{screen.name}: [{entry['id']}] {kind}: {entry['help']} — "
        + "; ".join(str(node["html"])[:120] for node in list(entry["nodes"])[:3])  # type: ignore[call-overload]
        for entry in entries
    ]


def _check(page: Page, base: str, corpus: CorpusHandles, screen: Screen) -> list[str]:
    screen.reach(page, base, corpus)
    page.evaluate(_AXE_SOURCE)  # not a <script> tag: the page policy refuses inline script
    result = page.evaluate(_RUN)
    findings = _report(screen, "violation", result["violations"])
    incomplete = [e for e in result["incomplete"] if e["id"] in _INCOMPLETE_COUNTS]
    return findings + _report(screen, "needs review", incomplete)


def test_axe_archivist_screens(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    findings = [
        f
        for screen in screens_for(archivist=True)
        for f in _check(archivist_page, live_workbench, e2e_corpus, screen)
    ]
    assert not findings, "axe (WCAG 2.2 AA) violations:\n" + "\n".join(findings)


def test_axe_member_screens(
    public_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    findings = [
        f
        for screen in screens_for(archivist=False)
        for f in _check(public_page, live_workbench, e2e_corpus, screen)
    ]
    assert not findings, "axe (WCAG 2.2 AA) violations:\n" + "\n".join(findings)
