"""The declaration probe over every gallery state (``_probe.py``). It reports and never fails on a
finding; ``scripts/css_probe_report.py`` aggregates what it writes.
"""

import pytest
from playwright.sync_api import Browser
from tests.e2e._corpus import CorpusHandles
from tests.e2e._gallery import STATES, GalleryState
from tests.e2e._probe import probe_state

pytestmark = pytest.mark.css_probe


@pytest.mark.parametrize("state", STATES, ids=lambda state: state.name)
def test_probe_state(
    state: GalleryState, browser: Browser, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    written = probe_state(browser, live_workbench, e2e_corpus, state)
    assert all(path.stat().st_size > 0 for path in written)
