"""The state gallery: every inventory screen plus the interaction states declared here, shot per mode
and width to ``var/gallery/<state>.<mode>.<width>.png`` (``BUNDESARCHIV_GALLERY_DIR`` overrides).
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from django.template.loader import render_to_string
from playwright.sync_api import Browser, Page
from tests.e2e._corpus import TEMPLATE_ULID, CorpusHandles
from tests.e2e._pages import LIST, SCREENS, Screen, reach_tag_suggestions

#: Shot under the emulated ``prefers-color-scheme``, with no theme cookie.
MODES: tuple[Literal["light", "dark"], ...] = ("light", "dark")


@dataclass(frozen=True, slots=True)
class GalleryState:
    name: str
    what: str
    archivist: bool
    reach: Callable[[Page, str, CorpusHandles], None]
    full_page: bool = (
        True  # False for a full-viewport overlay: the shot is the viewport, not the page
    )


def _goto(path: str) -> Callable[[Page, str, CorpusHandles], None]:
    """A reach that just navigates to ``base + path`` and waits for the network to settle."""

    def reach(page: Page, base: str, _corpus: CorpusHandles) -> None:
        page.goto(base + path, wait_until="networkidle")

    return reach


def _screen_state(screen: Screen) -> GalleryState:
    """One inventory screen as a gallery state — the screen already carries HOW to reach it."""
    return GalleryState(screen.name, screen.what, screen.archivist, screen.reach)


def _reach_slot_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles", wait_until="networkidle")
    page.locator(".search-sentence-slots .menu-button").first.click()


def _reach_plus_filter_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # on S the trigger is "Filter"; click whichever is visible
    page.goto(f"{base}/articles", wait_until="networkidle")
    triggers = page.locator(":is(.search-sentence-add, .search-sentence-more) .menu-button")
    triggers.filter(visible=True).click()


def _reach_header_new_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles", wait_until="networkidle")
    page.click(".menu-button")


def _reach_header_panel(page: Page, base: str, path: str, entry: str) -> None:
    page.goto(f"{base}{path}", wait_until="networkidle")
    page.click("header .menu-button")
    page.get_by_role("button", name=entry).click()


def _reach_new_article_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    _reach_header_panel(page, base, LIST, "Neuer Artikel …")


def _reach_new_collection_refused(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # Spaces: the browser's `required` stops an empty Name before the server sees it.
    _reach_header_panel(page, base, LIST, "Neuer Bestand …")
    page.locator("#new-collection-name").fill("   ")
    page.locator("#new-collection").get_by_role("button", name="Anlegen").click()
    page.wait_for_selector("#new-collection .error")


def _reach_collection_edit_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}{LIST}?collection={corpus.renamable_ulid}", wait_until="networkidle")
    page.get_by_role("button", name="Bestand bearbeiten …").click()


def _reach_columns_open(page: Page, base: str, _corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles", wait_until="networkidle")
    page.get_by_role("button", name="Spalten …").click()


def _reach_selection(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(
        f"{base}{LIST}?selection={corpus.published_ulid}&selection={corpus.second_ulid}",
        wait_until="networkidle",
    )


def _reach_bulk(page: Page, base: str, corpus: CorpusHandles) -> None:
    _reach_selection(page, base, corpus)
    page.click('[popovertarget="field-change"]')


def _reach_csrf_refused(page: Page, base: str, _corpus: CorpusHandles) -> None:
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
    page.goto(f"{base}/gibt-es-nicht", wait_until="networkidle")


def _reach_edit_more_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.draft_ulid}/edit", wait_until="networkidle")
    page.click(".record-meta .menu-button")


def _reach_edit_delete_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    _reach_edit_more_open(page, base, corpus)
    page.click('[popovertarget="delete"]')


def _reach_detail_actions_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.published_ulid}", wait_until="networkidle")
    page.click(".split-button .menu-button")


def _reach_detail_delete_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.published_ulid}", wait_until="networkidle")
    page.click(".split-button .menu-button")
    page.click('[popovertarget="delete"]')


def _reach_detail_publish_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.draft_ulid}", wait_until="networkidle")
    page.click('button:has-text("Veröffentlichen")')


def _reach_detail_template_actions_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.template_ulid}", wait_until="networkidle")
    page.click(".split-button .menu-button")


def _reach_edit_template_refused(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.draft_ulid}/edit", wait_until="networkidle")
    page.check('main input[name="template"]')
    page.select_option('main select[name="lifecycle"]', "published")
    page.click('main button:has-text("Speichern")')
    page.locator("#field-template-error").wait_for()


def _reach_detail_in_trash_confirm_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.marked_ulid}", wait_until="networkidle")
    page.click('[popovertarget="delete-permanently"]')


def _reach_detail_lightbox_open(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.many_ulid}", wait_until="networkidle")
    page.locator(".media-rows a").nth(2).click()
    page.locator(".lightbox").wait_for(state="visible")
    # the shown picture is the fourth: cover, then the third row tile
    page.wait_for_function(
        "() => document.querySelectorAll('.lightbox-strip img')[3].naturalWidth > 0"
    )
    page.evaluate("() => Promise.all(document.getAnimations().map((a) => a.finished))")


def _reach_trash_emptied(page: Page, base: str, _corpus: CorpusHandles) -> None:
    # Each width reaches this again on the same corpus, so only the first reach deletes.
    page.goto(f"{base}/trash", wait_until="networkidle")
    delete = page.locator("main a", has_text="Endgültig löschen …")
    if delete.count():
        delete.click()
        page.locator("main form button[type=submit]").click()
        page.wait_for_url("**/trash")


def _reach_edit_date_help(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(f"{base}/articles/{corpus.draft_ulid}/edit", wait_until="networkidle")
    page.click("#field-date-hint .help")


def _reach_edit_rejected(page: Page, base: str, corpus: CorpusHandles) -> None:
    # Gruppe(n) with no Gruppen; also the C13 error-border shot.
    page.goto(f"{base}/articles/{corpus.published_ulid}/edit", wait_until="networkidle")
    page.select_option('main select[name="audience"]', "groups")
    page.click('main button:has-text("Speichern")')
    page.wait_for_selector(".record-meta .error")


def _reach_edit_more_details(page: Page, base: str, corpus: CorpusHandles) -> None:
    # the published record holds no custom row
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
    page.goto(
        f"{base}{LIST}?selection={corpus.published_ulid}&selection={corpus.second_ulid}",
        wait_until="networkidle",
    )
    page.click('[popovertarget="field-change"]')
    page.select_option('select[name="field"]', "media_type")
    page.select_option('select[name="value_media_type"]', "")
    page.click('button:has-text("Änderung prüfen")')
    page.wait_for_selector(".column .error")


#: Second states of an inventory screen: a menu opened, a save rejected. A whole screen belongs in
#: _pages.SCREENS.
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
        "header-new-open",
        "workbench, header '+ Neu …' create menu open (Mock B popover)",
        True,
        _reach_header_new_open,
    ),
    GalleryState(
        "workbench-columns-open",
        "workbench, the 'Spalten …' check list open at the tool row's end edge",
        True,
        _reach_columns_open,
    ),
    GalleryState(
        "workbench-bulk-cold",
        "workbench cold (no selection mode): 'Auswählen' at the tool row's start, no checkbox"
        " column, so the titles align with the sentence",
        True,
        _goto(LIST),
    ),
    GalleryState(
        "workbench-selecting",
        "workbench in selection mode, nothing ticked: 'Abbrechen', 'Feld ändern …' and the"
        " checkbox column with its select-all head",
        True,
        _goto(f"{LIST}?selection="),
    ),
    GalleryState(
        "workbench-selection",
        "workbench, two rows picked: 'Abbrechen', the count and 'Feld ändern …' at the tool row's"
        " start",
        True,
        _reach_selection,
    ),
    GalleryState(
        "workbench-bulk", "workbench, selection + 'Feld ändern …' open", True, _reach_bulk
    ),
    GalleryState(
        "workbench-templates",
        "workbench filtered to the Vorlagen: the removable chip, no Vorlage mark on the rows",
        True,
        _goto(f"{LIST}?templates=1"),
    ),
    GalleryState(
        "bulk-confirm-error",
        "bulk edit, confirm surface rejected: the chooser re-rendered under the message",
        True,
        _reach_bulk_confirm_error,
    ),
    GalleryState(
        "edit-more-open",
        "the edit surface, the margin's 'Mehr …' menu open (a draft)",
        True,
        _reach_edit_more_open,
    ),
    GalleryState(
        "edit-delete-open",
        "the edit surface, a draft's Löschen confirm open from 'Mehr …' (the margin's own panel)",
        True,
        _reach_edit_delete_open,
    ),
    GalleryState(
        "new-article-open",
        "the header's 'Neuer Artikel …' panel open from '+ Neu …' (Titel and Bestand)",
        True,
        _reach_new_article_open,
    ),
    GalleryState(
        "new-collection-refused",
        "the header's 'Neuer Bestand …' panel after Anlegen without a Name: the error in place",
        True,
        _reach_new_collection_refused,
    ),
    GalleryState(
        "collection-edit-open",
        "the list scoped to one Bestand, its 'Bestand bearbeiten …' panel open (the rename)",
        True,
        _reach_collection_edit_open,
    ),
    GalleryState(
        "detail-actions-open",
        "the article page, the split button's menu open (Duplizieren, Löschen)",
        True,
        _reach_detail_actions_open,
    ),
    GalleryState(
        "detail-lightbox-open",
        "the article page of seven photos, the lightbox open on the third row tile",
        False,
        _reach_detail_lightbox_open,
        full_page=False,
    ),
    GalleryState(
        "detail-delete-open",
        "the article page, the delete confirm open from the menu (what goes, the one red button)",
        True,
        _reach_detail_delete_open,
    ),
    GalleryState(
        "detail-publish-open",
        "the article page, a draft's Veröffentlichen confirmation open (who will see it)",
        True,
        _reach_detail_publish_open,
    ),
    GalleryState(
        "detail-template-actions-open",
        "the article page of a Vorlage, the menu open: 'Neuer Entwurf aus Vorlage', no"
        " Veröffentlichen",
        True,
        _reach_detail_template_actions_open,
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
        "edit-date-help",
        "the edit surface, the Datierung hint's ⓘ popover open (the notation list)",
        True,
        _reach_edit_date_help,
    ),
    GalleryState(
        "edit-tag-suggestions",
        "the edit surface, the Schlagworte field suggesting for the line being typed",
        True,
        reach_tag_suggestions,
    ),
    GalleryState(
        "edit-rejected",
        "the edit surface rejected: a Gruppen error in the margin",
        True,
        _reach_edit_rejected,
    ),
    GalleryState(
        "edit-template",
        "the edit surface of a Vorlage: the box ticked, the Status without Veröffentlicht",
        True,
        _goto(f"/articles/{TEMPLATE_ULID}/edit"),
    ),
    GalleryState(
        "edit-template-refused",
        "the edit surface rejected: Vorlage ticked with Veröffentlicht, the error in the margin",
        True,
        _reach_edit_template_refused,
    ),
    GalleryState(
        "edit-conflict",
        "the edit surface after a lost CAS race: the notice in the margin, each changed field marked",
        True,
        _reach_edit_conflict,
    ),
    GalleryState(
        "edit-more-details",
        "the edit surface, one Weitere Angaben row added and filled (unsaved)",
        True,
        _reach_edit_more_details,
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

#: Stable order: the gallery is a design contract.
STATES: tuple[GalleryState, ...] = (
    *(_screen_state(screen) for screen in SCREENS),
    *_INTERACTION_STATES,
)

#: 1440 shows the pane beside the ledger; 680 is below the 80rem switch, where the pane collapses.
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
    out = out_dir if out_dir is not None else gallery_dir()
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for width in WIDTHS:
        context = browser.new_context(
            color_scheme=MODES[0], viewport={"width": width, "height": 900}
        )
        try:
            if state.archivist:
                context.add_cookies([archivist_cookie])  # type: ignore[list-item]
            page = context.new_page()
            state.reach(page, base_url, corpus)
            for mode in MODES:
                page.emulate_media(color_scheme=mode)
                target = out / f"{state.name}.{mode}.{width}.png"
                page.screenshot(path=str(target), full_page=state.full_page)
                written.append(target)
        finally:
            context.close()
    return written
