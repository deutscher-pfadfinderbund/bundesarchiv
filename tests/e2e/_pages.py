"""THE screen inventory — the one list of screens every e2e walker covers.

Learning G.21, applied to PAGE coverage rather than to row discovery: an invariant written as a
walker over all instances protects the next sibling the day it appears — but only if the set it walks
is derived, not hand-typed. Four hand-maintained page lists had grown side by side (the state
gallery's states, the axe pass's paths, the overlay-containment walker's pages, the three URLs in the
C8 control-row test), and they had already drifted: only the PUBLISHED record has media, so the media
register's icon toolbar — with its hit floor, its disabled treatment and its accessible names — was
composed on a screen none of the three guards visited.

So the screens live here once, and each guard derives its own view of them:

- ``test_a11y`` runs axe over every screen, split by viewer;
- ``test_journeys.test_control_rows_compute_one_height_source`` walks every ARCHIVIST screen's
  control rows and every toolbar button's ink;
- ``test_journeys.test_overlays_stay_inside_the_viewport`` opens every overlay on every screen that
  composes one, across the width range;
- ``_gallery`` renders every screen from here and declares only its own INTERACTION states (a menu
  opened, a rejected save) itself.

A new screen therefore lands in one tuple and is covered everywhere at once — and it cannot be
FORGOTTEN either: ``tests/app/web/test_screen_inventory.py`` asserts this tuple against the leak
matrix's route contract, so a new GET-reachable prod screen fails the fast suite until it joins.

A screen is reached by a ``reach`` callable, not by a bare path. Most are a plain navigate, but the
two bulk surfaces (confirm and result) exist only behind a POST — they were the inventory's blind
spot: they lived as gallery interaction states with zero assertions, and an unlabelled ``<input>``
plus an alt-less ``<img>`` planted on the confirm page passed every guard.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from django.test import override_settings
from playwright.sync_api import Page, expect
from tests.e2e._corpus import CorpusHandles

#: The list's path, once for every browser file (the start page is "/").
LIST = "/articles"

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
    """One screen of the app. ``name`` is the file-safe gallery name, ``what`` the one-line manifest
    description, ``archivist`` whether it needs the archivist cookie, ``reach`` how a browser gets
    there, ``route`` the prod route name that renders it (the handle the inventory gate joins on).

    ``overlays`` is the MINIMUM number of dropped overlay panels the screen composes — the walkers
    assert it so a silent no-find can never pass as a green walk (a screen whose overlays vanished
    would otherwise be "covered" by measuring nothing). ``control_rows`` names the row-name PREFIXES
    the C8 walk must find on the screen, for the same reason.
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
    """The bulk CONFIRM surface: a URL-seeded selection, open "Feld ändern …", choose a field and a
    value, submit. POST-only — no path reaches it, which is why it needs a reach."""
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
    # The PUBLISHED record's edit surface is the only screen carrying MEDIA — so it is the only one
    # that composes the media register's icon toolbar (owner ruling 6, the form wave's control row).
    # Every guard here was walking the DRAFT, which has no media at all.
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
        "the article page as a member: cover Platte and the plate register",
        False,
        _goto(lambda c: f"/articles/{c.published_ulid}"),
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
    # The two POST-only bulk surfaces. They are real prod screens with real chrome, and until they
    # joined the inventory they existed only as gallery shots — nothing asserted anything about them.
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

#: The count pin. Every guard here is a WALKER, and a walker over a shorter list is green — deleting
#: an entry silently retires the a11y pass, the C8 walk, the overlay walk and the gallery shot for
#: that screen at once. Two independently-RED mutations (a broken media toolbar, a missing
#: aria-label) both went green when their screen was dropped. The inventory gate joins this tuple to
#: the leak matrix's routes; this catches the shrink a route-level join cannot see, because several
#: screens share one route.
SCREEN_COUNT = 28


def screens_for(*, archivist: bool) -> tuple[Screen, ...]:
    """The screens one viewer tier reaches."""
    return tuple(s for s in SCREENS if s.archivist == archivist)
