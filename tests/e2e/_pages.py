"""THE screen inventory — the one list of GET-reachable screens every e2e walker covers.

Learning G.21, applied to PAGE coverage rather than to row discovery: an invariant written as a
walker over all instances protects the next sibling the day it appears — but only if the set it walks
is derived, not hand-typed. Four hand-maintained page lists had grown side by side (the state
gallery's states, the axe pass's paths, the overlay-containment walker's pages, the three URLs in the
C8 control-row test), and they had already drifted: only the PUBLISHED record has media, so the media
register's icon toolbar — this wave's new control row, with its hit floor, its disabled treatment and
its accessible names — was composed on a screen none of the three guards visited.

So the screens live here once, and each guard derives its own view of them:

- ``test_a11y`` runs axe over every screen, split by viewer;
- ``test_journeys.test_control_rows_compute_one_height_source`` walks every ARCHIVIST screen's
  control rows (a public screen composes no chrome the archivist screens do not);
- ``test_journeys.test_overlays_stay_inside_the_viewport`` opens every overlay on every screen that
  composes one, across the width range;
- ``_gallery`` renders the plain-GET screens from here and declares only its INTERACTION states
  (a fold opened, a confirm page reached by POST) itself.

A new screen therefore lands in one tuple and is covered everywhere at once. What a screen may NOT
express here is an interaction — anything reached by clicking or POSTing stays in the gallery's own
state list, because a path is not enough to describe it.
"""

from collections.abc import Callable
from dataclasses import dataclass

from tests.e2e._corpus import CorpusHandles


@dataclass(frozen=True, slots=True)
class Screen:
    """One GET-reachable screen. ``name`` is the file-safe gallery name, ``what`` the one-line
    manifest description, ``archivist`` whether it needs the archivist cookie, ``path`` builds the URL
    from the corpus handles.

    ``overlays`` is the MINIMUM number of dropped overlay panels the screen composes — the walkers
    assert it so a silent no-find can never pass as a green walk (a screen whose overlays vanished
    would otherwise be "covered" by measuring nothing). ``control_rows`` names the row-name PREFIXES
    the C8 walk must find on the screen, for the same reason.
    """

    name: str
    what: str
    archivist: bool
    path: Callable[[CorpusHandles], str]
    overlays: int = 0
    control_rows: tuple[str, ...] = ()


def _at(path: str) -> Callable[[CorpusHandles], str]:
    """A screen whose URL carries no corpus identity."""
    return lambda _corpus: path


#: Every screen a GET reaches, in a stable order. The archivist screens all carry the shared header,
#: hence one overlay (the "+ Neu …" create disclosure) at minimum; the filtered workbench adds one
#: dropdown per filter-rail facet group, and the edit surface adds the record row's "Mehr …".
SCREENS: tuple[Screen, ...] = (
    Screen(
        "workbench-empty",
        "workbench, no results",
        True,
        _at("/?q=zzzznomatch"),
        overlays=1,
        control_rows=("header",),
    ),
    Screen(
        "workbench-results",
        "workbench, the corpus",
        True,
        _at("/"),
        overlays=1,
        control_rows=("header", "span[toolbar]"),
    ),
    Screen(
        "workbench-filtered",
        "workbench, tag filter applied (rail chip + inverted dropdown row)",
        True,
        _at("/?schlagwort=sommer"),
        overlays=2,
        control_rows=("header", "div.filterrail"),
    ),
    Screen(
        "workbench-facets",
        "workbench, two filters applied — every rail facet group carries a dropdown",
        True,
        _at("/?schlagwort=sommer&medienart=Fotografie"),
        overlays=4,
        control_rows=("header", "div.filterrail"),
    ),
    Screen(
        "workbench-pane",
        "workbench, preview pane open",
        True,
        lambda c: f"/?artikel={c.published_ulid}",
        overlays=1,
        control_rows=("header", "div[toolbar]"),
    ),
    Screen(
        "workbench-bulk-url",
        "workbench, URL-seeded bulk selection",
        True,
        lambda c: f"/?auswahl={c.published_ulid}&auswahl={c.second_ulid}",
        overlays=1,
        control_rows=("header",),
    ),
    Screen("workbench-public", "workbench as a public visitor", False, _at("/")),
    Screen(
        "create-form",
        "the create step",
        True,
        _at("/artikel/neu"),
        overlays=1,
        control_rows=("header",),
    ),
    Screen("bestand-neu", "create a Bestand", True, _at("/bestand/neu"), overlays=1),
    Screen(
        "bestand-bearbeiten",
        "rename a Bestand (Name only)",
        True,
        lambda c: f"/bestand/{c.renamable_ulid}/bearbeiten",
        overlays=1,
    ),
    Screen(
        "bestand-landing",
        "create-article form after a new Bestand (pre-selected + hinweis)",
        True,
        lambda c: f"/artikel/neu?bestand={c.renamable_ulid}&angelegt=Karten",
        overlays=1,
    ),
    Screen(
        "edit-form",
        "the edit surface (a draft)",
        True,
        lambda c: f"/artikel/{c.draft_ulid}/bearbeiten",
        overlays=2,
        control_rows=("header", "div.recordrow"),
    ),
    # The PUBLISHED record's edit surface is the only screen carrying MEDIA — so it is the only one
    # that composes the media register's icon toolbar (owner ruling 6, this wave's new control row).
    # Every guard here was walking the DRAFT, which has no media at all.
    Screen(
        "edit-published",
        "the edit surface (a published record: media rows + their icon toolbars, retract action)",
        True,
        lambda c: f"/artikel/{c.published_ulid}/bearbeiten",
        overlays=2,
        control_rows=("header", "div.recordrow", "span[toolbar]"),
    ),
    Screen(
        "read-published",
        "the read view as an archivist (the action row)",
        True,
        lambda c: f"/artikel/{c.published_ulid}",
    ),
    Screen(
        "delete-confirm",
        "delete, confirm page",
        True,
        lambda c: f"/artikel/{c.draft_ulid}/loeschen",
        overlays=1,
    ),
    Screen(
        "detail-archivist-draft",
        "detail read view, archivist draft (ENTWURF + action row)",
        True,
        lambda c: f"/artikel/{c.draft_ulid}",
    ),
    Screen(
        "detail-member-cover",
        "detail read view, member, with cover + filmstrip",
        False,
        lambda c: f"/artikel/{c.published_ulid}",
    ),
    Screen(
        "detail-no-media",
        "detail read view, member, no media (title focal)",
        False,
        lambda c: f"/artikel/{c.second_ulid}",
    ),
)


def screens_for(*, archivist: bool) -> tuple[Screen, ...]:
    """The screens one viewer tier reaches."""
    return tuple(s for s in SCREENS if s.archivist == archivist)
