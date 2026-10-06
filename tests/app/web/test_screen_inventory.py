"""The screen inventory is exhaustive against the urlconf — the mirror of the stylesheet gate.

``tests/e2e/_pages.SCREENS`` is the ONE list every e2e walker derives from (the axe pass, both
control-row walks, the overlay-containment walk, the gallery). That makes it a single point of
failure of exactly the shape learning G.40/G.41 names: a check whose SCOPE is asserted rather than
derived. Deleting an entry is GREEN in every guard, because a walker over a shorter list finds
nothing to complain about — worse, two independently-RED mutations (a broken media toolbar, a missing
``aria-label``) BOTH went green once their screen was dropped. And two real prod screens were simply
missing: the bulk CONFIRM and RESULT surfaces existed only as gallery shots, so an unlabelled
``<input>`` and an alt-less ``<img>`` planted on the confirm page passed everything.

So the inventory is gated the way ``test_design_lint.test_every_prod_stylesheet_is_linted`` gates the
stylesheet list: against the source of truth. Here that is the leak matrix's ``_CONTRACT``, which
already classifies every prod route by the status each method returns — a route that answers GET 200
either renders a screen the inventory names, or is named below as one of the things that are not
screens.

This lives in the FAST suite deliberately: a deleted screen must fail the gate every commit runs, not
only ``-m e2e``.
"""

from tests.app.web.test_leak_matrix import _CONTRACT, OK
from tests.e2e._pages import SCREEN_COUNT, SCREENS

#: Prod routes that answer GET 200 and render NO screen, each with the reason. This is the ONE place
#: an exemption may be declared, and it is a decision: a new GET route either joins the inventory or
#: earns a line here.
_NOT_A_SCREEN: dict[str, str] = {
    "static-htmx": "a static asset, not a page",
    "static-catalog-form": "a static asset, not a page",
    "static-catalog-bulk": "a static asset, not a page",
    "static-tokens": "a static asset, not a page",
    "static-components": "a static asset, not a page",
    "static-layouts": "a static asset, not a page",
    "static-forms": "a static asset, not a page",
    "static-detail": "a static asset, not a page",
    "media": "media BYTES, not a page",
    "media-thumb": "a derived thumbnail, not a page",
    "media-display": "an image's derived display version, not a page",
    "article-document-types": "an HTMX fragment (an <option> list swapped into a screen)",
    "article-bulk-edit-document-types": "an HTMX fragment (the bulk chooser's options)",
    "tag-suggestions": "a fragment (the <li> options of the Schlagworte field's list)",
}


def _get_reachable_routes() -> set[str]:
    """Every prod route whose GET renders 200 for an archivist — the app's whole readable surface, read
    off the leak matrix's contract rather than re-listed here (G.40: a guard's SET is derived)."""
    return {name for name, route in _CONTRACT.items() if route.get_arch == OK}


def test_every_get_reachable_route_is_a_screen_or_declared_not_one() -> None:
    covered = {screen.route for screen in SCREENS}
    unaccounted = _get_reachable_routes() - covered - set(_NOT_A_SCREEN)
    assert not unaccounted, (
        f"GET-reachable prod routes with no screen in tests/e2e/_pages.SCREENS and no line in"
        f" _NOT_A_SCREEN: {sorted(unaccounted)} — add the screen (it is then covered by the axe pass,"
        " both control-row walks, the overlay walk and the gallery at once) or say why it is not one"
    )
    # ...and the exemption list may not quietly cover a screen that IS in the inventory: then one of
    # the two is wrong and the reader cannot tell which.
    both = covered & set(_NOT_A_SCREEN)
    assert not both, f"declared not-a-screen AND present in the inventory: {sorted(both)}"


def test_no_screen_names_a_route_the_urlconf_lacks() -> None:
    # The other direction: a screen whose route was renamed or deleted. The leak matrix already
    # asserts _CONTRACT == the urlconf, so joining on _CONTRACT joins on the urlconf.
    stale = {screen.route for screen in SCREENS} - set(_CONTRACT)
    assert not stale, f"screens naming a route that no longer exists: {sorted(stale)}"


def test_the_inventory_has_not_shrunk() -> None:
    # The count pin. The route join above cannot see a shrink, because several screens share one route
    # (eight on `workbench`, four on `article-detail`, two on `article-edit`) — so deleting one
    # of them leaves the join green while four walkers quietly stop covering it.
    assert len(SCREENS) == SCREEN_COUNT, (
        f"the inventory holds {len(SCREENS)} screens, pinned at {SCREEN_COUNT}. Adding one? Raise the"
        " pin. Removing one? Say which guard no longer needs to see it."
    )
    names = [screen.name for screen in SCREENS]
    assert len(names) == len(set(names)), (
        f"duplicate screen names (the gallery shares them): {names}"
    )
