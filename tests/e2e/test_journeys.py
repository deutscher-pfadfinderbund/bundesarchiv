"""Canonical E2E journeys (Part #26) — the common flows written ONCE, driven in a real browser.

Each test walks a whole flow through the live app (server + Postgres index + browser), so a review no
longer re-derives them by hand. Marked ``e2e`` (excluded from the default run; ``-m e2e`` to run).
The ``archivist_page`` / ``public_page`` fixtures (conftest) carry the right viewer cookie; the
corpus is the canonical one from ``_corpus``.

Journeys: search+filter+pane · create draft · edit+save · CAS conflict (two contexts) · Kopieren
loop · Löschen confirm · publish preview gate · bulk select→confirm→partial result.
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


def _walk_overlay_containment(page: Page, live_workbench: str) -> list[str]:
    """Open every overlay on the filtered workbench at every containment width and return the
    containment defects. The filtered URL makes the rail carry chips AND dropdowns; overlays open
    one at a time so panels never mask each other's geometry."""
    defects: list[str] = []
    for width in _CONTAINMENT_WIDTHS:
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(live_workbench + "/?schlagwort=sommer&medienart=Fotografie")
        overlays = page.locator(_OVERLAY_SELECTOR)
        found = overlays.count()
        # a silent no-find proves nothing: the create menu + one dropdown per facet group
        assert found >= 4, f"the overlay walker found only {found} panels at {width}px"
        for i in range(found):
            summary = overlays.nth(i).locator("summary")
            summary.click()
            rect: dict[str, float | str] = page.evaluate(_OVERLAY_RECT_JS, i)
            where = f"{width}px · {rect['label']}"
            if float(rect["left"]) < -1:
                defects.append(f"{where}: panel starts off-viewport at {rect['left']}px")
            if float(rect["right"]) > float(rect["viewport"]) + 1:
                defects.append(f"{where}: panel ends at {rect['right']}px > {rect['viewport']}px")
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


def test_overlays_stay_inside_the_viewport(archivist_page: Page, live_workbench: str) -> None:
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
    defects = [f"[anchored] {d}" for d in _walk_overlay_containment(page, live_workbench)]
    page.route("**/static/components.css", _serve_components_css_without_anchor_positioning)
    page.goto(live_workbench + "/")
    page.locator("details.menu summary").click()
    assert (
        page.evaluate(
            "() => getComputedStyle(document.querySelector('details.menu > ul')).positionArea"
        )
        == "none"
    ), "the enhancement is still live — the fallback tier would go unproven"
    defects += [f"[fallback] {d}" for d in _walk_overlay_containment(page, live_workbench)]
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


def _seed_long_content(root: Path, blocker: DjangoDbBlocker) -> None:
    """Add ONE article whose columns are as long as real archive content gets: a Signatur at the
    8-character ceiling, an unbounded free-text Titel, the widest vocabulary Dokumenttyp and a
    full-date EDTF interval. Seeded per test (not into the shared corpus) so the count-asserting
    journeys keep their canonical hit count."""
    from bundesarchiv.domain.edtf import EdtfDate
    from bundesarchiv.domain.models import Article, Lifecycle
    from bundesarchiv.index import indexer
    from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
    from bundesarchiv.persistence.repository import ArticleRepository

    store = LocalFsObjectStore(root)
    ArticleRepository(store).save(
        Article(
            ulid="01KXE2ELANG0000000000000AA",  # valid Crockford base32, sorts after the canonical
            title=_LONG_TITLE,
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code=_CEILING_REF_CODE,
            media_type="Plakat",
            document_type=_LONG_TYP,
            date=EdtfDate("1948-01-01/1952-12-31"),
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
    page.fill('input[name="creator"]', "K. Meyer")
    page.fill('input[name="ref_code"]', "E2E-1")
    page.click('button:has-text("Speichern")')
    # save 302s to the read view (the detail stub in this slice)
    page.wait_for_url(lambda url: "/bearbeiten" not in url and "/artikel/" in url)
    assert "/bearbeiten" not in page.url


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
    archivist_page.fill('input[name="creator"]', "Erster")
    archivist_page.click('button:has-text("Speichern")')
    archivist_page.wait_for_url(lambda url: "/bearbeiten" not in url)

    # archivist 2 saves the now-stale form → the conflict panel appears inline, values preserved
    page2.fill('input[name="creator"]', "Zweiter")
    page2.click('button:has-text("Speichern")')
    expect(page2.get_by_text("Inzwischen geändert")).to_be_visible()
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


# --- publish preview gate ----------------------------------------------------------


def test_publish_requires_over_exposure_confirm(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Zu Veröffentlichen")
    # _create_draft already set the required Medienart; open the over-exposure preview
    page.click('button:has-text("Veröffentlichen")')
    # the over-exposure preview panel appears (neutral); the confirm checkbox gates the final button
    expect(page.get_by_text("Wer bekommt nach Veröffentlichung Einblick?")).to_be_visible()
    expect(page.get_by_text("Ich habe geprüft, wer Einblick erhält.")).to_be_visible()


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
    page.fill('input[name="creator"]', "K. Meyer")
    page.click('button:has-text("Speichern")')
    page.wait_for_url(lambda url: "/bearbeiten" not in url and "/artikel/" in url)
    assert "/bearbeiten" not in page.url
