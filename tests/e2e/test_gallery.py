"""Runs under pytest so it reuses the E2E stack: live server, real index, never the production
database.
"""

import pytest
from playwright.sync_api import Browser
from tests.e2e._corpus import CorpusHandles
from tests.e2e._gallery import MODES, STATES, GalleryState, gallery_dir, render_state

pytestmark = pytest.mark.gallery


@pytest.mark.parametrize("state", STATES, ids=lambda state: state.name)
def test_render_state(
    state: GalleryState, browser: Browser, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    written = render_state(browser, live_workbench, e2e_corpus, state)
    assert len(written) == len(MODES) * len(state.widths)
    assert all(p.exists() and p.stat().st_size > 0 for p in written)
    print(f"\nwrote {len(written)} PNGs for {state.name} to {gallery_dir()}")
