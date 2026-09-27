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

from playwright.sync_api import Page
from tests.e2e._corpus import CorpusHandles

#: What an OVERLAY is, once — every walker reads it: each mechanism the app drops a panel with, as
#: (its trigger, its panel, a JS expression resolving the trigger ``t`` to its panel). The facet
#: dropdowns are ``<details>``, the menus popovers. A new mechanism is one line here.
OVERLAY_MECHANISMS: tuple[tuple[str, str, str], ...] = (
    ("details:has(> ul) > summary", "details > ul", "t.parentElement.querySelector(':scope > ul')"),
    ("[popovertarget]", "[popover]", "t.popoverTargetElement"),
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
#: Fields; the popover menus, components.css "menu"): the fallback-tier walker exempts them from
#: "hangs under its trigger". The anchored tier still holds them to it.
OVERLAY_CENTRED_PANEL = ".popover, ul.menu[popover]"

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


def _reach_bulk_confirm(page: Page, base: str, corpus: CorpusHandles) -> None:
    """The bulk CONFIRM surface: a URL-seeded selection, expand the disclosure, choose a field and a
    value, submit. POST-only — no path reaches it, which is why it needs a reach."""
    page.goto(
        f"{base}/?auswahl={corpus.published_ulid}&auswahl={corpus.second_ulid}",
        wait_until="networkidle",
    )
    page.click("details.bulk > summary")
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    page.wait_for_load_state("networkidle")


def _reach_bulk_result(page: Page, base: str, corpus: CorpusHandles) -> None:
    """The bulk RESULT surface, one POST past the confirm."""
    _reach_bulk_confirm(page, base, corpus)
    page.click('button:has-text("anwenden")')
    page.wait_for_load_state("networkidle")


#: Every screen the app renders, in a stable order. The archivist screens all carry the shared
#: header, hence one overlay (the "+ Neu …" create menu) at minimum; the filtered workbench adds
#: one dropdown per filter-rail facet group, and the edit surface adds the margin's "Mehr …".
SCREENS: tuple[Screen, ...] = (
    Screen(
        "workbench-empty",
        "workbench, no results",
        True,
        _at("/?q=zzzznomatch"),
        "workbench",
        overlays=1,
        control_rows=("header",),
    ),
    Screen(
        "workbench-results",
        "workbench, the corpus",
        True,
        _at("/"),
        "workbench",
        overlays=1,
        control_rows=("header", "span[toolbar]"),
    ),
    Screen(
        "workbench-filtered",
        "workbench, tag filter applied (rail chip + inverted dropdown row)",
        True,
        _at("/?schlagwort=sommer"),
        "workbench",
        overlays=2,
        control_rows=("header", "nav.filterrail"),
    ),
    Screen(
        "workbench-facets",
        "workbench, two filters applied — every rail facet group carries a dropdown",
        True,
        _at("/?schlagwort=sommer&medienart=Foto(s)"),
        "workbench",
        overlays=4,
        control_rows=("header", "nav.filterrail"),
    ),
    Screen(
        "workbench-pane",
        "workbench, preview pane open",
        True,
        _goto(lambda c: f"/?artikel={c.published_ulid}"),
        "workbench",
        overlays=1,
        control_rows=("header", "span[toolbar]"),
    ),
    Screen(
        "workbench-bulk-url",
        "workbench, URL-seeded bulk selection",
        True,
        _goto(lambda c: f"/?auswahl={c.published_ulid}&auswahl={c.second_ulid}"),
        "workbench",
        overlays=1,
        control_rows=("header",),
    ),
    Screen("workbench-public", "workbench as a public visitor", False, _at("/"), "workbench"),
    Screen(
        "create-form",
        "the create step",
        True,
        _at("/artikel/neu"),
        "artikel-neu",
        overlays=1,
        control_rows=("header",),
    ),
    Screen("bestand-neu", "create a Bestand", True, _at("/bestand/neu"), "bestand-neu", overlays=1),
    Screen(
        "bestand-bearbeiten",
        "rename a Bestand (Name only)",
        True,
        _goto(lambda c: f"/bestand/{c.renamable_ulid}/bearbeiten"),
        "bestand-bearbeiten",
        overlays=1,
    ),
    Screen(
        "bestand-landing",
        "create-article form after a new Bestand (pre-selected + hinweis)",
        True,
        _goto(lambda c: f"/artikel/neu?bestand={c.renamable_ulid}&angelegt=Karten"),
        "artikel-neu",
        overlays=1,
    ),
    Screen(
        "edit-form",
        "the edit surface (a draft)",
        True,
        _goto(lambda c: f"/artikel/{c.draft_ulid}/bearbeiten"),
        "artikel-bearbeiten",
        overlays=2,
        control_rows=("header", "div.record-meta-actions"),
    ),
    # The PUBLISHED record's edit surface is the only screen carrying MEDIA — so it is the only one
    # that composes the media register's icon toolbar (owner ruling 6, the form wave's control row).
    # Every guard here was walking the DRAFT, which has no media at all.
    Screen(
        "edit-published",
        "the edit surface (a published record: media rows + their icon toolbars, retract action)",
        True,
        _goto(lambda c: f"/artikel/{c.published_ulid}/bearbeiten"),
        "artikel-bearbeiten",
        overlays=2,
        control_rows=("header", "div.record-meta-actions", "span[toolbar]"),
    ),
    Screen(
        "read-published",
        "the read view as an archivist (the action row)",
        True,
        _goto(lambda c: f"/artikel/{c.published_ulid}"),
        "artikel-detail",
    ),
    Screen(
        "delete-confirm",
        "delete, confirm page",
        True,
        _goto(lambda c: f"/artikel/{c.draft_ulid}/loeschen"),
        "artikel-loeschen",
        overlays=1,
    ),
    Screen(
        "detail-archivist-draft",
        "detail read view, archivist draft (ENTWURF + action row)",
        True,
        _goto(lambda c: f"/artikel/{c.draft_ulid}"),
        "artikel-detail",
    ),
    Screen(
        "detail-member-cover",
        "detail read view, member, with cover + filmstrip",
        False,
        _goto(lambda c: f"/artikel/{c.published_ulid}"),
        "artikel-detail",
    ),
    Screen(
        "detail-no-media",
        "detail read view, member, no media (title focal)",
        False,
        _goto(lambda c: f"/artikel/{c.second_ulid}"),
        "artikel-detail",
    ),
    # The two POST-only bulk surfaces. They are real prod screens with real chrome, and until they
    # joined the inventory they existed only as gallery shots — nothing asserted anything about them.
    Screen(
        "bulk-confirm",
        "bulk edit, confirm surface (field · value · affected list · the one primary action)",
        True,
        _reach_bulk_confirm,
        "artikel-sammelbearbeitung",
        overlays=1,
        control_rows=("header",),
    ),
    Screen(
        "bulk-result",
        "bulk edit, result surface (saved count, actionable rows only)",
        True,
        _reach_bulk_result,
        "artikel-sammelbearbeitung",
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
SCREEN_COUNT = 20


def screens_for(*, archivist: bool) -> tuple[Screen, ...]:
    """The screens one viewer tier reaches."""
    return tuple(s for s in SCREENS if s.archivist == archivist)
