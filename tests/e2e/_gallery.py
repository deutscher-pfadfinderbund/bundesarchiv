"""The state gallery (Part #26): render every canonical UI state to a PNG, in both color modes.

A design gate / an owner phone review wants ONE folder of screenshots that always shows the same
states in the same order — not a hand-driven click-through. This module is that: a list of named
``GalleryState``s (a state = how to reach it in a real browser + what to shoot), plus ``render_all``
which drives each one twice (light + dark ``prefers-color-scheme``) and writes ``<name>.<mode>.png``.

It reuses the E2E stack (live server + Postgres index + the cached chromium) so a shot is the REAL
page, byte-for-byte what ships — not a static mock. GET-renderable states are a plain navigate;
the POST-gated confirm surfaces (bulk-confirm, delete-confirm, publish-preview) are reached the way
a user reaches them, by driving the affordance, so those states appear in the gallery too.

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


def _reach_pane(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/?artikel={corpus.published_ulid}", wait_until="networkidle")


def _reach_bulk(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(
        f"{base}/?auswahl={corpus.published_ulid}&auswahl={corpus.second_ulid}",
        wait_until="networkidle",
    )


def _reach_bulk_confirm(page: Page, base: str, corpus: CorpusHandles) -> None:
    _reach_bulk(page, base, corpus)
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    page.wait_for_load_state("networkidle")


def _reach_delete_confirm(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/artikel/{corpus.draft_ulid}", wait_until="networkidle")
    page.click('a:has-text("Löschen")')
    page.wait_for_load_state("networkidle")


def _reach_publish_preview(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the draft carries a Medienart already (corpus builds it so publish is not validation-blocked)
    page.goto(f"{base}/artikel/{corpus.draft_ulid}/bearbeiten", wait_until="networkidle")
    page.click('button:has-text("Veröffentlichen")')
    page.wait_for_load_state("networkidle")


def _reach_edit(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/artikel/{corpus.draft_ulid}/bearbeiten", wait_until="networkidle")


def _reach_read(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/artikel/{corpus.published_ulid}", wait_until="networkidle")


def _reach_detail_cover(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the published article WITH media — the cover Platte + filmstrip (a member view: no cookie)
    page.goto(f"{base}/artikel/{corpus.published_ulid}", wait_until="networkidle")


def _reach_detail_no_media(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the second published article has no media — the no-media rule (title focal, no empty frame)
    page.goto(f"{base}/artikel/{corpus.second_ulid}", wait_until="networkidle")


def _reach_detail_draft(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the draft — archivist-only: ENTWURF badge + action row (the one amber mark)
    page.goto(f"{base}/artikel/{corpus.draft_ulid}", wait_until="networkidle")


#: The canonical states, in a stable order (the gallery is a design contract: same states, same
#: order, every run). Read-only workbench variants first, then the write surfaces, then the
#: POST-gated confirm panels. ``draft_ulid`` is a saveable draft (Medienart set); ``published_ulid``
#: is the published article the pane/copy/bulk paths reference.
STATES: tuple[GalleryState, ...] = (
    GalleryState("workbench-empty", "workbench, no results", True, _goto("/?q=zzzznomatch")),
    GalleryState("workbench-results", "workbench, the corpus", True, _goto("/")),
    GalleryState(
        "workbench-filtered", "workbench, tag facet applied", True, _goto("/?schlagwort=sommer")
    ),
    GalleryState("workbench-pane", "workbench, preview pane open", True, _reach_pane),
    GalleryState(
        "workbench-bulk-cold",
        "workbench, bulk bar cold start (affordances, no selection)",
        True,
        _goto("/"),
    ),
    GalleryState("workbench-bulk", "workbench, bulk selection bar", True, _reach_bulk),
    GalleryState("workbench-public", "workbench as a public visitor", False, _goto("/")),
    GalleryState("create-form", "the create step", True, _goto("/artikel/neu")),
    GalleryState("edit-form", "the full edit form (a draft)", True, _reach_edit),
    GalleryState("read-published", "the read view (a published article)", True, _reach_read),
    GalleryState(
        "detail-member-cover",
        "detail read view, member, with cover + filmstrip",
        False,
        _reach_detail_cover,
    ),
    GalleryState(
        "detail-no-media",
        "detail read view, member, no media (title focal)",
        False,
        _reach_detail_no_media,
    ),
    GalleryState(
        "detail-archivist-draft",
        "detail read view, archivist draft (ENTWURF + action row)",
        True,
        _reach_detail_draft,
    ),
    GalleryState("bulk-confirm", "bulk edit, confirm panel", True, _reach_bulk_confirm),
    GalleryState("delete-confirm", "delete, confirm page", True, _reach_delete_confirm),
    GalleryState("publish-preview", "publish, over-exposure preview", True, _reach_publish_preview),
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
