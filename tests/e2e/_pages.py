"""THE screen inventory: every GET-reachable screen once, which the a11y pass, the control-row and
overlay walks and the gallery all derive from (G.21; tests/CLAUDE.md).
``tests/app/web/test_screen_inventory.py`` joins it to the leak matrix's routes. A screen has a
``reach``, not a path, because the two bulk surfaces exist only behind a POST.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from django.test import override_settings
from playwright.sync_api import Page, expect
from tests.e2e._corpus import PAGE_ONLY_WORD, CorpusHandles

#: The list's path, once for every browser file (the start page is "/").
LIST = "/articles"

#: A query whose Lesesaal shows every kind of row: a word only on a page, and "Lager…" (the trailing
#: word is a prefix, ADR 0011) in a title (Lagerchronik), in a Schlagwort (Herbstlager 1963) and in a
#: description (Sommerfahrt 1962).
READING_QUERY = f"{PAGE_ONLY_WORD} or Lager"

#: What an OVERLAY is, once — every walker reads it: each mechanism the app drops a panel with, as
#: (its trigger, its panel, a JS expression resolving the trigger ``t`` to its panel). The facet
#: dropdowns are ``<details>``, the menus popovers. A new mechanism is one line here.
OVERLAY_MECHANISMS: tuple[tuple[str, str, str], ...] = (
    ("details:has(> ul) > summary", "details > ul", "t.parentElement.querySelector(':scope > ul')"),
    ('[popovertarget]:not([popovertargetaction="hide"])', "[popover]", "t.popoverTargetElement"),
)
OVERLAY_TRIGGERS = ", ".join(trigger for trigger, _, _ in OVERLAY_MECHANISMS)
OVERLAY_PANELS = ", ".join(panel for _, panel, _ in OVERLAY_MECHANISMS)
#: A JS function: an overlay trigger to its panel, whichever mechanism built it.
OVERLAY_PANEL_OF_JS = (
    "((t) => "
    + " : ".join(
        f"t.matches({json.dumps(trigger)}) ? {panel_of}"
        for trigger, _, panel_of in OVERLAY_MECHANISMS
    )
    + " : null)"
)

#: The panels the browser CENTRES when anchor positioning is absent (the help popover, DESIGN.md
#: Fields; the popover menus and tool panels, components.css "menu" / "toolpanel"): the fallback-tier walker exempts them from
#: "hangs under its trigger". The anchored tier still holds them to it.
OVERLAY_CENTRED_PANEL = ".popover, ul.menu[popover], .toolpanel"

#: How a guard gets a browser onto a screen: navigate, or drive whatever affordance leads there.
#: Every reach leaves the page fully loaded, so a caller only measures.
Reach = Callable[[Page, str, CorpusHandles], None]


@dataclass(frozen=True, slots=True)
class Screen:
    """``route`` is the prod route name the inventory gate joins on. ``overlays`` and
    ``control_rows`` are the MINIMUM a walker must find, so a silent no-find never passes as a green
    walk.
    """

    name: str
    what: str
    archivist: bool
    reach: Reach
    route: str
    overlays: int = 0
    control_rows: tuple[str, ...] = field(default=())


def _goto(build: Callable[[CorpusHandles], str]) -> Reach:
    """A reach that navigates to a URL built from the corpus handles."""

    def reach(page: Page, base: str, corpus: CorpusHandles) -> None:
        page.goto(base + build(corpus), wait_until="networkidle")

    return reach


def _at(path: str) -> Reach:
    """A reach for a screen whose URL carries no corpus identity."""
    return _goto(lambda _corpus: path)


#: The bulk check page's commit: the one submit of the form that carries ``confirmed``.
BULK_COMMIT = 'main form:has(input[name="confirmed"]) button[type="submit"]'


def _reach_bulk_confirm(page: Page, base: str, corpus: CorpusHandles) -> None:
    page.goto(
        f"{base}{LIST}?selection={corpus.published_ulid}&selection={corpus.second_ulid}",
        wait_until="networkidle",
    )
    page.click('[popovertarget="field-change"]')
    page.select_option('select[name="field"]', "creator")
    page.fill('input[name="value_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    page.wait_for_load_state("networkidle")


def _reach_bulk_result(page: Page, base: str, corpus: CorpusHandles) -> None:
    """The bulk RESULT surface, one POST past the confirm."""
    _reach_bulk_confirm(page, base, corpus)
    page.click(BULK_COMMIT)
    page.wait_for_load_state("networkidle")


def reach_door(page: Page, base: str, corpus: CorpusHandles) -> None:
    """The door, on an article's path. The browser suites run with the anonymous gate off
    (``settings_dev``), so this reach turns it on for its own navigation."""
    with override_settings(ANONYMOUS_GATE_ENABLED=True):
        page.goto(f"{base}/articles/{corpus.published_ulid}", wait_until="networkidle")


def reach_tag_suggestions(page: Page, base: str, corpus: CorpusHandles) -> None:
    """The second Article's edit form (it carries "lager") with "r" typed on a new last line of the
    Schlagworte, the suggestion list open."""
    page.goto(f"{base}/articles/{corpus.second_ulid}/edit", wait_until="networkidle")
    field = page.locator("main #field-tags")
    field.click()
    field.evaluate("(el) => el.setSelectionRange(el.value.length, el.value.length)")
    page.keyboard.press("Enter")
    field.press_sequentially("r")
    expect(page.locator(".autocomplete-list")).to_be_visible()


def reach_search_suggestions(page: Page, base: str, _corpus: CorpusHandles) -> None:
    """The start page with "meyer" typed in its search field: an Artikel and its Autor offered."""
    page.goto(f"{base}/", wait_until="networkidle")
    page.locator("main #search-field").press_sequentially("meyer")
    expect(page.locator(".autocomplete-list")).to_be_visible()


#: Every screen the app renders, in a stable order. The archivist screens all carry the shared
#: header, hence one overlay (the "+ Neu …" create menu) at minimum; a list with hits adds its
#: "Spalten …" panel, the filtered workbench one dropdown per filter-rail facet group, the edit surface the margin's "Mehr …" and the article
#: page its split button's menu (a draft's also its Veröffentlichen confirmation).
SCREENS: tuple[Screen, ...] = (
    Screen(
        "start",
        "the start page: the search sentence and the Bestände",
        True,
        _at("/"),
        "start",
        overlays=1,
        control_rows=("header",),
    ),
    Screen("start-member", "the start page as a member", False, _at("/"), "start"),
    Screen(
        "workbench-empty",
        "workbench, no results",
        True,
        _at(f"{LIST}?q=zzzznomatch"),
        "workbench",
        overlays=1,
        control_rows=("header",),
    ),
    Screen(
        "workbench-results",
        "workbench, the corpus",
        True,
        _at(LIST),
        "workbench",
        overlays=2,
        control_rows=("header", "div[toolbar]"),
    ),
    Screen(
        "workbench-filtered",
        "workbench, tag filter applied (a set filter in the search sentence)",
        True,
        _at(f"{LIST}?tag=sommer"),
        "workbench",
        overlays=3,
        control_rows=("header",),
    ),
    Screen(
        "workbench-facets",
        "workbench, two filters applied, both set in the search sentence",
        True,
        _at(f"{LIST}?tag=sommer&media_type=Foto(s)"),
        "workbench",
        overlays=5,
        control_rows=("header",),
    ),
    Screen(
        "workbench-type",
        "workbench, a type filter set: the Typ column steps back (a2 round 11)",
        True,
        _at(f"{LIST}?document_type=Zeitschrift"),
        "workbench",
        overlays=3,
        control_rows=("header", "div[toolbar]"),
    ),
    Screen(
        "workbench-pane",
        "workbench, preview pane open",
        True,
        _goto(lambda c: f"{LIST}?article={c.published_ulid}"),
        "workbench",
        overlays=2,
        control_rows=("header", "div[toolbar]"),
    ),
    Screen(
        "workbench-bulk-url",
        "workbench, URL-seeded bulk selection",
        True,
        _goto(lambda c: f"{LIST}?selection={c.published_ulid}&selection={c.second_ulid}"),
        "workbench",
        overlays=2,
        control_rows=("header",),
    ),
    Screen(
        "workbench-public",
        "workbench as a public visitor",
        False,
        _at(LIST),
        "workbench",
        overlays=1,
    ),
    Screen(
        "workbench-text-hit",
        "workbench as a public visitor, a word only on a page of a PDF: the row links that page",
        False,
        _at(f"{LIST}?q={PAGE_ONLY_WORD}"),
        "workbench",
        overlays=1,
    ),
    Screen(
        "workbench-reading",
        "workbench, a query in the Lesesaal: a hit named by its title, two by the field the word is"
        " in (the why line), one with the matching page of its PDF",
        True,
        _at(f"{LIST}?q={READING_QUERY}"),
        "workbench",
        overlays=1,
        control_rows=("header", "div[toolbar]"),
    ),
    Screen(
        "create-form",
        "the create step",
        True,
        _at("/articles/new"),
        "article-create",
        overlays=1,
        control_rows=("header", "div.record-meta-actions"),
    ),
    Screen(
        "collection-create",
        "create a Bestand",
        True,
        _at("/collections/new"),
        "collection-create",
        overlays=1,
    ),
    Screen(
        "collection-edit",
        "rename a Bestand (Name only)",
        True,
        _goto(lambda c: f"/collections/{c.renamable_ulid}/edit"),
        "collection-edit",
        overlays=1,
    ),
    Screen(
        "collection-landing",
        "create-article form after a new Bestand (pre-selected + hinweis)",
        True,
        _goto(lambda c: f"/articles/new?collection={c.renamable_ulid}&created=1"),
        "article-create",
        overlays=1,
    ),
    Screen(
        "edit-form",
        "the edit surface (a draft: the Löschen confirm in 'Mehr …')",
        True,
        _goto(lambda c: f"/articles/{c.draft_ulid}/edit"),
        "article-edit",
        overlays=4,
        control_rows=("header", "div.record-meta-actions"),
    ),
    # The only screen with media, hence the only one composing the media register's icon toolbar.
    Screen(
        "edit-published",
        "the edit surface (a published record: media rows + their icon toolbars)",
        True,
        _goto(lambda c: f"/articles/{c.published_ulid}/edit"),
        "article-edit",
        overlays=3,
        control_rows=("header", "div.record-meta-actions", "span.file-row-tools[toolbar]"),
    ),
    Screen(
        "read-published",
        "the article page as an archivist (Bearbeiten and its split menu)",
        True,
        _goto(lambda c: f"/articles/{c.published_ulid}"),
        "article-detail",
        overlays=3,
        control_rows=("header", "div.actions"),
    ),
    Screen(
        "detail-pdf",
        "the article page of a record whose one file is a PDF: its first page leads",
        True,
        _goto(lambda c: f"/articles/{c.ceiling_ulid}"),
        "article-detail",
        overlays=3,
        control_rows=("header", "div.actions"),
    ),
    Screen(
        "delete-confirm",
        "delete, confirm page",
        True,
        _goto(lambda c: f"/articles/{c.draft_ulid}/delete"),
        "article-delete",
        overlays=1,
    ),
    Screen(
        "delete-permanently-confirm",
        "delete permanently, confirm page (a record in the Papierkorb)",
        True,
        _goto(lambda c: f"/articles/{c.marked_ulid}/delete-permanently"),
        "article-delete-permanently",
        overlays=1,
    ),
    Screen(
        "trash",
        "the Papierkorb: a record with Wiederherstellen and Endgültig löschen …",
        True,
        _at("/trash"),
        "trash",
        overlays=1,
        control_rows=("header",),
    ),
    Screen(
        "detail-in-trash",
        "the article page of a record in the Papierkorb (Wiederherstellen, Endgültig löschen …)",
        True,
        _goto(lambda c: f"/articles/{c.marked_ulid}"),
        "article-detail",
        overlays=2,
        control_rows=("header", "div.actions"),
    ),
    Screen(
        "detail-archivist-draft",
        "the article page, a draft as an archivist (Veröffentlichen; Standort, Weitere Angaben)",
        True,
        _goto(lambda c: f"/articles/{c.draft_ulid}"),
        "article-detail",
        overlays=4,
        control_rows=("header", "div.actions"),
    ),
    Screen(
        "detail-member-cover",
        "the article page as a member: the cover Platte and the media rows",
        False,
        _goto(lambda c: f"/articles/{c.published_ulid}"),
        "article-detail",
    ),
    Screen(
        "detail-many",
        "the article page as a member: seven photos of mixed shape, the cover and justified rows",
        False,
        _goto(lambda c: f"/articles/{c.many_ulid}"),
        "article-detail",
    ),
    Screen(
        "detail-no-media",
        "the article page as a member, no media (the title is the focus)",
        False,
        _goto(lambda c: f"/articles/{c.second_ulid}"),
        "article-detail",
    ),
    Screen(
        "door",
        "the door: an anonymous visitor with the production gate on",
        False,
        reach_door,
        "article-detail",
    ),
    Screen(
        "bulk-confirm",
        "bulk edit, confirm surface (field · value · affected list · the one primary action)",
        True,
        _reach_bulk_confirm,
        "article-bulk-edit",
        overlays=1,
        control_rows=("header",),
    ),
    Screen(
        "bulk-result",
        "bulk edit, result surface (saved count, actionable rows only)",
        True,
        _reach_bulk_result,
        "article-bulk-edit",
        overlays=1,
        control_rows=("header",),
    ),
)

#: The count pin: a walker over a shorter list stays green, and the route join cannot see a dropped
#: screen because several share one route.
SCREEN_COUNT = 31


def screens_for(*, archivist: bool) -> tuple[Screen, ...]:
    """The screens one viewer tier reaches."""
    return tuple(s for s in SCREENS if s.archivist == archivist)
