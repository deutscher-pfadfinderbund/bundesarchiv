"""The axe pass (``_axe.py``) over every inventory screen."""

import pytest
from playwright.sync_api import Page
from tests.e2e._axe import axe_findings
from tests.e2e._corpus import CorpusHandles
from tests.e2e._pages import Screen, screens_for

pytestmark = pytest.mark.e2e


def _assert_axe_clean(page: Page, base: str, corpus: CorpusHandles, screen: Screen) -> None:
    screen.reach(page, base, corpus)
    findings = axe_findings(page, screen)
    assert not findings, "axe (WCAG 2.2 AA) violations:\n" + "\n".join(findings)


@pytest.mark.parametrize("screen", screens_for(archivist=True), ids=lambda s: s.name)
def test_axe_archivist_screens(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles, screen: Screen
) -> None:
    _assert_axe_clean(archivist_page, live_workbench, e2e_corpus, screen)


@pytest.mark.parametrize("screen", screens_for(archivist=False), ids=lambda s: s.name)
def test_axe_member_screens(
    public_page: Page, live_workbench: str, e2e_corpus: CorpusHandles, screen: Screen
) -> None:
    _assert_axe_clean(public_page, live_workbench, e2e_corpus, screen)
