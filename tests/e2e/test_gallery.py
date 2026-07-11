"""The state-gallery entry point (Part #26): ``uv run pytest -m gallery -s``.

ONE invocation renders every canonical UI state to a PNG in both color modes — the standard input
for a design gate and an owner phone review. It is a pytest test (not a management command) so it
reuses the E2E stack verbatim: the isolated per-run corpus, the live server + real Postgres index,
and the cached chromium — a real page, never a mock, and never the production database.

Marked ``gallery`` (its own marker, like ``e2e``): excluded from the default run, so the fast gate
never spends a browser render. The ``-s`` flag surfaces the "wrote N PNGs to ..." line.
"""

import pytest
from playwright.sync_api import Browser
from tests.e2e._corpus import CorpusHandles
from tests.e2e._gallery import MODES, STATES, WIDTHS, gallery_dir, render_all

pytestmark = pytest.mark.gallery


def test_render_state_gallery(
    browser: Browser, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    from tests.e2e.conftest import _archivist_cookie

    written = render_all(
        browser,
        live_workbench,
        e2e_corpus,
        _archivist_cookie(live_workbench),
    )
    # every state shot in both modes at every width, nothing empty
    assert len(written) == len(STATES) * len(MODES) * len(WIDTHS)
    assert all(p.exists() and p.stat().st_size > 0 for p in written)
    print(f"\nwrote {len(written)} PNGs to {gallery_dir()}")  # the gallery's -s receipt
