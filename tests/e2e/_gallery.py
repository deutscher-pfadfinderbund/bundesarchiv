"""The state gallery (Part #26): render every canonical UI state to a PNG, in both color modes.

A design gate / an owner phone review wants ONE folder of screenshots that always shows the same
states in the same order — not a hand-driven click-through. This module is that: a list of named
``GalleryState``s (a state = how to reach it in a real browser + what to shoot), plus ``render_all``
which drives each one twice (light + dark ``prefers-color-scheme``) and writes ``<name>.<mode>.png``.

It reuses the E2E stack (live server + Postgres index + the cached chromium) so a shot is the REAL
page, byte-for-byte what ships — not a static mock. The GET-renderable states come from THE screen
inventory (``_pages.SCREENS``), shared with the a11y pass and the control-row/overlay walkers, so the
gallery and the guards can never disagree about which screens the app has; the states behind an
INTERACTION (the bulk confirm page, an unfolded card section, a rejected save) are declared here and
reached the way a user reaches them, by driving the affordance.

Entry point: the ``gallery`` marker in ``test_gallery.py`` (``uv run pytest -m gallery -s``); the
PNGs land in ``var/gallery/`` (override with ``BUNDESARCHIV_GALLERY_DIR``).
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from playwright.sync_api import Browser, Page
from tests.e2e._corpus import CorpusHandles
from tests.e2e._pages import SCREENS, Screen

#: The two color modes the design system supports (``:root { color-scheme: light dark }`` +
#: ``light-dark()`` tokens, resolved by ``prefers-color-scheme`` — no JS toggle). Every state is
#: shot once per mode; the mode is forced through the browser context, not a cookie.
MODES: tuple[Literal["light", "dark"], ...] = ("light", "dark")


@dataclass(frozen=True, slots=True)
class GalleryState:
    """One canonical UI state: its file-safe ``name``, a one-line ``what`` (for the manifest), whether
    it needs an ``archivist`` cookie, and a ``reach`` callable that navigates the page to the state
    (a plain goto for GET states; a click-through for the POST-gated confirm surfaces)."""

    name: str
    what: str
    archivist: bool
    reach: Callable[[Page, str, CorpusHandles], None]


def _goto(path: str) -> Callable[[Page, str, CorpusHandles], None]:
    """A reach that just navigates to ``base + path`` and waits for the network to settle."""

    def reach(page: Page, base: str, _corpus: CorpusHandles) -> None:
        page.goto(base + path, wait_until="networkidle")

    return reach


def _screen_state(screen: Screen) -> GalleryState:
    """One inventory screen as a gallery state: a plain navigate to its path."""

    def reach(page: Page, base: str, corpus: CorpusHandles) -> None:
        page.goto(base + screen.path(corpus), wait_until="networkidle")

    return GalleryState(screen.name, screen.what, screen.archivist, reach)


def _reach_rail_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # the filter rail with one facet dropdown open — the dropped overlay panel over the ledger
    page.goto(f"{base}/", wait_until="networkidle")
    page.locator(".filterrail summary", has_text="Bestand").click()


def _reach_header_neu_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # the header's "+ Neu …" create disclosure open (Mock B, owner 2026-08-07) — the floating
    # overlay panel with Neuer Artikel / Neuer Bestand
    page.goto(f"{base}/", wait_until="networkidle")
    page.click("details.menu > summary")


def _reach_bulk(page: Page, base: str, corpus: CorpusHandles) -> None:
    # a URL-seeded selection with the Sammelbearbeitung disclosure EXPANDED (the chooser open) —
    # the collapsed cold state is its own gallery state (workbench-bulk-cold)
    page.goto(
        f"{base}/?auswahl={corpus.published_ulid}&auswahl={corpus.second_ulid}",
        wait_until="networkidle",
    )
    page.click("details.bulk > summary")


def _reach_bulk_confirm(page: Page, base: str, corpus: CorpusHandles) -> None:
    _reach_bulk(page, base, corpus)
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    page.wait_for_load_state("networkidle")


def _reach_edit_folded_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the folded sections OPEN (owner ruling 4): Herkunft + Zugriff unfolded, so the shot shows both
    # the value-carrying summaries and what they hide — including the exposure statement's in-card
    # placement
    page.goto(f"{base}/artikel/{corpus.published_ulid}/bearbeiten", wait_until="networkidle")
    page.click('summary:has-text("Herkunft")')
    page.click('summary:has-text("Zugriff")')


def _reach_edit_rejected(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the REJECTED state of the record card, and specifically an error inside a FOLDED section:
    # Sichtbarkeit=Gruppe(n) with an empty Gruppen field. The server decides [open] from the same error
    # context that renders the message, and the summary carries the red "Fehler" mark — a visible cue
    # needs a render to be judged on (learning G.7), and this shot is also the C13 error-border state.
    page.goto(f"{base}/artikel/{corpus.published_ulid}/bearbeiten", wait_until="networkidle")
    page.click('summary:has-text("Zugriff")')
    page.select_option('select[name="sichtbarkeit"]', "groups")
    page.click('button:has-text("Speichern")')
    page.wait_for_selector(".karte .error")


#: The states that are NOT a plain navigate: each is reached by driving an affordance, so a path
#: cannot describe it and it stays declared here rather than in the screen inventory.
_INTERACTION_STATES: tuple[GalleryState, ...] = (
    GalleryState(
        "workbench-rail-open",
        "workbench, Bestand filter dropdown open on the rail",
        True,
        _reach_rail_open,
    ),
    GalleryState(
        "header-neu-open",
        "workbench, header '+ Neu …' create disclosure open (Mock B overlay panel)",
        True,
        _reach_header_neu_open,
    ),
    GalleryState(
        "workbench-bulk-cold",
        "workbench cold (no selection) — NO Sammelbearbeitung visible (progressive, owner"
        " 2026-08-07: JS hides the disclosure at count 0; that absence is the point of the shot)",
        True,
        _goto("/"),
    ),
    GalleryState(
        "workbench-bulk", "workbench, selection + expanded Sammelbearbeitung", True, _reach_bulk
    ),
    GalleryState(
        "edit-folded-open",
        "the edit surface with Herkunft + Zugriff unfolded",
        True,
        _reach_edit_folded_open,
    ),
    GalleryState(
        "edit-rejected",
        "the edit surface rejected: an error inside a folded section (opened, summary marked)",
        True,
        _reach_edit_rejected,
    ),
    GalleryState("bulk-confirm", "bulk edit, confirm panel", True, _reach_bulk_confirm),
)

#: The canonical states, in a stable order (the gallery is a design contract: same states, same
#: order, every run): every GET-reachable SCREEN from the one inventory (_pages.SCREENS — so a new
#: screen is shot the day it joins it, and the gallery can never disagree with what the guards walk),
#: then the interaction states above.
STATES: tuple[GalleryState, ...] = (
    *(_screen_state(screen) for screen in SCREENS),
    *_INTERACTION_STATES,
)

#: The gallery is rendered at each of these widths (the design-system's desktop + narrow breakpoints,
#: spec §4): 1440 is the split-narrow workbench (pane beside ledger); 680 is under the <1280 query
#: where the pane collapses and the ledger unfolds. Named ``<state>.<mode>.<width>.png``.
WIDTHS: tuple[int, ...] = (1440, 680)


def gallery_dir() -> Path:
    """Where the PNGs land: ``var/gallery/`` at the repo root by default, overridable by env."""
    default = Path(__file__).resolve().parent.parent.parent / "var" / "gallery"
    return Path(os.environ.get("BUNDESARCHIV_GALLERY_DIR") or default)


def render_all(
    browser: Browser,
    base_url: str,
    corpus: CorpusHandles,
    archivist_cookie: dict[str, object],
    out_dir: Path | None = None,
) -> list[Path]:
    """Render every canonical state to ``out_dir`` (default ``gallery_dir()``), at each ``WIDTHS``
    width in both color modes. One full-page PNG per (state, mode, width), named
    ``<state>.<mode>.<width>.png`` (stable so a review brief can reference a shot). Returns the paths.

    Shots are grouped by (mode, width, needs-cookie) so one browser context opens per group — a
    context fixes the color scheme + viewport + cookie — and every same-group state reuses its page
    via a fresh navigate, rather than spinning up a context per shot."""
    out = out_dir if out_dir is not None else gallery_dir()
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for mode in MODES:
        for width in WIDTHS:
            for archivist in (True, False):
                group = [s for s in STATES if s.archivist == archivist]
                if not group:
                    continue
                context = browser.new_context(
                    color_scheme=mode, viewport={"width": width, "height": 900}
                )
                if archivist:
                    context.add_cookies([archivist_cookie])  # type: ignore[list-item]
                page = context.new_page()
                try:
                    for state in group:
                        state.reach(page, base_url, corpus)
                        target = out / f"{state.name}.{mode}.{width}.png"
                        page.screenshot(path=str(target), full_page=True)
                        written.append(target)
                finally:
                    context.close()
    return written
