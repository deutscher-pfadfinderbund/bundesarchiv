"""The state gallery (Part #26): render every canonical UI state to a PNG, in both color modes.

A design gate / an owner phone review wants ONE folder of screenshots that always shows the same
states in the same order — not a hand-driven click-through. This module is that: a list of named
``GalleryState``s (a state = how to reach it in a real browser + what to shoot), plus ``render_state``
which drives one state in both color modes and each width (``prefers-color-scheme``) and writes ``<name>.<mode>.png``.

It reuses the E2E stack (live server + Postgres index + the cached chromium) so a shot is the REAL
page, byte-for-byte what ships — not a static mock. The GET-renderable states come from THE screen
inventory (``_pages.SCREENS``), shared with the a11y pass and the control-row/overlay walkers, so the
gallery and the guards can never disagree about which screens the app has; the states behind an
INTERACTION — an open menu, a rejected save — are declared here and reached the way a user
reaches them, by driving the affordance. A whole SCREEN that needs driving (the two bulk surfaces)
belongs in the inventory instead, with its own reach, so every guard covers it too.

Entry point: the ``gallery`` marker in ``test_gallery.py`` (``mise run test:gallery``); the
PNGs land in ``var/gallery/`` (override with ``BUNDESARCHIV_GALLERY_DIR``).
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from django.template.loader import render_to_string
from playwright.sync_api import Browser, Page
from tests.e2e._corpus import CorpusHandles
from tests.e2e._pages import LIST, SCREENS, Screen, reach_schlagwort_suggestions

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
    """One inventory screen as a gallery state — the screen already carries HOW to reach it."""
    return GalleryState(screen.name, screen.what, screen.archivist, screen.reach)


def _reach_slot_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # the search sentence with its Bestand slot open: the menu with its counts over the ledger
    page.goto(f"{base}/articles", wait_until="networkidle")
    page.locator(".search-sentence-slots .menu-button").first.click()


def _reach_plus_filter_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # the search sentence with "+ Filter" open: the secondary filters as a check list; on S,
    # "Filter", which also holds the folded slots
    page.goto(f"{base}/articles", wait_until="networkidle")
    triggers = page.locator(":is(.search-sentence-add, .search-sentence-more) .menu-button")
    triggers.filter(visible=True).click()


def _reach_header_neu_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # the header's "+ Neu …" create menu open (Mock B, owner 2026-08-07) — the floating
    # overlay panel with "Neuer Artikel …" / "Neuer Bestand …"
    page.goto(f"{base}/articles", wait_until="networkidle")
    page.click(".menu-button")


def _reach_header_panel(page: Page, base: str, path: str, entry: str) -> None:
    page.goto(f"{base}{path}", wait_until="networkidle")
    page.click("header .menu-button")
    page.get_by_role("button", name=entry).click()


def _reach_neu_artikel_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    _reach_header_panel(page, base, LIST, "Neuer Artikel …")


def _reach_neu_bestand_refused(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # Anlegen with a blank Name: htmx answers in the panel itself, the error under the field. Spaces,
    # because the browser's `required` stops an empty Name before the server sees it.
    _reach_header_panel(page, base, LIST, "Neuer Bestand …")
    page.locator("#neu-bestand-name").fill("   ")
    page.locator("#neu-bestand").get_by_role("button", name="Anlegen").click()
    page.wait_for_selector("#neu-bestand .error")


def _reach_bestand_bearbeiten_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}{LIST}?bestand={corpus.renamable_ulid}", wait_until="networkidle")
    page.get_by_role("button", name="Bestand bearbeiten …").click()


def _reach_spalten_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # the list's "Spalten …" check list open (ruling 2026-09-29: five columns, kept in a cookie)
    page.goto(f"{base}/articles", wait_until="networkidle")
    page.get_by_role("button", name="Spalten …").click()


def _reach_auswahl(page: Page, base: str, corpus: CorpusHandles) -> None:
    # a URL-seeded selection: the tool row shows the count and its tools
    page.goto(
        f"{base}{LIST}?auswahl={corpus.published_ulid}&auswahl={corpus.second_ulid}",
        wait_until="networkidle",
    )


def _reach_bulk(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the same selection with "Feld ändern …" open (the chooser in its toolpanel)
    _reach_auswahl(page, base, corpus)
    page.click('[popovertarget="feld-aendern"]')


def _reach_csrf_refused(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # a form posted with a token that no longer matches: the "form expired" page
    page.goto(f"{base}/collections/new", wait_until="networkidle")
    page.locator('main input[name="csrfmiddlewaretoken"]').evaluate("e => e.value = 'x'.repeat(64)")
    page.locator('main input[name="name"]').fill("Abgelaufen")
    page.locator("main form").get_by_role("button", name="Anlegen").click()
    page.wait_for_load_state("networkidle")


def _reach_server_error(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # no route fails on purpose: the page as Django's 500 handler renders it (no context), on the
    # app's origin so its stylesheets load
    page.goto(f"{base}/articles", wait_until="networkidle")
    page.set_content(render_to_string("500.html"), wait_until="networkidle")


def _reach_not_found(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # a path nothing answers: the same page every deny gets
    page.goto(f"{base}/gibt-es-nicht", wait_until="networkidle")


def _reach_edit_mehr_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.draft_ulid}/edit", wait_until="networkidle")
    page.click(".record-meta .menu-button")


def _reach_edit_loeschen_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    _reach_edit_mehr_open(page, base, corpus)
    page.click('[popovertarget="loeschen"]')


def _reach_detail_aktionen_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.published_ulid}", wait_until="networkidle")
    page.click(".split-button .menu-button")


def _reach_detail_loeschen_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.published_ulid}", wait_until="networkidle")
    page.click(".split-button .menu-button")
    page.click('[popovertarget="loeschen"]')


def _reach_detail_veroeffentlichen_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.draft_ulid}", wait_until="networkidle")
    page.click('button:has-text("Veröffentlichen")')


def _reach_detail_in_trash_confirm_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.marked_ulid}", wait_until="networkidle")
    page.click('[popovertarget="endgueltig-loeschen"]')


def _reach_trash_emptied(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # "Endgültig löschen …" on the one record, confirmed: the Papierkorb it lands on, empty. Every
    # shot of the state reaches it again on the same corpus, so only the first one deletes.
    page.goto(f"{base}/trash", wait_until="networkidle")
    delete = page.locator("main a", has_text="Endgültig löschen …")
    if delete.count():
        delete.click()
        page.locator("main form button[type=submit]").click()
        page.wait_for_url("**/trash")


def _reach_edit_datierung_help(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.draft_ulid}/edit", wait_until="networkidle")
    page.click("#feld-date-hinweis .help")


def _reach_edit_rejected(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the REJECTED state of the edit form: Sichtbarkeit=Gruppe(n) with an empty Gruppen field, the
    # error in the margin — a visible cue needs a render to be judged on (learning G.7), and this shot
    # is also the C13 error-border state.
    page.goto(f"{base}/articles/{corpus.published_ulid}/edit", wait_until="networkidle")
    page.select_option('main select[name="sichtbarkeit"]', "groups")
    page.click('main button:has-text("Speichern")')
    page.wait_for_selector(".record-meta .error")


def _reach_edit_weitere_angaben(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the corpus holds no custom row; "+ Angabe hinzufügen" re-renders one without saving
    page.goto(f"{base}/articles/{corpus.published_ulid}/edit", wait_until="networkidle")
    page.click('button:has-text("+ Angabe hinzufügen")')
    page.fill('#custom-bag input[name="custom_key"]', "Legacy-ID")
    page.fill('#custom-bag input[name="custom_value"]', "1293")


def _reach_edit_conflict(page: Page, base: str, corpus: CorpusHandles) -> None:
    # "Inzwischen geändert": a second tab saves the record unchanged (a version bump only, so every
    # other state keeps its content), then this tab's typed edits lose the CAS race
    page.goto(f"{base}/articles/{corpus.published_ulid}/edit", wait_until="networkidle")
    other = page.context.new_page()
    try:
        other.goto(page.url, wait_until="networkidle")
        other.click('main button:has-text("Speichern")')
        other.wait_for_url(lambda url: "/edit" not in url)
    finally:
        other.close()
    page.fill('input[name="date"]', "1962~")
    page.fill('textarea[name="body"]', "Fahrtenbericht mit Liedern.")
    page.click('main button:has-text("Speichern")')
    page.wait_for_selector(".conflict-notice")
    # the fills scrolled the page, and the sticky margin would be shot mid-page
    page.evaluate("window.scrollTo(0, 0)")


def _reach_bulk_confirm_error(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the confirm surface's ERROR mode: a blank Medienart re-renders the chooser under the verbatim
    # message, which must show exactly one "Neuer Wert" widget
    page.goto(
        f"{base}{LIST}?auswahl={corpus.published_ulid}&auswahl={corpus.second_ulid}",
        wait_until="networkidle",
    )
    page.click('[popovertarget="feld-aendern"]')
    page.select_option('select[name="feld"]', "media_type")
    page.select_option('select[name="wert_media_type"]', "")
    page.click('button:has-text("Änderung prüfen")')
    page.wait_for_selector(".column .error")


#: The states that are not SCREENS but STATES OF one — a menu opened, a save rejected. A screen that
#: merely needs driving to reach (the two bulk surfaces) belongs in the inventory with its own reach,
#: so the guards cover it too; only a second state of a screen already in the inventory lives here.
_INTERACTION_STATES: tuple[GalleryState, ...] = (
    GalleryState(
        "workbench-slot-open",
        "workbench, the search sentence's Bestand slot open",
        True,
        _reach_slot_open,
    ),
    GalleryState(
        "workbench-filter-open",
        "workbench, the search sentence's '+ Filter' open (on S: 'Filter')",
        True,
        _reach_plus_filter_open,
    ),
    GalleryState(
        "header-neu-open",
        "workbench, header '+ Neu …' create menu open (Mock B popover)",
        True,
        _reach_header_neu_open,
    ),
    GalleryState(
        "workbench-spalten-open",
        "workbench, the 'Spalten …' check list open at the tool row's end edge",
        True,
        _reach_spalten_open,
    ),
    GalleryState(
        "workbench-bulk-cold",
        "workbench cold (no selection mode): 'Auswählen' at the tool row's start, no checkbox"
        " column, so the titles align with the sentence",
        True,
        _goto(LIST),
    ),
    GalleryState(
        "workbench-waehlen",
        "workbench in selection mode, nothing ticked: 'Abbrechen', 'Feld ändern …' and the"
        " checkbox column with its select-all head",
        True,
        _goto(f"{LIST}?auswahl="),
    ),
    GalleryState(
        "workbench-auswahl",
        "workbench, two rows picked: 'Abbrechen', the count and 'Feld ändern …' at the tool row's"
        " start",
        True,
        _reach_auswahl,
    ),
    GalleryState(
        "workbench-bulk", "workbench, selection + 'Feld ändern …' open", True, _reach_bulk
    ),
    GalleryState(
        "bulk-confirm-error",
        "bulk edit, confirm surface rejected: the chooser re-rendered under the message",
        True,
        _reach_bulk_confirm_error,
    ),
    GalleryState(
        "edit-mehr-open",
        "the edit surface, the margin's 'Mehr …' menu open (a draft)",
        True,
        _reach_edit_mehr_open,
    ),
    GalleryState(
        "edit-loeschen-open",
        "the edit surface, a draft's Löschen confirm open from 'Mehr …' (the margin's own panel)",
        True,
        _reach_edit_loeschen_open,
    ),
    GalleryState(
        "neu-artikel-open",
        "the header's 'Neuer Artikel …' panel open from '+ Neu …' (Titel and Bestand)",
        True,
        _reach_neu_artikel_open,
    ),
    GalleryState(
        "neu-bestand-refused",
        "the header's 'Neuer Bestand …' panel after Anlegen without a Name: the error in place",
        True,
        _reach_neu_bestand_refused,
    ),
    GalleryState(
        "bestand-bearbeiten-open",
        "the list scoped to one Bestand, its 'Bestand bearbeiten …' panel open (the rename)",
        True,
        _reach_bestand_bearbeiten_open,
    ),
    GalleryState(
        "detail-aktionen-open",
        "the article page, the split button's menu open (Duplizieren, Löschen)",
        True,
        _reach_detail_aktionen_open,
    ),
    GalleryState(
        "detail-loeschen-open",
        "the article page, the delete confirm open from the menu (what goes, the one red button)",
        True,
        _reach_detail_loeschen_open,
    ),
    GalleryState(
        "detail-veroeffentlichen-open",
        "the article page, a draft's Veröffentlichen confirmation open (who will see it)",
        True,
        _reach_detail_veroeffentlichen_open,
    ),
    GalleryState(
        "detail-in-trash-confirm-open",
        "the article page of a record in the Papierkorb, its Endgültig löschen confirm open (red)",
        True,
        _reach_detail_in_trash_confirm_open,
    ),
    GalleryState(
        "trash-emptied",
        "the Papierkorb after Endgültig löschen: where it lands, now empty",
        True,
        _reach_trash_emptied,
    ),
    GalleryState(
        "edit-datierung-help",
        "the edit surface, the Datierung hint's ⓘ popover open (the notation list)",
        True,
        _reach_edit_datierung_help,
    ),
    GalleryState(
        "edit-schlagwort-suggestions",
        "the edit surface, the Schlagworte field suggesting for the line being typed",
        True,
        reach_schlagwort_suggestions,
    ),
    GalleryState(
        "edit-rejected",
        "the edit surface rejected: a Gruppen error in the margin",
        True,
        _reach_edit_rejected,
    ),
    GalleryState(
        "edit-conflict",
        "the edit surface after a lost CAS race: the notice in the margin, each changed field marked",
        True,
        _reach_edit_conflict,
    ),
    GalleryState(
        "edit-weitere-angaben",
        "the edit surface, one Weitere Angaben row added and filled (unsaved)",
        True,
        _reach_edit_weitere_angaben,
    ),
    GalleryState(
        "csrf-refused",
        "a form posted with a stale token: the 'form expired' page (403)",
        True,
        _reach_csrf_refused,
    ),
    GalleryState("server-error", "the server error page (500)", True, _reach_server_error),
    GalleryState(
        "not-found", "the 404 page, shared by every deny and unmatched path", True, _reach_not_found
    ),
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


def render_state(
    browser: Browser,
    base_url: str,
    corpus: CorpusHandles,
    archivist_cookie: dict[str, object],
    state: GalleryState,
    out_dir: Path | None = None,
) -> list[Path]:
    """Render one state to ``out_dir`` (default ``gallery_dir()``), at each ``WIDTHS`` width in both
    color modes. One full-page PNG per (mode, width), named ``<state>.<mode>.<width>.png`` (stable
    so a review brief can reference a shot). Returns the paths.

    A context fixes the color scheme + viewport + cookie, so each shot gets its own; a reach that
    raises fails this state alone (the context is closed either way)."""
    out = out_dir if out_dir is not None else gallery_dir()
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for mode in MODES:
        for width in WIDTHS:
            context = browser.new_context(
                color_scheme=mode, viewport={"width": width, "height": 900}
            )
            try:
                if state.archivist:
                    context.add_cookies([archivist_cookie])  # type: ignore[list-item]
                page = context.new_page()
                state.reach(page, base_url, corpus)
                target = out / f"{state.name}.{mode}.{width}.png"
                page.screenshot(path=str(target), full_page=True)
                written.append(target)
            finally:
                context.close()
    return written
