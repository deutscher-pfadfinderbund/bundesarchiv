"""The axe-core pass over the journey pages (rework-wave charter item 6, carried from issue #9).

A11y floor: WCAG 2.2 AA (`docs/design/design-review-law.md`, one-line rulings). Every canonical
screen is loaded in the real browser, the vendored axe-core (tests/e2e/vendor/, MPL-2.0) is
injected, and ANY violation of the WCAG A/AA rule tags fails with the offending nodes listed.

Two rules are configured explicitly, because axe's defaults do not match the ruled floor:
`color-contrast` stays OFF by owner ruling, and `target-size` is turned ON (it ships disabled, so the
"WCAG 2.2 AA pass" performed no target-size check at all). Both are explained at `_RULES` below, with
the reason `target-size` also needs its NEEDS-REVIEW results counted.
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

#: Two rules are set EXPLICITLY, because axe's own defaults do not match the ruled floor:
#:
#: - ``color-contrast`` stays OFF by owner ruling (2026-08 test audit — colors are chosen once in
#:   tokens.css and judged at the design gate; tests/CLAUDE.md forbids color sweeps). The pane's
#:   toolbar buttons are covered instead by a computed role check in test_journeys.
#: - ``target-size`` is turned ON. The vendored axe ships it DISABLED (it is "experimental" there),
#:   and selecting rules by TAG never enables a disabled rule — so the WCAG 2.2 AA pass performed no
#:   target-size check at all, and a 12x12px control passed both it and the AA floor walker in
#:   test_journeys (which only measures controls inside a discovered control ROW, and the pane's ✕ is
#:   in none). It is the one AA success criterion this suite claims and did not run.
#: json.dumps, not repr: Python's True/False are not JavaScript literals.
_RULES = json.dumps({"color-contrast": {"enabled": False}, "target-size": {"enabled": True}})

#: Rules whose INCOMPLETE ("needs review") results count as findings here. Enabling ``target-size``
#: is only half a check: axe returns a too-small target that is also too CLOSE to its neighbours as
#: incomplete rather than as a violation, because in general it cannot decide programmatically — and
#: a check that reads only ``violations`` therefore still cannot fail on the defect the rule exists
#: for (measured: three adjacent media-register icon buttons at 10px with no gap produced four
#: incomplete results and ZERO violations). On our own app a needs-review target size is the finding:
#: every hit area here comes from one knob chain, so there is nothing legitimate for axe to be unsure
#: about, and the clean app reports none.
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
    # The whole archivist surface, DERIVED from the one screen inventory (_pages.SCREENS) rather than
    # re-typed here: this list had drifted from the app, and the drift was invisible — the PUBLISHED
    # record's edit surface is the only screen with MEDIA, so the media register's icon toolbar (icon-
    # only controls, whose accessible names are exactly axe's business) was never loaded by this pass.
    findings = [
        f
        for screen in screens_for(archivist=True)
        for f in _check(archivist_page, live_workbench, e2e_corpus, screen)
    ]
    assert not findings, "axe (WCAG 2.2 AA) violations:\n" + "\n".join(findings)


def test_axe_member_screens(
    public_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The member/public surface: the workbench and the two detail read shapes (cover + no-media).
    findings = [
        f
        for screen in screens_for(archivist=False)
        for f in _check(public_page, live_workbench, e2e_corpus, screen)
    ]
    assert not findings, "axe (WCAG 2.2 AA) violations:\n" + "\n".join(findings)
