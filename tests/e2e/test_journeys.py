"""Canonical E2E journeys (Part #26) — the common flows written ONCE, driven in a real browser.

Each test walks a whole flow through the live app (server + Postgres index + browser), so a review no
longer re-derives them by hand. Marked ``e2e`` (excluded from the default run; ``-m e2e`` to run).
The ``archivist_page`` / ``public_page`` fixtures (conftest) carry the right viewer cookie; the
corpus is the canonical one from ``_corpus``.

Journeys: search+filter+pane · create draft · edit+save · CAS conflict (two contexts) · Kopieren
loop · Löschen confirm · one-click publish · bulk select→confirm→partial result.
"""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Page, Route, expect
from pytest_django.plugin import DjangoDbBlocker
from tests.e2e._corpus import CorpusHandles

pytestmark = pytest.mark.e2e


# --- search + filter + pane --------------------------------------------------------


def test_search_filter_and_open_pane(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    page.goto(live_workbench + "/")
    # the ledger shows the corpus
    expect(page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(page.get_by_text("Herbstlager 1963")).to_be_visible()
    # filter by a tag facet (Schlagworte: sommer) narrows to the one article
    page.goto(live_workbench + "/?schlagwort=sommer")
    expect(page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(page.get_by_text("Herbstlager 1963")).not_to_be_visible()
    # the pane opens via the row's explicit Vorschau action (one-click model: the Titel itself
    # navigates to the detail page; the pane is never a toll gate) and keeps the search state
    page.get_by_role("link", name="Vorschau", exact=True).first.click()
    expect(page.locator(".pane")).to_be_visible()
    expect(page.locator(".pane h2")).to_have_text("Sommerfahrt 1962")
    assert "schlagwort=sommer" in page.url and "artikel=" in page.url  # URL-borne pane state
    # ✕ closes the pane and keeps the filter
    page.get_by_label("Vorschau schließen").click()
    expect(page.locator(".pane")).not_to_be_visible()
    assert "schlagwort=sommer" in page.url


#: Counts htmx's own "the swap target is not on this page" aborts. Installed on the document before
#: the interaction, because htmx:targetError is NOT a request failure — it fires before any request,
#: so the global error banner never shows and the archivist sees a dead control with no clue why.
_COUNT_TARGET_ERRORS_JS = """() => {
    window.__targetErrors = [];
    document.body.addEventListener('htmx:targetError', (e) => {
        window.__targetErrors.push(String(e.detail && e.detail.target));
    });
}"""


def test_search_works_from_a_screen_without_the_results_region(
    archivist_page: Page, live_workbench: str
) -> None:
    # The shared header (workbench/_header.html) is included by FIVE screens; #results exists on ONE.
    # While the form carried hx-get + hx-target="#results", htmx cancelled the native submit on the
    # other four and aborted with htmx:targetError — so with JS ON the search box on the
    # create/edit/Bestand screens did nothing at all, and the create step had also dropped its
    # "Zurück zur Suche" link on the grounds that the search box was the way back. The enhancement
    # now lives on the region it swaps, so the form is plain HTML everywhere: one behaviour, and it is
    # the no-JS one.
    page = archivist_page
    edit_url = _create_draft(page, live_workbench, "E2E Suche vom Formular")
    for path, submit in (
        ("/artikel/neu", "click"),
        ("/bestand/neu", "click"),
        (edit_url, "enter"),  # the edit surface, and by implicit submission rather than a click
    ):
        page.goto(path if path.startswith("http") else live_workbench + path)
        page.evaluate(_COUNT_TARGET_ERRORS_JS)
        # typing must not fire an aborted request either — off the workbench there is nothing to swap,
        # so the enhancement is simply not attached (it may not "hide" a failure, learning G.25)
        page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
        page.wait_for_timeout(700)  # longer than the 400ms type-to-search debounce
        assert page.evaluate("() => window.__targetErrors") == [], (
            f"{path}: htmx aborted a swap against an absent target"
        )
        assert "q=Sommerfahrt" not in page.url, f"{path}: typing navigated on its own: {page.url}"
        # ...and submitting IS the navigation, on this screen exactly as on the workbench
        if submit == "click":
            page.click('button:has-text("Suchen")')
        else:
            page.keyboard.press("Enter")
        page.wait_for_url("**q=Sommerfahrt**")
        expect(page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    # the create step's visible return path is back (the search box is a way back only if you type)
    page.goto(live_workbench + "/artikel/neu")
    page.get_by_text("Zurück zur Suche").click()
    page.wait_for_url(lambda url: url.rstrip("/").endswith(live_workbench.rstrip("/")))


def test_the_edit_forms_two_small_swaps_land_their_own_partials(
    archivist_page: Page, live_workbench: str
) -> None:
    # The SAME class as the header's search, found by sweeping it (learning G.27): an htmx swap
    # selector that does not resolve where the enhancement fires. htmx inherits hx-select down the
    # tree, so #bearbeiten-form's hx-select="#form-region" reached the two little GET enhancements
    # inside it — whose responses are an <option> list and one <span>, containing no #form-region.
    # htmx selected nothing and swapped exactly that: picking a Medienart EMPTIED the Dokumenttyp
    # select (no type could be chosen at all with JS on, while the no-JS baseline worked), and typing
    # a Datierung deleted the echo's own target. Both are enhancement-only, so no test that runs the
    # server saw it.
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Teilschwenks")  # picks Medienart = Fotografie
    dokumenttyp = page.locator("#dokumenttyp-select")
    expect(dokumenttyp.locator("option")).to_have_count(5)  # the empty option + Fotografie's four
    expect(dokumenttyp).to_contain_text("Lageraufnahme")
    expect(dokumenttyp).not_to_contain_text("Wanderkarte")  # ...and only that Medienart's types
    page.locator('input[name="date"]').press_sequentially("1962-07")
    expect(page.locator("#datierung-echo")).to_have_text("Juli 1962")


def test_ledger_headers_compute_one_uniform_treatment(
    archivist_page: Page, live_workbench: str
) -> None:
    # Learning G.1: a comment is not a proof; the computed style is. Every [role=columnheader]
    # AND every anchor inside one must compute the SAME font treatment (the label role) — the
    # sortable-head link may differ only by affordance, never by typography.
    archivist_page.goto(live_workbench + "/")
    treatments: list[str] = archivist_page.evaluate(
        """() => Array.from(document.querySelectorAll(
               '.ledger [role=columnheader], .ledger [role=columnheader] a'
           )).map((el) => {
               const s = getComputedStyle(el);
               return [s.fontSize, s.fontWeight, s.fontFamily, s.textTransform,
                       s.letterSpacing, s.color].join('|');
           })"""
    )
    assert len(treatments) >= 5  # four column heads + at least one sortable-head anchor
    assert len(set(treatments)) == 1, f"non-uniform header treatments: {sorted(set(treatments))}"


#: The generic control-row walker (design-review-law E, mandatory; learning G.21: invariants are
#: WALKERS over all instances). Rows are DISCOVERED, never listed: a control row is any element that
#: DECLARES the --control-height knob (its computed value differs from its parent's) plus every
#: [role=toolbar] — so the header cluster, the filter rail, the edit surface's record row and each
#: toolbar are found by the mechanism law C8 is written in, and the next row built the same way is
#: covered the day it appears. A toolbar that INHERITS its row's knob (the record row's action slot)
#: is deliberately not a row of its own: its controls belong to the row that owns the knob, which is
#: exactly the equality C8 demands.
#: A "control" is a button, a summary, a chip or a toolbar's icon link (the rail's clear-all link is
#: text, not a control). Per-instance copies of this proof are forbidden.
_CONTROL_ROW_WALKER_JS = """() => {
    const declaresKnob = (el) => {
        const own = getComputedStyle(el).getPropertyValue('--control-height').trim();
        if (!own) return false;  // unset, or reset to the guaranteed-invalid value
        const parent = el.parentElement;
        const inherited = parent
            ? getComputedStyle(parent).getPropertyValue('--control-height').trim() : '';
        return own !== inherited;
    };
    const rows = [];
    for (const el of document.querySelectorAll('*')) {
        if (el.matches('[role=toolbar]') || declaresKnob(el)) rows.push(el);
    }
    const name = (el) => (el.tagName.toLowerCase()
        + (el.id ? '#' + el.id : '')
        + (el.className && typeof el.className === 'string'
            ? '.' + el.className.trim().split(/\\s+/).join('.') : '')
        + (el.matches('[role=toolbar]') ? '[toolbar]' : ''));
    return rows.map((row) => ({
        name: name(row),
        knob: getComputedStyle(row).getPropertyValue('--control-height').trim(),
        controls: Array.from(
            row.querySelectorAll('button, a.button, summary, .chip, [role=toolbar] > a'))
            // rendered only — checkVisibility, not offsetParent: a CLOSED <details> keeps its
            // contents in the box tree (Chromium renders ::details-content with
            // content-visibility:hidden), so offsetParent still resolves for a panel item that is
            // not on screen. Opacity is deliberately NOT considered: the ledger's row-action icons
            // rest at opacity 0 and are still controls of their row.
            .filter((el) => el.checkVisibility({
                checkVisibilityCSS: true, contentVisibilityAuto: true}))
            .map((el) => {
                const s = getComputedStyle(el);
                return {
                    label: (el.getAttribute('aria-label') || el.textContent).trim(),
                    chip: el.matches('.chip'),
                    height: el.offsetHeight,
                    font: [s.fontSize, s.fontWeight, s.fontFamily, s.textTransform,
                           s.letterSpacing].join('|'),
                };
            }),
    }));
}"""


def _walk_control_rows(page: Page, url: str) -> dict[str, list[dict[str, str | int | bool]]]:
    """Every control row on ``url`` with its rendered controls, keyed by a readable row name."""
    page.goto(url)
    rows: list[dict[str, object]] = page.evaluate(_CONTROL_ROW_WALKER_JS)
    return {str(row["name"]): row["controls"] for row in rows}  # type: ignore[misc]


def _control_row_defects(by_name: dict[str, list[dict[str, str | int | bool]]]) -> list[str]:
    """Law C8, computed: within every row, one height (offsetHeight within 1px) and — chips excepted,
    which keep chip typography but must still match height — one font treatment."""
    defects: list[str] = []
    for name, controls in by_name.items():
        if len(controls) < 2:
            continue  # nothing to compare within this row
        heights = {str(c["label"]): int(str(c["height"])) for c in controls}
        if max(heights.values()) - min(heights.values()) > 1:
            defects.append(f"row '{name}' computes more than one height: {heights}")
        fonts = {c["font"] for c in controls if not c["chip"]}
        if len(fonts) > 1:
            defects.append(f"row '{name}' computes mixed control fonts: {fonts}")
    return defects


def test_control_rows_compute_one_height_source(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # Law C8 proven computed (the generalized G.1 pattern, section E) over every control row the app
    # composes: the filtered workbench (header cluster + rail with chips AND dropdowns + the ledger's
    # row toolbars) and the edit surface (the record row, whose action toolbar INHERITS the row's
    # knob — Speichern, the lifecycle action and the overflow summary must compute one height).
    page = archivist_page
    by_name = _walk_control_rows(page, live_workbench + "/?schlagwort=sommer")
    # the walker must actually see the rows this page composes — a silent no-find proves nothing
    header = next(n for n in by_name if n.startswith("header"))
    rail = next(n for n in by_name if "filterrail" in n)
    assert len(by_name[header]) >= 2  # the Suchen button + the "+ Neu …" summary
    assert any(c["chip"] for c in by_name[rail])  # the active-filter chip is present
    assert any("[toolbar]" in n for n in by_name)  # ledger row toolbars
    defects = [f"[workbench] {d}" for d in _control_row_defects(by_name)]

    edit = _walk_control_rows(page, live_workbench + f"/artikel/{e2e_corpus.draft_ulid}/bearbeiten")
    row = next(n for n in edit if "recordrow" in n)
    assert len(edit[row]) >= 3, f"the record row's controls were not found: {edit[row]}"
    defects += [f"[edit] {d}" for d in _control_row_defects(edit)]
    assert not defects, "control rows violating C8 (one height source):\n" + "\n".join(defects)


#: Every OVERLAY on the page, found generically: a native disclosure whose dropped panel is a
#: positioned list (`details > ul` — the header's "+ Neu …" create menu and each filter-rail facet
#: dropdown today). Written as a WALKER, not per instance (learning G.21/G.26): the day a new
#: overlay is built from the same pattern, this proof already covers it.
_OVERLAY_SELECTOR = "details:has(> ul)"

#: One overlay's containment facts: the panel's box against the viewport, plus the document's own
#: horizontal overflow while it is open. Both are needed — a panel can sit inside the viewport
#: while still stretching the document, and vice versa.
_OVERLAY_RECT_JS = """(index) => {
    const detail = document.querySelectorAll('details:has(> ul)')[index];
    const panel = detail.querySelector(':scope > ul');
    const r = panel.getBoundingClientRect();
    const d = document.documentElement;
    return {
        label: detail.querySelector('summary').textContent.trim(),
        left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width),
        viewport: d.clientWidth,
        docOverflow: d.scrollWidth - d.clientWidth,
    };
}"""

#: The width range every overlay must survive. 360 is the narrowest phone, 1440 a wide desktop;
#: 540/680/900 straddle the header wrap and the rail's own wrapping.
_CONTAINMENT_WIDTHS = (360, 540, 680, 900, 1440)


def _walk_overlay_containment(page: Page, live_workbench: str, corpus: CorpusHandles) -> list[str]:
    """Open every overlay on every page that composes one, at every containment width, and return the
    containment defects. The pages are named with the MINIMUM number of overlays each must carry, so a
    silent no-find can never pass as a green walk: the filtered workbench (the header's create menu +
    one dropdown per rail facet group — the filtered URL makes the rail carry chips AND dropdowns) and
    the edit surface (the record row's "Mehr …" overflow). Overlays open one at a time so panels never
    mask each other's geometry."""
    pages = (
        ("/?schlagwort=sommer&medienart=Fotografie", 4),
        (f"/artikel/{corpus.draft_ulid}/bearbeiten", 1),
    )
    defects: list[str] = []
    for width in _CONTAINMENT_WIDTHS:
        page.set_viewport_size({"width": width, "height": 900})
        for path, minimum in pages:
            page.goto(live_workbench + path)
            overlays = page.locator(_OVERLAY_SELECTOR)
            found = overlays.count()
            assert found >= minimum, (
                f"the overlay walker found only {found} panels on {path} at {width}px"
            )
            for i in range(found):
                summary = overlays.nth(i).locator("summary")
                summary.click()
                rect: dict[str, float | str] = page.evaluate(_OVERLAY_RECT_JS, i)
                where = f"{width}px · {path} · {rect['label']}"
                if float(rect["left"]) < -1:
                    defects.append(f"{where}: panel starts off-viewport at {rect['left']}px")
                if float(rect["right"]) > float(rect["viewport"]) + 1:
                    defects.append(
                        f"{where}: panel ends at {rect['right']}px > {rect['viewport']}px"
                    )
                if float(rect["docOverflow"]) > 1:
                    defects.append(f"{where}: the open panel scrolls the document {rect}")
                summary.click()  # close before measuring the next one
    return defects


#: The one pre-Baseline @supports condition in components.css, and a falsification of it. Serving
#: the REAL stylesheet with just this condition negated is how the walker reaches the FALLBACK tier
#: — no fallback CSS is restated in the test, and Chromium's own anchor-positioning support (which
#: no browser flag turns off any more) is left alone.
_ANCHOR_SUPPORTS_CONDITION = "(anchor-name: --anchor-probe)"
_ANCHOR_SUPPORTS_FALSIFIED = "(anchor-name: 0)"


def _serve_components_css_without_anchor_positioning(route: Route) -> None:
    response = route.fetch()
    css = response.text()
    patched = css.replace(_ANCHOR_SUPPORTS_CONDITION, _ANCHOR_SUPPORTS_FALSIFIED)
    assert patched != css, f"components.css no longer contains {_ANCHOR_SUPPORTS_CONDITION}"
    route.fulfill(response=response, body=patched)


def test_overlays_stay_inside_the_viewport(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # Learning G.26: every floating panel needs a computed CONTAINMENT proof across the width
    # range — both overlays could leave the viewport at widths no gallery state rendered (the
    # header create menu landed at left:-89px once the header wrapped, its labels clipped; the
    # rail's trailing dropdowns ran past the right edge and pushed the document into horizontal
    # scroll). Walked over BOTH availability tiers (law F): the ANCHORED render, where anchor
    # positioning drops each panel from its own trigger and flips it away from the edge, and the
    # FALLBACK render, where the row-pinned placement has to hold containment alone — a
    # pre-Baseline feature is licensed only where its absence is acceptable, so the fallback is
    # not something to reason about from the enhanced render.
    page = archivist_page
    assert page.evaluate("() => CSS.supports('anchor-name: --a')"), (
        "this browser has no anchor positioning — the anchored tier would go unproven"
    )
    defects = [
        f"[anchored] {d}" for d in _walk_overlay_containment(page, live_workbench, e2e_corpus)
    ]
    page.route("**/static/components.css", _serve_components_css_without_anchor_positioning)
    page.goto(live_workbench + "/")
    page.locator("details.menu summary").click()
    assert (
        page.evaluate(
            "() => getComputedStyle(document.querySelector('details.menu > ul')).positionArea"
        )
        == "none"
    ), "the enhancement is still live — the fallback tier would go unproven"
    defects += [
        f"[fallback] {d}" for d in _walk_overlay_containment(page, live_workbench, e2e_corpus)
    ]
    assert not defects, "overlays leaving the viewport (G.26):\n" + "\n".join(defects)


def test_treffer_count_rides_the_rail_and_stays_live(
    archivist_page: Page, live_workbench: str
) -> None:
    # Law C10 (owner round-2 correction 2026-08-07): the "N Treffer" count rides the filter
    # rail's line — the occupied band — and the status-only toolrow is gone. The rail lives
    # OUTSIDE the #results swap target, so the htmx type-to-search swap must refresh the count
    # out-of-band: type a narrowing q and watch the RAIL's count change without navigation.
    page = archivist_page
    page.goto(live_workbench + "/")
    count = page.locator(".filterrail #trefferzahl")
    expect(count).to_have_text("4 Treffer")  # the canonical corpus, archivist-scoped
    # The live region's NODE must survive the swap or the polite announcement dies silently (an
    # aria-live element inserted together with its content is not announced). Stamp the node with
    # an expando — a property, so no server render can reproduce it — and look for it afterwards.
    page.evaluate("() => { document.querySelector('#trefferzahl').__probe = 'same-node'; }")
    # real keystrokes (the hx-trigger is keyup; fill() sets the value without key events)
    page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
    expect(count).to_have_text("1 Treffer")  # refreshed out-of-band, no full navigation
    assert "q=Sommerfahrt" in page.url  # it was the hx swap (pushed URL), not a page load
    assert page.evaluate("() => document.querySelector('#trefferzahl').__probe") == "same-node", (
        "the count's aria-live node was replaced by the swap — announcements die silently"
    )
    # zero hits: the rail still renders, the count stays on its line (the rail is the one place)
    page.goto(live_workbench + "/?q=zzzznomatch")
    expect(page.locator(".filterrail #trefferzahl")).to_have_text("0 Treffer")


def test_rail_links_keep_the_typed_q_after_a_live_swap(
    archivist_page: Page, live_workbench: str
) -> None:
    # The rail lives OUTSIDE the #results swap target, so an htmx q-swap left every rail link
    # rendered from the PREVIOUS request: the chip ✕ and "Alle Filter entfernen" still pointed at
    # a query with no q. Typing "Sommerfahrt" and then removing a filter navigated to "?" and
    # destroyed the search — violating browse.clear_filters_query's contract ("every FILTER param
    # drops, q + sort survive"). One fact, one source: the whole filter set refreshes out-of-band
    # with the count, so the rail can never describe a query the URL no longer has.
    page = archivist_page
    for remove in ("Filter entfernen: sommer", "Alle Filter entfernen"):
        page.goto(live_workbench + "/?schlagwort=sommer&medienart=Fotografie")
        page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
        page.wait_for_url("**q=Sommerfahrt**")
        expect(page.locator(".filterrail #trefferzahl")).to_have_text("1 Treffer")
        link = (
            page.get_by_label(remove) if remove.startswith("Filter") else page.get_by_text(remove)
        )
        assert "q=Sommerfahrt" in (link.get_attribute("href") or ""), (
            f"'{remove}' was rendered before the q existed: {link.get_attribute('href')}"
        )
        link.click()
        page.wait_for_load_state()
        assert "q=Sommerfahrt" in page.url, f"'{remove}' destroyed the search: {page.url}"


def test_pane_open_never_folds_the_ledger(archivist_page: Page, live_workbench: str) -> None:
    # Decision 1 (owner 2026-08-07), proven computed (learning G.1): at the NARROWEST viewport
    # that still shows the pane (the 80rem switch = 1280px at default root font), the pane-open
    # ledger keeps its one-line row anatomy — the header row stays visible (the phone fold is
    # the only state that hides it) and the tracks merely tighten (law C11 — no column drops).
    page = archivist_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_workbench + "/")
    page.get_by_role("link", name="Vorschau", exact=True).first.click()
    expect(page.locator(".pane")).to_be_visible()
    header_row = page.locator('.ledger [role="table"] > [role="row"]')
    expect(header_row).to_be_visible()  # the fold's signature is a hidden header row


#: The stress content for the intrinsic-sizing proofs, sized by what each field can ACTUALLY carry
#: (learning G.24: an intrinsic-sizing test run on short content passes VACUOUSLY, so the stress must
#: sit where the content really grows — but stressing a BOUNDED field beyond its bound only proves a
#: fiction, learning G.6). Per the SIGNATUR DOMAIN FACT (owner, 2026-08-07) a Signatur carries NO
#: SPACES and 8 characters is the practical ceiling, so the sig column is stressed AT that ceiling
#: (the 30-character space-bearing code used while diagnosing G.24 was not representative). Typ is
#: vocabulary-bounded: its longest value IS its ceiling. The TITEL is the genuinely unbounded field —
#: free text an archivist types, with no ceiling — so it carries the real pressure here.
_CEILING_REF_CODE = "B106/XVI"  # 8 chars, no spaces: Bestand · tectonic level
_LONG_TITLE = (
    "Werbeplakat zur Bundesfahrt in die Rhön mit Aufruf zur Teilnahme"
    " am Pfingstlager des Gaues Hochland"
)
_LONG_TYP = "Veranstaltungsplakat"
#: Long HERKUNFT values: an institutional author and a full place name. They are what the record
#: card's FOLDED sections have to absorb — a folded section prints its values in its summary line
#: (owner ruling 4), which is the one place on the edit surface where unbounded text is laid out
#: without an input box around it.
_LONG_CREATOR = "Bundesleitung des Bundes Deutscher Pfadfinderinnen, Referat Öffentlichkeitsarbeit"
#: The long-content article's ULID. Crockford base32 EXCLUDES I/L/O/U, so the mnemonic "…LANG…" this
#: constant used to spell was not a valid ULID at all: the store and the index accepted it (they do
#: not validate), and the ledger proofs worked because they only ever read it back from the index —
#: but every ROUTE validates the ulid in-view, so /artikel/<it>/bearbeiten answered 404 and any proof
#: driven through a route would have passed vacuously against an empty page. Sorts after the canonical
#: corpus either way, so it still renders last in browse order.
_LONG_PLACE = "Burg Rieneck im Sinntal, Unterfranken"
_LONG_ULID = "01KXE2E1ANG0000000000000AA"


def _seed_long_content(root: Path, blocker: DjangoDbBlocker) -> None:
    """Add ONE article whose fields are as long as real archive content gets: a Signatur at the
    8-character ceiling, an unbounded free-text Titel, the widest vocabulary Dokumenttyp, a full-date
    EDTF interval, and an institutional Autor/Ort pair (what the record card's folded summaries have
    to absorb). Seeded per test (not into the shared corpus) so the count-asserting journeys keep
    their canonical hit count. Every single-line field EXCEPT Standort carries a value, which also
    makes this the record whose autofocus target sits behind the Herkunft fold
    (test_a_fold_never_swallows_the_autofocus)."""
    from bundesarchiv.domain.edtf import EdtfDate
    from bundesarchiv.domain.models import Article, Lifecycle
    from bundesarchiv.index import indexer
    from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
    from bundesarchiv.persistence.repository import ArticleRepository

    store = LocalFsObjectStore(root)
    ArticleRepository(store).save(
        Article(
            ulid=_LONG_ULID,
            title=_LONG_TITLE,
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code=_CEILING_REF_CODE,
            media_type="Plakat",
            document_type=_LONG_TYP,
            date=EdtfDate("1948-01-01/1952-12-31"),
            tags=("pfingstlager",),
            creator=_LONG_CREATOR,
            subject_place=_LONG_PLACE,
        ),
        0,
    )
    with blocker.unblock():
        indexer.rebuild(store)


#: The ledger's content minimum (law C9's arithmetic, computed live): every SHRINKABLE track at its
#: CSS floor — read from the ``--*-floor`` knobs on the grid itself, so the proof can never drift
#: from the stylesheet the way a hard-coded ``6 * 16`` did — plus the rigid tracks at their measured
#: content width, the Signatur column's margin-rule chrome, the row gaps and the row padding.
#: Mirrors the derivation comment next to the fold query in components.css.
_LEDGER_MINIMUM_JS = """() => {
    const table = document.querySelector('.ledger [role=table]');
    const s = getComputedStyle(table);
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    const floor = (name) => {
        const raw = s.getPropertyValue('--' + name + '-floor').trim();
        if (!raw.endsWith('rem')) throw new Error('no --' + name + '-floor knob: ' + raw);
        return parseFloat(raw) * rem;
    };
    const measure = (el) => {
        const r = document.createRange();
        r.selectNodeContents(el);
        return r.getBoundingClientRect().width;
    };
    const colMin = (cls) => {
        const cells = [
            ...table.querySelectorAll('[role=rowgroup] .' + cls),
            ...[...table.querySelectorAll(':scope > [role=row] .' + cls)].filter(
                (h) => !h.querySelector('.visually-hidden')),
        ];
        return Math.max(0, ...cells.map(measure));
    };
    const row = table.querySelector('[role=rowgroup] [role=row]');
    const rs = getComputedStyle(row);
    const sig = table.querySelector('[role=rowgroup] .sig');
    const sigChrome = parseFloat(getComputedStyle(sig).paddingInlineEnd)
        + parseFloat(getComputedStyle(sig).borderInlineEndWidth);
    const cols = [colMin('auswahl'), floor('sig') + sigChrome, floor('titel'),
                  floor('datum'), floor('typ'), colMin('aktion')];
    return Math.round(cols.reduce((a, b) => a + b, 0)
        + parseFloat(rs.columnGap) * (cols.length - 1)
        + parseFloat(rs.paddingLeft) + parseFloat(rs.paddingRight));
}"""

#: The [role=table]'s OWN horizontal overflow. It is the last-resort scroll box, so it CAN scroll —
#: but a scrolling register hides columns, which is exactly what law C11 forbids above the fold, so
#: above the fold this must stay zero.
_TABLE_OVERFLOW_JS = """() => {
    const t = document.querySelector('.ledger [role=table]');
    return t.scrollWidth - t.clientWidth;
}"""

#: The DOCUMENT's horizontal overflow — ledger.html's standing contract is "the page body never
#: scrolls sideways" (the [role=table] may scroll in its OWN box; the page may not).
_DOC_OVERFLOW_JS = """() => {
    const d = document.documentElement;
    return {overflow: d.scrollWidth - d.clientWidth,
            scrollX: (window.scrollTo(99999, 0), window.scrollX)};
}"""

#: Is the long TITEL actually ELLIPSIZED at this width? Its rendered box vs the width its text wants
#: (Range-measured). The Titel is the elastic track and the archive's one unbounded field, so it is
#: the column that must give space back — if it never tightens, nothing does, and the .titel
#: ellipsis is dead styling (catechism Q6). The seeded long row is the only Titel over 60 characters,
#: so it is found by length rather than by a duplicated literal.
_LONG_TITEL_JS = """() => {
    const link = [...document.querySelectorAll('.ledger [role=rowgroup] .titel a')]
        .find((e) => e.textContent.trim().length > 60);
    if (!link) throw new Error('the long-Titel row is not on this page');
    const r = document.createRange();
    r.selectNodeContents(link);
    return {box: link.getBoundingClientRect().width, text: r.getBoundingClientRect().width};
}"""


def test_ledger_columns_stay_visible_by_intrinsic_sizing(
    archivist_page: Page,
    live_workbench: str,
    e2e_corpus: CorpusHandles,
    _e2e_root: Path,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    # Law C11 (intrinsic first, owner 2026-08-07): the ledger has NO column-drop thresholds —
    # the mono columns tighten to content and the Titel ellipsizes first, so Datierung AND Typ
    # stay visible from desktop down to the ~32rem fold. G.23's red case pinned computed: the
    # old invented 60/52rem thresholds hid both columns at a 680px viewport with room to spare.
    # G.24's red case pinned the opposite escape: with long content the bare max-content tracks
    # could not shrink at all, so the ledger pushed the whole PAGE BODY into horizontal scroll from
    # 800px down. Hence the long-content seed — the short demo corpus made this proof pass
    # vacuously. WHAT is long here follows the domain (owner, 2026-08-07): a Signatur has no spaces
    # and tops out around 8 characters, and Typ comes from the vocabulary — the TITEL is the one
    # genuinely unbounded field, so it carries the pressure and it is the column that must yield.
    _seed_long_content(_e2e_root, django_db_blocker)
    page = archivist_page
    for width, path in ((680, "/"), (1280, f"/?artikel={e2e_corpus.published_ulid}")):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(live_workbench + path)
        for col in ("sig", "titel", "datierung", "typ"):
            expect(page.locator(f'.ledger [role="rowgroup"] .{col}').first).to_be_visible()
        overflow: int = page.evaluate(_TABLE_OVERFLOW_JS)
        assert overflow <= 1, f"ledger overflows its container at viewport {width}px: {overflow}px"
    # ledger.html's contract at EVERY width above the fold, pane open and closed: the page body
    # never scrolls sideways, the [role=table] absorbs the long row without a scrollbar of its own
    # (a scrolling table hides columns, which is exactly what C11 forbids), and the long Titel gives
    # its space back by ELLIPSIZING (proof the tracks are shrinkable and the .titel ellipsis is live
    # styling, not dead — Q6).
    defects: list[str] = []
    for width, path in (
        (560, "/"),
        (640, "/"),
        (800, "/"),
        (1280, f"/?artikel={e2e_corpus.published_ulid}"),
    ):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(live_workbench + path)
        doc: dict[str, float] = page.evaluate(_DOC_OVERFLOW_JS)
        if doc["overflow"] > 1 or doc["scrollX"] > 1:
            defects.append(f"{width}px: document scrolls sideways {doc}")
        table: int = page.evaluate(_TABLE_OVERFLOW_JS)
        if table > 1:
            defects.append(f"{width}px: the ledger overflows its own box by {table}px")
        titel: dict[str, float] = page.evaluate(_LONG_TITEL_JS)
        if titel["box"] >= titel["text"] - 1:
            defects.append(f"{width}px: the long Titel never tightened {titel}")
    assert not defects, "the ledger does not absorb long content intrinsically:\n" + "\n".join(
        defects
    )
    # The fold below 32rem stays the ONE modal width change (C11-licensed) and hides content
    # only out of necessity (C9): the fully-tightened one-line anatomy exceeds the fold container.
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_workbench + "/")
    minimum: int = page.evaluate(_LEDGER_MINIMUM_JS)  # measured while all columns render
    page.set_viewport_size({"width": 500, "height": 900})
    page.goto(live_workbench + "/")
    expect(page.locator('.ledger [role="table"] > [role="row"]')).to_be_hidden()  # fold active
    container: int = page.evaluate("() => document.querySelector('.ledger').clientWidth")
    assert minimum > container, (
        f"the fold engaged although the four-column anatomy ({minimum}px) fits {container}px"
    )


def test_public_never_sees_a_draft(public_page: Page, live_workbench: str) -> None:
    # the leak spine, end to end: a public visitor's workbench shows the published articles but never
    # the draft (search scopes it out) and no archivist chrome (no bulk column, no "+ Neu …" create
    # disclosure — Mock B, owner 2026-08-07).
    public_page.goto(live_workbench + "/")
    expect(public_page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(public_page.get_by_text("Lagerchronik")).not_to_be_visible()  # the draft's title
    expect(public_page.locator("details.menu")).to_have_count(0)


# --- detail read view (4.6) --------------------------------------------------------


def test_detail_read_from_search_result(public_page: Page, live_workbench: str) -> None:
    page = public_page
    # a member/public visitor: the Titel click IS the navigation to the Lesesaal detail read view
    # (one-click entry, owner 2026-08-07 — no pane interception, no JS in the loop).
    page.goto(live_workbench + "/")
    page.locator(".ledger .titel a", has_text="Sommerfahrt 1962").click()
    page.wait_for_url("**/artikel/**")
    # the reading structure: title, record card facts (Signatur + human + mono date), the cover
    expect(page.locator("main h1")).to_have_text("Sommerfahrt 1962")
    expect(page.locator("main header p")).to_have_text("Juli 1962")  # human German under the title
    expect(page.locator(".facts dd.mono").first).to_have_text("1962-07")  # mono machine date
    expect(page.get_by_text("F12")).to_be_visible()  # Signatur (no spaces — the domain fact)
    expect(page.locator("main figure img")).to_be_visible()  # cover Platte
    expect(page.locator(".filmstrip > div > a")).to_have_count(2)  # cover + one further plate
    # a plate links its gated media byte route; Zurück returns to the search
    href = page.locator(".filmstrip > div > a").first.get_attribute("href")
    assert href is not None and href.startswith("/media/")
    page.get_by_text("Zurück zur Suche").click()
    page.wait_for_url(lambda url: url.rstrip("/").endswith(live_workbench.rstrip("/")))


# --- create a Bestand (4.8) --------------------------------------------------------


def test_create_bestand_then_file_an_article_under_it(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # "+ Neu …" → Neuer Bestand → fill Name → Anlegen → LAND on the create-article form
    # (create→catalog is one flow), the new Bestand pre-selected + a success hinweis. File the
    # first article under it. The create actions live in the header's ONE quiet disclosure
    # (Mock B, owner 2026-08-07) — a native <details>, opened by a plain click.
    page.goto(live_workbench + "/")
    page.click("details.menu > summary")
    page.get_by_role("link", name="Neuer Bestand").click()
    page.wait_for_url("**/bestand/neu")
    page.fill('input[name="name"]', "Plakate")
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/artikel/neu?**")  # 302 to the create-article form, not the workbench
    expect(page.get_by_text("Bestand „Plakate“ angelegt.")).to_be_visible()  # success hinweis
    expect(page.locator('select[name="collection_id"]')).to_contain_text("Plakate")
    page.fill('input[name="title"]', "Ein Plakat")  # the new Bestand is already pre-selected
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/bearbeiten**")
    # now the Bestand has an article, so it appears in the workbench's Bestand filter dropdown
    # (the rail is the primary filter interaction — open the group to see its values)
    page.goto(live_workbench + "/")
    page.locator(".filterrail summary", has_text="Bestand").click()
    expect(page.locator(".facet a", has_text="Plakate")).to_be_visible()


# --- create a draft ----------------------------------------------------------------


def _create_draft(page: Page, base: str, title: str) -> str:
    """Drive the create step (Titel + Bestand → Anlegen) then set the required Medienart on the edit
    form, so the draft is saveable/publishable. Returns the new draft's edit-form URL."""
    page.goto(base + "/artikel/neu")
    page.fill('input[name="title"]', title)
    page.select_option('select[name="collection_id"]', "FOTOS")
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/bearbeiten**")
    # Medienart is required to save/publish (spec §3) — set it so downstream steps aren't blocked.
    page.select_option('select[name="media_type"]', "Fotografie")
    return page.url


def _open_herkunft(page: Page) -> None:
    """Unfold the record card's Herkunft section (Autor · Ort · Standort). Since the form wave the
    rarely-touched sections are folded <details> whose summary carries their values (owner ruling 4),
    so a journey that edits one of those fields opens the section the way an archivist does."""
    page.click('summary:has-text("Herkunft")')


def test_create_draft_lands_on_edit_form(archivist_page: Page, live_workbench: str) -> None:
    edit_url = _create_draft(archivist_page, live_workbench, "E2E Neuer Entwurf")
    assert "/bearbeiten" in edit_url
    # the edit form is seeded with the new title + shows the ENTWURF header badge
    expect(archivist_page.locator('input[name="title"]')).to_have_value("E2E Neuer Entwurf")
    expect(archivist_page.get_by_text("Entwurf", exact=True).first).to_be_visible()


# --- edit + save -------------------------------------------------------------------


def test_edit_and_save_redirects_to_read_view(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Zu Bearbeiten")
    page.fill('input[name="ref_code"]', "E2E-1")
    # Autor lives in the FOLDED Herkunft section (owner ruling 4) — its summary shows the values, and
    # editing one means opening it, a native <details> toggle that needs no JS
    _open_herkunft(page)
    page.fill('input[name="creator"]', "K. Meyer")
    # Saved by pressing ENTER in a field, not by clicking: since the form wave Speichern lives in the
    # record row, OUTSIDE #bearbeiten-form's subtree and associated to it by form=, and the record
    # card's own DOM splits at the media register. Implicit submission still has to find Speichern as
    # the form's default button — and the lifecycle actions, which are their own forms, still must not
    # be reachable this way (spec §6.2: Enter never publishes). Every other journey clicks the button.
    page.click('input[name="title"]')
    page.keyboard.press("Enter")
    # save 302s to the read view (the detail stub in this slice)
    page.wait_for_url(lambda url: "/bearbeiten" not in url and "/artikel/" in url)
    assert "/bearbeiten" not in page.url
    expect(page.get_by_text("Entwurf", exact=True)).to_have_count(
        1
    )  # Enter saved; it did not publish


def test_failed_save_banner_leaves_speichern_clickable(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # A failed save reveals the global error banner, fixed at the viewport BOTTOM. Since the form
    # wave the edit surface's one action place is the sticky record row at the TOP (owner ruling 2),
    # so the recorded regression class — a bottom-docked Speichern occluded by the banner at exactly
    # the moment the archivist needs to retry — is gone BY CONSTRUCTION rather than by a
    # measure-and-lift dance. This journey pins that: while the banner is up, a real browser
    # hit-test at Speichern's center still reaches the button, and the retry fires again.
    _create_draft(page, live_workbench, "E2E Fehlschlag")

    def fail_saves(route: Route) -> None:
        # abort only the save POSTs; the edit page's own GET (same URL) must keep loading normally
        if route.request.method == "POST":
            route.abort()
        else:
            route.fallback()

    page.route("**/bearbeiten", fail_saves)
    page.click('button:has-text("Speichern")')  # htmx sendError → the banner reveals
    expect(page.get_by_text("Aktion fehlgeschlagen. Bitte erneut versuchen.")).to_be_visible()
    # Scrolled to the very bottom — the harshest position for a viewport-bottom banner — the record
    # row is still pinned at the top and its Speichern is still the topmost element at its own
    # center. A bare page.click cannot pin this: Playwright's actionability retry scrolls an
    # occluded element into a clickable position and the click lands anyway.
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    state = page.evaluate(
        """() => {
        const banner = document.querySelector('.error-banner');
        const btn = document.querySelector('.recordrow button.primary');
        const b = banner.getBoundingClientRect();
        const r = btn.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return {
            speichernHit: btn === hit || btn.contains(hit),
            speichernBottom: r.bottom,
            bannerTop: b.top,
        };
    }"""
    )
    assert state["speichernHit"], "the error banner paints over Speichern (hit-test misses)"
    assert state["speichernBottom"] <= state["bannerTop"] + 1, (
        f"the record row overlaps the banner: Speichern bottom {state['speichernBottom']}px "
        f"vs banner top {state['bannerTop']}px"
    )
    # and the retry itself works end to end: the second Speichern fires another save while the
    # banner stays visible through it (the error is never sacrificed to keep the button clickable)
    page.click('button:has-text("Speichern")', timeout=5000)
    expect(page.get_by_text("Aktion fehlgeschlagen. Bitte erneut versuchen.")).to_be_visible()


# --- dirty register (PE) -----------------------------------------------------------


def test_dirty_register_covers_fields_outside_the_form_subtree(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # Custom-bag fields are form= ASSOCIATED with #bearbeiten-form but sit outside its
    # DOM subtree (the #medien-drawer split) — the dirty register must still see their first edit.
    edit_url = _create_draft(page, live_workbench, "E2E Ungespeichert")
    page.goto(edit_url)  # fresh load: _create_draft's Medienart pick already revealed the chip
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_hidden()
    page.click('summary:has-text("Weitere Angaben")')
    page.fill('input[name="custom_key"]', "Quelle")
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_visible()
    # and the plain path still works: a Gruppe-1 field inside the form reveals it too
    page.goto(edit_url)
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_hidden()
    page.fill('input[name="title"]', "E2E Ungespeichert 2")
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_visible()


# --- CAS conflict (two contexts) ---------------------------------------------------


def test_cas_conflict_second_saver_sees_panel(
    archivist_page: Page, live_workbench: str, browser: Browser
) -> None:
    # Two archivists open the SAME draft edit form at the same version; the first save wins, the
    # second sees the "Inzwischen geändert" panel (CAS, ADR 0013) — driven through two real browsers.
    edit_url = _create_draft(archivist_page, live_workbench, "E2E Rennen")

    from tests.e2e.conftest import _archivist_cookie

    ctx2 = browser.new_context()
    ctx2.add_cookies([_archivist_cookie(live_workbench)])  # type: ignore[list-item]
    page2 = ctx2.new_page()
    page2.goto(edit_url)  # both now hold the same expected_version
    # both forms carry a valid Medienart so each save reaches the CAS path (not a validation error);
    # the draft on disk has none yet, so page2 sets its own too.
    page2.select_option('select[name="media_type"]', "Fotografie")

    # archivist 1 saves first (wins)
    _open_herkunft(archivist_page)
    archivist_page.fill('input[name="creator"]', "Erster")
    archivist_page.click('button:has-text("Speichern")')
    archivist_page.wait_for_url(lambda url: "/bearbeiten" not in url)

    # archivist 2 saves the now-stale form → the conflict panel appears inline, values preserved
    _open_herkunft(page2)
    page2.fill('input[name="creator"]', "Zweiter")
    page2.click('button:has-text("Speichern")')
    expect(page2.get_by_text("Inzwischen geändert")).to_be_visible()
    # the re-render preserves every submitted value — including the one in the folded section, whose
    # SUMMARY now shows it without the archivist having to open anything (ruling 4)
    expect(page2.locator("summary", has_text="Herkunft")).to_contain_text("Zweiter")
    _open_herkunft(page2)
    expect(page2.locator('input[name="creator"]')).to_have_value("Zweiter")
    ctx2.close()


# --- Kopieren loop -----------------------------------------------------------------


def test_kopieren_creates_draft_copy_signatur_focused(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # from the published article's read view, Kopieren → a fresh draft's edit form, Signatur focused
    page.goto(live_workbench + f"/artikel/{e2e_corpus.published_ulid}")
    page.click('button:has-text("Kopieren")')
    page.wait_for_url("**/bearbeiten**")
    # the copy cleared the Signatur (ref_code) and the field is focused (spec §5)
    expect(page.locator('input[name="ref_code"]')).to_have_value("")
    expect(page.locator('input[name="ref_code"]')).to_be_focused()
    # title carried over
    expect(page.locator('input[name="title"]')).to_have_value("Sommerfahrt 1962")


# --- Löschen confirm ---------------------------------------------------------------


def test_loeschen_confirm_then_delete(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Zu Löschen")
    ulid = page.url.split("/artikel/")[1].split("/")[0]
    # from the read view, Löschen → the confirm page (the ONE red button.danger), then delete
    page.goto(live_workbench + f"/artikel/{ulid}")
    page.click('a:has-text("Löschen")')
    expect(page.get_by_text("Artikel löschen?")).to_be_visible()
    expect(page.locator("button.danger")).to_be_visible()
    page.click('button:has-text("Endgültig löschen")')
    page.wait_for_url(
        lambda url: url.rstrip("/").endswith(live_workbench.rstrip("/"))
    )  # → workbench


# --- publish: one click, exposure permanently on screen -----------------------------


def test_publish_is_one_click_with_the_exposure_on_screen(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # Owner ruling 5 (2026-08-08): the over-exposure preview GATE retired — the fact it used to
    # charge three interactions for is on screen the whole time, in the reader's sheet beside the
    # card, in the future tense while the record is a draft. Publishing is then one click.
    _create_draft(page, live_workbench, "E2E Zu Veröffentlichen")
    expect(page.locator(".pane")).to_contain_text("Nach Veröffentlichung sichtbar für")
    # ...and SAVING IS PART OF PUBLISHING (owner decision 2026-08-08): Veröffentlichen sits in the same
    # row as Speichern (ruling 2), so the archivist reaches for it with unsaved edits on screen. It used
    # to POST a lifecycle transition of its own, which rebuilt the record from disk and threw those
    # edits away without a word. Type into two fields — one inside #bearbeiten-form's subtree and one
    # OUTSIDE it (the media/custom split), because they are wired to the form differently — then publish
    # with ONE click and find both on the read view.
    page.fill('input[name="ref_code"]', "E2E-42")
    page.click('summary:has-text("Weitere Angaben")')
    page.fill('input[name="custom_key"]', "Quelle")
    page.fill('input[name="custom_value"]', "Privatbesitz Meyer")
    page.click('button:has-text("Veröffentlichen")')
    # straight to the read view, published — no panel, no checkbox, no second Veröffentlichen
    page.wait_for_url(lambda url: "/bearbeiten" not in url and "/artikel/" in url)
    expect(page.get_by_text("Entwurf", exact=True)).to_have_count(0)
    expect(page.get_by_text("E2E-42")).to_be_visible()  # the unsaved Signatur survived
    expect(page.get_by_text("Privatbesitz Meyer")).to_be_visible()  # ...and the custom row


def test_exposure_statement_is_on_screen_at_every_width(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # ONE renderer, TWO placements (law C7): the reader's sheet carries the exposure statement where
    # the pane's 80rem switch shows the pane, and the card carries it below that — so the fact is on
    # screen at EVERY width, and exactly ONCE (no Q2 duplication). Both are server-rendered: this
    # holds with JS off too.
    #
    # Nothing is CLICKED here any more, and that is the point. This proof used to open the folded
    # Zugriff section to find the statement below the switch — which meant the statement was not on
    # screen at all on a narrow window (the pane is display:none there), while the publish gate had
    # already been retired BECAUSE the statement is permanent (owner ruling 5). A test that has to
    # open a fold to see a permanent fact is reporting the defect, not the promise.
    page = archivist_page
    url = live_workbench + f"/artikel/{e2e_corpus.draft_ulid}/bearbeiten"
    for width, in_sheet in ((1440, True), (1000, False), (680, False), (360, False)):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(url)
        shown = page.locator(".einblick:visible")
        assert shown.count() == 1, f"{width}px: {shown.count()} exposure statements on screen"
        expect(shown).to_contain_text("Nach Veröffentlichung sichtbar für")
        assert page.locator(".pane:visible").count() == (1 if in_sheet else 0)


# --- bulk select → confirm → result ------------------------------------------------


def test_bulk_select_confirm_apply(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # The PROGRESSIVE cold start (owner 2026-08-07 — reverses the #16 cold-start ruling): with JS
    # on and NO selection, the whole Sammelbearbeitung affordance is hidden (the server renders it
    # visible; catalog_bulk.js hides it at count 0). The first tick reveals it with the live
    # count → expand → choose a field → Änderung prüfen posts the checked boxes → confirm → apply.
    page.goto(live_workbench + "/")
    expect(page.locator("details.bulk")).to_be_hidden()  # cold: no selection, no affordance
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(page.locator("details.bulk > summary")).to_be_visible()  # revealed on the first tick
    # unticking back to zero hides it again — the visibility tracks the live count both ways
    page.uncheck(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(page.locator("details.bulk")).to_be_hidden()
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()  # JS live count on tick, collapsed
    # expand by clicking THE COUNT ITSELF — the named regression: a form-associated element in
    # the summary (the old <output>) swallowed exactly this click and the disclosure never
    # opened; the status span must toggle like any other point on the summary line
    page.get_by_text("2 ausgewählt").click()
    expect(page.locator("details.bulk")).to_have_attribute("open", "")
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    # the confirm page lists the field + count; apply → the result page
    expect(page.get_by_text("Sammelbearbeitung prüfen")).to_be_visible()
    page.click('button:has-text("anwenden")')
    expect(page.get_by_text("abgeschlossen")).to_be_visible()


def test_bulk_url_seeded_selection_still_works(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # The pagination-persistence path: a selection seeded in the URL (?auswahl=) still renders the
    # bar with the count + confirm flow — and the JS wire-time sync must KEEP it visible (count
    # ≥ 1), it only hides at zero. Cheap second assertion so the fix doesn't regress it.
    page.goto(
        live_workbench + f"/?auswahl={e2e_corpus.published_ulid}&auswahl={e2e_corpus.second_ulid}"
    )
    expect(page.locator("details.bulk > summary")).to_be_visible()
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()  # server-rendered count, collapsed
    page.click("details.bulk > summary")
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    expect(page.get_by_text("Sammelbearbeitung prüfen")).to_be_visible()


def test_bulk_enhancement_survives_a_history_restore(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # Learning G.25, second half: htmx 2.0.4 restores a cached page WITHOUT firing afterSwap —
    # only htmx:historyRestore — and the snapshot it restores was serialized WITH the enhancement's
    # own leftovers: data-bulk-bound="1" on the form, the [hidden] state and the count text as they
    # stood at snapshot time. Checkbox ticks are properties and do NOT survive the snapshot, so
    # after search-then-Back the disclosure claimed "2 ausgewählt" over an empty selection and the
    # bound-guard left the form dead. The restore must re-init from the ACTUAL restored state.
    page = archivist_page
    page.goto(live_workbench + "/")
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()
    # a live search: hx-push-url snapshots the current page into htmx's history cache first
    page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
    page.wait_for_url("**q=Sommerfahrt**")
    page.go_back()
    page.wait_for_url(lambda url: "q=Sommerfahrt" not in url)
    # the restored page states the URL's selection (none), never the snapshot's stale count
    expect(page.locator('input[name="auswahl"]:checked')).to_have_count(0)
    expect(page.locator("details.bulk")).to_be_hidden()
    # ...and the enhancement is WIRED again: a fresh tick moves the live count
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(page.get_by_text("1 ausgewählt")).to_be_visible()


def _seed_second_page(root: Path, blocker: DjangoDbBlocker) -> None:
    """Grow the canonical corpus past one page (PAGE_SIZE=50): 60 extra published articles with
    fixed ULIDs sorting AFTER the canonical ones (browse order is ulid), then re-index so the live
    server actually paginates. 64 archivist-visible hits → page 1 holds the canonical articles."""
    from bundesarchiv.domain.models import Article, Lifecycle
    from bundesarchiv.index import indexer
    from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
    from bundesarchiv.persistence.repository import ArticleRepository

    store = LocalFsObjectStore(root)
    articles = ArticleRepository(store)
    for i in range(60):
        articles.save(
            Article(
                ulid=f"01KXE2EPAGE{i:015d}",  # valid Crockford base32, > the canonical 01KX8N…
                title=f"Seitenfüller {i:02d}",
                collection_id="FOTOS",
                lifecycle=Lifecycle.PUBLISHED,
                media_type="Fotografie",
            ),
            0,
        )
    with blocker.unblock():
        indexer.rebuild(store)


def _auswahl_in_url(page: Page) -> list[str]:
    return parse_qs(urlparse(page.url).query).get("auswahl", [])


def test_bulk_fresh_ticks_survive_paging(
    archivist_page: Page,
    live_workbench: str,
    e2e_corpus: CorpusHandles,
    _e2e_root: Path,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    # GH #22: UNSUBMITTED ticks/unticks must survive paging. catalog_bulk.js folds the live checkbox
    # state into the prev/next + "Alle auf dieser Seite" links on every change, so the URL stays the
    # canonical shareable state — the landed page renders exactly as a cold visit to it would.
    _seed_second_page(_e2e_root, django_db_blocker)
    page = archivist_page
    # land with a URL-seeded selection (the no-JS-persisted baseline state)
    page.goto(live_workbench + f"/?auswahl={e2e_corpus.published_ulid}")
    seeded = page.locator(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(seeded).to_be_checked()
    # a fresh tick + a fresh UNTICK of the URL-seeded item — both unsubmitted, DOM-only
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    seeded.uncheck()
    # "Auswahl aufheben" is NEVER rewritten — its purpose is clearing the selection
    aufheben_href = page.locator('a:has-text("Auswahl aufheben")').get_attribute("href")
    assert "auswahl" not in (aufheben_href or "")
    page.click('a[rel="next"]')
    page.wait_for_url("**seite=2**")
    # the URL carries the fresh state: the tick travelled, the untick stuck
    assert e2e_corpus.second_ulid in _auswahl_in_url(page)
    assert e2e_corpus.published_ulid not in _auswahl_in_url(page)
    # ...and the archivist can SEE it here. Learning G.25: the progressive-visibility JS counted
    # only THIS page's checkboxes, so an off-page selection (nothing ticked on page 2) was hidden
    # at wire time — the server rendered "1 ausgewählt" + Auswahl aufheben and the client took the
    # whole disclosure away, stranding the selection. Asserted BEFORE any tick on this page.
    expect(page.locator('input[name="auswahl"]:checked')).to_have_count(0)  # none of it is here
    expect(page.locator("details.bulk > summary")).to_be_visible()
    expect(page.get_by_text("1 ausgewählt")).to_be_visible()
    # tick an item on page 2, go back — the rewritten Zurück link preserves BOTH pages' selections
    page2_box = page.locator('input[name="auswahl"]').first
    page2_ulid = page2_box.get_attribute("value")
    page2_box.check()
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()  # off-page 1 + this page's fresh tick
    page.click('a[rel="prev"]')
    page.wait_for_url("**seite=1**")
    # page 1 re-renders the selection from the URL alone: tick survived, untick survived
    expect(page.locator(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')).to_be_checked()
    expect(
        page.locator(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    ).not_to_be_checked()
    assert page2_ulid in _auswahl_in_url(page)  # the other-page selection rode along
    assert e2e_corpus.second_ulid in _auswahl_in_url(page)
    # the cross-page selection stays CLEARABLE from either page (the other half of G.25: an
    # affordance the client hid could not be used) — one link drops both pages' ulids
    page.click("details.bulk > summary")
    page.click('a:has-text("Auswahl aufheben")')
    expect(page.locator("details.bulk")).to_be_hidden()  # nothing selected anywhere → hidden again
    assert not _auswahl_in_url(page)


# --- record-card guards (the form wave) ---------------------------------------------

#: Every field on the edit surface that CARRIES AN ERROR, with its control's four border colors and
#: the ink its own error message computes. Written as a WALKER over all errored fields (learning
#: G.21 — never one instance), and comparing against the message's OWN ink rather than a colour
#: constant, so the proof reads "the border is the error ink" in whatever mode/theme resolved it.
_ERROR_FIELD_WALKER_JS = """() => {
    const fields = document.querySelectorAll(
        ':is(.karte, .karte > form) > :is(section, details) > .field:has(.error)');
    return [...fields].map((field) => {
        const control = field.querySelector('input, select, textarea');
        const message = field.querySelector('.error');
        const cs = getComputedStyle(control);
        return {
            name: control.getAttribute('name'),
            message: message.textContent.trim(),
            sides: [cs.borderTopColor, cs.borderRightColor,
                    cs.borderBottomColor, cs.borderLeftColor],
            ink: getComputedStyle(message).color,
        };
    });
}"""


def test_error_fields_compute_the_error_border(archivist_page: Page, live_workbench: str) -> None:
    # Law C13 / learning G.29, proven computed: the card's RESTING look ("value on the line, no box")
    # is declared in :where(), so a field carrying an error must out-rank it and actually draw the red
    # border. This is the wave's own mock bug — an error border that existed in the stylesheet and was
    # invisible on screen — and in SOURCE an out-ranked state rule is indistinguishable from a correct
    # one, so the only honest check is the browser's.
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Fehlerhaft")
    page.fill('input[name="title"]', "")  # Titel ist erforderlich.
    page.fill('input[name="date"]', "nicht-ein-datum")  # an unparseable EDTF value
    page.click('button:has-text("Speichern")')
    expect(page.locator(".error").first).to_be_visible()
    fields: list[dict[str, str | list[str]]] = page.evaluate(_ERROR_FIELD_WALKER_JS)
    assert len(fields) >= 2, f"the walker found {len(fields)} errored fields — it proves nothing"
    defects = [
        f"{f['name']} ({f['message']}): border {f['sides']} is not the error ink {f['ink']}"
        for f in fields
        if set(f["sides"]) != {f["ink"]}
    ]
    assert not defects, "an error state lost to the resting look (C13/G.29):\n" + "\n".join(defects)


def test_a_fold_hides_neither_the_error_nor_the_focus(
    archivist_page: Page, live_workbench: str
) -> None:
    # Owner ruling 4 folds the rare sections WITH their values, so folding hides no DATA. It must hide
    # no MESSAGE either: Sichtbarkeit=Gruppe(n) with an empty Gruppen field re-rendered the message AND
    # the errored input inside the folded Zugriff section, with `autofocus` focusing nothing (a closed
    # <details> has no focusable contents). The server decides [open] from the same error context that
    # renders the message, and the summary says so via :has(.error) — proven in the browser, because
    # "on screen" and "focused" are browser facts.
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Fehler im Fach")
    page.click('summary:has-text("Zugriff")')
    page.select_option('select[name="sichtbarkeit"]', "groups")  # Gruppen stays empty -> invalid
    page.click('button:has-text("Speichern")')
    # the swap discards whatever the archivist had opened: this is the SERVER's fold state
    zugriff = page.locator("details", has=page.locator('input[name="gruppen"]'))
    expect(zugriff).to_have_attribute("open", "")
    expect(zugriff.locator(".error")).to_be_visible()
    expect(zugriff.locator(".error")).to_have_text("Bitte mindestens eine Gruppe angeben.")
    marker = page.evaluate(
        """() => {
            const d = [...document.querySelectorAll('.karte details')]
                .find((el) => el.querySelector('[name=gruppen]'));
            return getComputedStyle(d.querySelector('summary'), '::after').content;
        }"""
    )
    assert "Fehler" in marker, f"the opened section's summary does not say why: {marker}"


def test_a_fold_never_swallows_the_autofocus(
    archivist_page: Page,
    live_workbench: str,
    _e2e_root: Path,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    # The other half of the same class: _FOCUSABLE_FIELDS scans for the first EMPTY field and three of
    # them (Autor, Ort, Standort) sit behind the Herkunft fold, so on a well-catalogued record the
    # server told the browser to focus an input inside a closed <details> — which focuses NOTHING. The
    # fixture is the realistic long-content record (H.7): a Plakat with everything filled except its
    # Standort, which is exactly the state an archivist reaches at the end of cataloguing.
    _seed_long_content(_e2e_root, django_db_blocker)
    page = archivist_page
    page.goto(live_workbench + f"/artikel/{_LONG_ULID}/bearbeiten")
    standort = page.locator('input[name="physical_location"]')
    expect(standort).to_have_attribute("autofocus", "")  # the case this guard is about
    expect(standort).to_be_focused()


#: Every label on the record card, with its own box width and the width its text WANTS. The card's
#: --label-spalte knob is the one axis every section subscribes to (C3), and the arithmetic beside the
#: knob in forms.css claims it holds the longest label — both halves are measured here rather than
#: asserted in prose (learning G.1).
_LABEL_AXIS_JS = """() => {
    const fields = document.querySelectorAll(
        ':is(.karte, .karte > form) > :is(section, details) > .field');
    return [...fields].map((field) => {
        // a grid item is blockified, so the label's clientWidth IS the axis track's used width
        const label = field.querySelector(':scope > span:first-child');
        const box = label.clientWidth;
        // what the label WANTS on one line. Measured with wrapping suppressed, because a label that
        // does not fit its column simply wraps to a second line — a Range around the wrapped text
        // reports the column width back and the proof would pass vacuously.
        const before = label.style.whiteSpace;
        label.style.whiteSpace = 'nowrap';
        const wanted = label.scrollWidth;
        label.style.whiteSpace = before;
        return {text: label.textContent.trim(), box: box, text_width: wanted};
    });
}"""


def test_karte_labels_share_one_axis(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The label axis, computed (the claim forms.css writes next to --label-spalte): ONE width for every
    # label in the card whichever section it sits in, and wide enough for the longest label — a label
    # that outgrows its column does not wrap, it silently overflows into the gap, which no gallery shot
    # would reveal.
    page = archivist_page
    page.goto(live_workbench + f"/artikel/{e2e_corpus.published_ulid}/bearbeiten")
    page.click('summary:has-text("Herkunft")')  # measure the folded sections' labels too
    page.click('summary:has-text("Zugriff")')
    labels: list[dict[str, object]] = page.evaluate(_LABEL_AXIS_JS)
    assert len(labels) >= 10, f"only {len(labels)} card labels found — the walker proves nothing"
    widths = {int(str(label["box"])) for label in labels}
    assert len(widths) == 1, f"the card computes more than one label axis: {sorted(widths)}"
    overflowing = [
        f"{label['text']}: wants {label['text_width']}px in a {label['box']}px column"
        for label in labels
        if int(str(label["text_width"])) > int(str(label["box"]))
    ]
    assert not overflowing, "a label outgrew the axis (--label-spalte):\n" + "\n".join(overflowing)


def test_karte_absorbs_long_content(
    archivist_page: Page,
    live_workbench: str,
    _e2e_root: Path,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    # Learning G.24: an intrinsic-sizing proof run on short demo data passes VACUOUSLY, so the stress
    # sits where content really grows — the Titel is the archive's one unbounded field (free text an
    # archivist types). It reaches the card as an input VALUE, the reader's sheet as a heading and the
    # <title>; none of them may push the page body sideways. The seed also carries an institutional
    # Autor and a full place name, which the FOLDED sections print in their summary lines — the one
    # place on this surface where unbounded text is laid out with no input box around it. Walked at the
    # narrow width where the card is one column and at the wide one where the sheet sits beside it.
    _seed_long_content(_e2e_root, django_db_blocker)
    page = archivist_page
    url = live_workbench + f"/artikel/{_LONG_ULID}/bearbeiten"
    defects: list[str] = []
    # 360 is in the range because that is where the card's own two-column floor bit: a bare
    # minmax(floor, 1fr) track cannot shrink below its floor (G.24), so the single column stayed
    # 380px wide inside a 328px column and scrolled the page body.
    for width in (360, 680, 1000, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(url)
        doc: dict[str, float] = page.evaluate(_DOC_OVERFLOW_JS)
        if doc["overflow"] > 1 or doc["scrollX"] > 1:
            defects.append(f"{width}px: the edit surface scrolls the page body sideways {doc}")
    assert not defects, "the record card does not absorb long content:\n" + "\n".join(defects)


# --- no-JS baseline ----------------------------------------------------------------


def test_no_js_bulk_flow_completes(
    no_js_archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = no_js_archivist_page
    # The progressive pattern's no-JS half (owner 2026-08-07): the server renders the
    # Sammelbearbeitung disclosure VISIBLE, so with JavaScript OFF and no selection the archivist
    # still reaches "Alle auf dieser Seite" — the URL-borne selection path — and completes the
    # whole bulk flow: page-select → expand → choose a field → prüfen → anwenden.
    page.goto(live_workbench + "/")
    expect(page.locator("details.bulk > summary")).to_be_visible()  # server-visible, no JS hiding
    page.click("details.bulk > summary")  # native <details> toggle, no JS involved
    page.click('a:has-text("Alle auf dieser Seite")')
    page.wait_for_url("**auswahl=**")  # the selection is URL state now
    expect(page.locator("details.bulk > summary")).to_be_visible()
    page.click("details.bulk > summary")
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    expect(page.get_by_text("Sammelbearbeitung prüfen")).to_be_visible()
    page.click('button:has-text("anwenden")')
    expect(page.get_by_text("abgeschlossen")).to_be_visible()


def test_no_js_create_and_save_baseline(no_js_archivist_page: Page, live_workbench: str) -> None:
    page = no_js_archivist_page
    # The whole create→edit→save flow must work with JavaScript OFF: plain server-rendered forms,
    # no HTMX swap, no PE enhancements. This pins the baseline promise the other journeys (JS on)
    # take for granted. Create step → edit form (server 302, not an hx-swap).
    page.goto(live_workbench + "/artikel/neu")
    page.fill('input[name="title"]', "E2E Ohne JS")
    page.select_option('select[name="collection_id"]', "FOTOS")
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/bearbeiten**")
    expect(page.locator('input[name="title"]')).to_have_value("E2E Ohne JS")
    # save: a plain form POST that 302s to the read view (no JS in the loop at all)
    page.select_option('select[name="media_type"]', "Fotografie")
    _open_herkunft(page)  # a native <details> — the fold is part of the no-JS baseline
    page.fill('input[name="creator"]', "K. Meyer")
    page.click('button:has-text("Speichern")')
    page.wait_for_url(lambda url: "/bearbeiten" not in url and "/artikel/" in url)
    assert "/bearbeiten" not in page.url
