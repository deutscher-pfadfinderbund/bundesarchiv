"""The axe-core pass over the journey pages (rework-wave charter item 6, carried from issue #9).

A11y floor: WCAG 2.2 AA (`docs/design/design-review-law.md`, one-line rulings). Every canonical
screen is loaded in the real browser, the vendored axe-core (tests/e2e/vendor/, MPL-2.0) is
injected, and ANY violation of the WCAG A/AA rule tags fails with the offending nodes listed.

The `color-contrast` rule is deliberately disabled: automated contrast testing was removed by
owner ruling (2026-08 test audit — colors are chosen once in tokens.css and judged at the design
gate; tests/CLAUDE.md forbids color sweeps). Everything else — names/roles, labels, landmarks,
list/table semantics, aria validity — runs.
"""

from pathlib import Path

import pytest
from playwright.sync_api import Page
from tests.e2e._corpus import CorpusHandles

pytestmark = pytest.mark.e2e

_AXE_SOURCE = (Path(__file__).parent / "vendor" / "axe.min.js").read_text()

#: WCAG 2.2 AA and everything it builds on — the ruled floor.
_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

_RUN = f"""
() => axe.run(document, {{
  runOnly: {{ type: "tag", values: {_TAGS!r} }},
  rules: {{ "color-contrast": {{ enabled: false }} }},
}})
"""


def _check(page: Page, base: str, path: str) -> list[str]:
    page.goto(base + path, wait_until="networkidle")
    page.add_script_tag(content=_AXE_SOURCE)
    result = page.evaluate(_RUN)
    return [
        f"{path}: [{v['id']}] {v['help']} — "
        + "; ".join(node["html"][:120] for node in v["nodes"][:3])
        for v in result["violations"]
    ]


def test_axe_archivist_screens(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The archivist journey surface: workbench (results / pane open / bulk selection), the create
    # + edit forms, the delete confirm, the archivist draft read view, the Bestand forms.
    paths = (
        "/",
        "/?schlagwort=sommer",  # active filter: the rail chip + its labeled remove link
        f"/?artikel={e2e_corpus.published_ulid}",
        f"/?auswahl={e2e_corpus.published_ulid}&auswahl={e2e_corpus.second_ulid}",
        "/artikel/neu",
        f"/artikel/{e2e_corpus.draft_ulid}/bearbeiten",
        f"/artikel/{e2e_corpus.draft_ulid}/loeschen",
        f"/artikel/{e2e_corpus.draft_ulid}",
        "/bestand/neu",
        f"/bestand/{e2e_corpus.renamable_ulid}/bearbeiten",
    )
    findings = [f for path in paths for f in _check(archivist_page, live_workbench, path)]
    assert not findings, "axe (WCAG 2.2 AA) violations:\n" + "\n".join(findings)


def test_axe_member_screens(
    public_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The member/public surface: the workbench and the two detail read shapes (cover + no-media).
    paths = (
        "/",
        f"/artikel/{e2e_corpus.published_ulid}",
        f"/artikel/{e2e_corpus.second_ulid}",
    )
    findings = [f for path in paths for f in _check(public_page, live_workbench, path)]
    assert not findings, "axe (WCAG 2.2 AA) violations:\n" + "\n".join(findings)
