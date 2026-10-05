"""Canonical E2E journeys (Part #26) — the common flows written ONCE, driven in a real browser.

Each test walks a whole flow through the live app (server + Postgres index + browser), so a review no
longer re-derives them by hand. Marked ``e2e`` (excluded from the default run; ``-m e2e`` to run).
The ``archivist_page`` / ``public_page`` fixtures (conftest) carry the right viewer cookie; the
corpus is the canonical one from ``_corpus``.

Journeys: search+filter+pane · create draft · edit+save · CAS conflict (two contexts) · Duplizieren
loop · Löschen → Papierkorb → restore / delete permanently · one-click publish · bulk select→confirm→partial result.
"""

import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Dialog, FilePayload, Page, Route, expect
from pytest_django.plugin import DjangoDbBlocker
from tests.app.web._asserts import assert_login_target
from tests.e2e._corpus import MINUTES_FILENAME, CorpusHandles, _png
from tests.e2e._pages import (
    BULK_COMMIT,
    LIST,
    OVERLAY_CENTRED_PANEL,
    OVERLAY_PANEL_OF_JS,
    OVERLAY_PANELS,
    OVERLAY_TRIGGERS,
    SCREENS,
    reach_door,
    reach_schlagwort_suggestions,
    screens_for,
)

from bundesarchiv.app.web import vocab

pytestmark = pytest.mark.e2e


# --- search + filter + pane --------------------------------------------------------


def test_search_filter_and_open_pane(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    page.goto(live_workbench + LIST)
    # the ledger shows the corpus
    expect(page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(page.get_by_text("Herbstlager 1963")).to_be_visible()
    # filter by a tag facet (Schlagworte: sommer) narrows to the one article
    page.goto(live_workbench + f"{LIST}?schlagwort=sommer")
    expect(page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(page.get_by_text("Herbstlager 1963")).not_to_be_visible()
    # the preview is paused (owner 2026-09-30): only its address opens the pane, beside the search
    page.goto(live_workbench + f"{LIST}?schlagwort=sommer&artikel={e2e_corpus.published_ulid}")
    expect(page.locator(".pane")).to_be_visible()
    expect(page.locator(".pane h2")).to_have_text("Sommerfahrt 1962")
    # ✕ closes the pane and keeps the filter
    page.get_by_label("Vorschau schließen").click()
    expect(page.locator(".pane")).not_to_be_visible()
    assert "schlagwort=sommer" in page.url


def test_spalten_keeps_its_choice_and_returns_to_the_same_list(
    no_js_archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # "Spalten …" (ruling 2026-09-29): without JS, a native popover and a POST that keeps the choice
    # in a cookie and redirects back to the SAME list (PRG) — query, pane and selection intact — so
    # the next visit still shows it. The address never carries it.
    page = no_js_archivist_page
    query = f"schlagwort=sommer&sortierung=-datierung&auswahl={e2e_corpus.published_ulid}"
    page.goto(f"{live_workbench}{LIST}?{query}")
    page.get_by_role("button", name="Spalten …").click()
    panel = page.locator("#spalten")
    panel.get_by_role("checkbox", name="Bestand").check()
    panel.get_by_role("checkbox", name="Signatur").uncheck()
    panel.locator("button[type=submit]").click()
    page.wait_for_url(lambda url: parse_qs(urlparse(url).query) == parse_qs(query))
    expect(page.locator(".ledger th.bestand")).to_have_text("Bestand")
    expect(page.locator(".ledger th.signatur")).to_have_count(0)
    page.goto(live_workbench + LIST)
    expect(page.locator(".ledger th.bestand")).to_have_text("Bestand")


def test_an_abandoned_panel_change_never_rides_along(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # Abbrechen, Esc and a click outside put "Spalten …" and "Feld ändern …" back as rendered, so a
    # later Fertig / Änderung prüfen submits only what the archivist kept.
    page = archivist_page
    page.goto(live_workbench + f"{LIST}?auswahl={e2e_corpus.published_ulid}")
    spalten = page.locator("#spalten")
    page.get_by_role("button", name="Spalten …").click()
    spalten.get_by_role("checkbox", name="Bestand").check()
    spalten.get_by_role("button", name="Abbrechen").click()
    page.get_by_role("button", name="Spalten …").click()
    expect(spalten.get_by_role("checkbox", name="Bestand")).not_to_be_checked()
    spalten.get_by_role("button", name="Fertig").click()
    expect(page.locator(".ledger th.signatur")).to_be_visible()
    expect(page.locator(".ledger th.bestand")).to_have_count(0)

    feld = page.locator('#feld-aendern select[name="feld"]')
    rendered = feld.input_value()
    page.click('[popovertarget="feld-aendern"]')
    feld.select_option("creator")
    page.keyboard.press("Escape")
    page.click('[popovertarget="feld-aendern"]')
    expect(feld).to_have_value(rendered)


#: Counts htmx's errors AND every request htmx starts. The REQUEST counter is what makes the
#: assertion an assertion rather than a sleep: "not attached here" means htmx started nothing at all.
_COUNT_HTMX_JS = """() => {
    window.__htmxErrors = [];
    window.__requests = [];
    document.addEventListener('htmx:error', (e) => {
        window.__htmxErrors.push(String(e.detail && e.detail.error));
    });
    document.body.addEventListener('htmx:before:request', (e) => {
        window.__requests.push(String(e.detail && e.detail.ctx && e.detail.ctx.request.action));
    });
}"""

#: Just past the type-to-search debounce on #results: long enough that a debounced request WOULD have
#: fired, and not a sleep in disguise — the assertions are on the request counter above; this only
#: opens the window in which a request could appear.
_PAST_SEARCH_DEBOUNCE_MS = 450


def test_search_works_from_a_screen_without_the_results_region(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The shared header's search lives on screens without #results. While the form carried
    # hx-get + hx-target="#results", htmx cancelled the native submit there and aborted with
    # htmx:targetError, so with JS ON the search box did nothing at all (G.32). The enhancement now
    # lives on the region it swaps, so the form is plain HTML everywhere.
    page = archivist_page
    article = f"/articles/{e2e_corpus.published_ulid}"
    for path, submit in (
        (article, "click"),
        (article, "enter"),  # and by implicit submission rather than a click
        ("/", "enter"),  # the start page's search sentence submits to the list
    ):
        page.goto(path if path.startswith("http") else live_workbench + path)
        page.evaluate(_COUNT_HTMX_JS)
        # typing must not fire an aborted request either — off the workbench there is nothing to swap,
        # so the enhancement is simply not attached (it may not "hide" a failure, learning G.25). That
        # is ASSERTED on the request counter rather than waited out: htmx must start nothing at all.
        page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
        page.wait_for_timeout(_PAST_SEARCH_DEBOUNCE_MS)
        assert page.evaluate("() => window.__htmxErrors") == [], f"{path}: htmx raised an error"
        assert page.evaluate("() => window.__requests") == [], (
            f"{path}: htmx fired a request from a screen the enhancement does not live on"
        )
        assert "q=Sommerfahrt" not in page.url, f"{path}: typing navigated on its own: {page.url}"
        # ...and submitting IS the navigation, on this screen exactly as on the workbench
        if submit == "click":
            page.click('button:has-text("Suchen")')
        else:
            page.keyboard.press("Enter")
        page.wait_for_url("**q=Sommerfahrt**")
        expect(page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    # the forms carry no search at all: it invites leaving a form with unsaved edits
    for form_url in (
        live_workbench + "/articles/new",
        live_workbench + "/collections/new",
        _create_draft(page, live_workbench, "E2E Formular ohne Suche"),
    ):
        page.goto(form_url)
        expect(page.locator('[role="search"]')).to_have_count(0)


def test_the_edit_forms_small_swap_lands_its_own_partial(
    archivist_page: Page, live_workbench: str
) -> None:
    # The same class one level down (G.27/G.32): htmx INHERITS hx-select, so #bearbeiten-form's
    # hx-select="#form-region" reached the little GET enhancement inside it — whose response is an
    # <option> list, containing no #form-region. htmx selected nothing and swapped exactly that:
    # picking a Medienart EMPTIED the Dokumenttyp select. Enhancement-only, so no server-side test
    # saw it.
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Teilschwenks")  # picks Medienart = Foto(s)
    dokumenttyp = page.locator("#dokumenttyp-select")
    expect(dokumenttyp.locator("option")).to_have_count(len(vocab.DOKUMENTTYPEN) + 1)  # + "kein"
    expect(dokumenttyp).to_contain_text("Zeitschrift")
    # ...and it is the SWAPPED list, not the no-JS baseline: both offer the same 16 words while no
    # Medienart narrows the vocabulary, so the only thing that tells them apart is the baseline's
    # single <optgroup>, which the partial does not emit. Without this the half is vacuous.
    expect(dokumenttyp.locator("optgroup")).to_have_count(0)


def test_ledger_headers_compute_one_uniform_treatment(
    archivist_page: Page, live_workbench: str
) -> None:
    # Learning G.1: a comment is not a proof; the computed style is. Every column head AND every
    # anchor inside one must compute the SAME font treatment (the label role) — the sortable-head
    # link may differ only by affordance, never by typography.
    archivist_page.goto(live_workbench + LIST)
    treatments: list[str] = archivist_page.evaluate(
        """() => Array.from(document.querySelectorAll('.ledger th, .ledger th a')).map((el) => {
               const s = getComputedStyle(el);
               return [s.fontSize, s.fontWeight, s.fontFamily, s.textTransform,
                       s.letterSpacing, s.color].join('|');
           })"""
    )
    assert len(treatments) >= 6  # five column heads + at least one sortable-head anchor
    assert len(set(treatments)) == 1, f"non-uniform header treatments: {sorted(set(treatments))}"


#: The generic control-row walker (design-review-law E, mandatory; learning G.21: invariants are
#: WALKERS over all instances). Rows are DISCOVERED, never listed: EVERY element that DECLARES the
#: --control-height knob (its computed value differs from its parent's) and EVERY [role=toolbar] is
#: walked as a row — so the header cluster, the search sentence, the edit form's action row, each
#: toolbar and each dropped overlay panel are found by the mechanism law C8 is written in, and the next
#: row built the same way is covered the day it appears. A toolbar that INHERITS its owning row's knob
#: (a toolbar inside a row) is walked too; that costs nothing, because the equality it then
#: asserts inside the toolbar is a SUBSET of the one its owning row already asserts.
#: The control set is EVERY interactive element in the row — link, button, input, select, textarea,
#: summary — so the selector and law C8's own words ("every interactive child of a control row")
#: agree. Nothing is left out: `input`/`select`, the two types the consumption rule names explicitly,
#: were missing, and while they were the header's search field could have stood 61px tall at a 24px
#: font beside 32px buttons with the whole suite green; bare links were missing too, and `a.back` stood
#: 19px in a control row (under the AA floor) for the same reason.
#: Per-instance copies of this proof are forbidden.
_CONTROL_ROW_WALKER_JS = """(overlayPanels) => {
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
    const target = (el) => (el.matches('input[type=checkbox], input[type=radio]')
        && el.closest('label')) || el;
    return rows.map((row) => ({
        name: name(row),
        knob: getComputedStyle(row).getPropertyValue('--control-height').trim(),
        controls: Array.from(row.querySelectorAll(
            'a[href], button, input, select, textarea, summary'))
            // an OVERLAY panel's entries belong to the panel, never to the row the panel hangs from
            // (the law is explicit: a toolbar may own a disclosure, and its dropped contents are
            // overlay contents). The panel is a row in its own right, so its entries are measured
            // there — counting them twice would demand that a 44px menu entry match a 32px chrome row.
            .filter((el) => {
                const panel = el.closest(overlayPanels);
                return panel === null || panel === row;
            })
            // rendered only — checkVisibility, not offsetParent: a CLOSED <details> keeps its
            // contents in the box tree (Chromium renders ::details-content with
            // content-visibility:hidden), so offsetParent still resolves for a panel item that is
            // not on screen. Opacity is deliberately NOT considered: a control resting at
            // opacity 0 until its row is hovered is still a control of its row.
            .filter((el) => el.checkVisibility({
                checkVisibilityCSS: true, contentVisibilityAuto: true}))
            .map((el) => {
                const s = getComputedStyle(el);
                return {
                    label: (el.getAttribute('aria-label') || el.textContent).trim(),
                    // The ACTIVE panel entry carries register row 3's inversion mark, and what row 3
                    // licenses is the fg/bg swap plus its SEMIBOLD — one axis. So it is exempt on
                    // font-weight and compared on the other four; a blanket exemption made a
                    // different face, size, transform or tracking inside that row unfindable.
                    inverted: !!el.closest('li:has(> [aria-current])'),
                    // ...and the row's TEXT OCCUPANTS, which share its height but not its control
                    // treatment: the wordmark carries the owner's ONE display face
                    // (tokens.css --type-wordmark, 2026-08-07) and the sentence's clear-all is a quiet
                    // text link (owner 2026-09-30). Two named
                    // selectors, not a category — anything else IS compared.
                    text: el.matches('.wordmark, .filterset > a'),
                    // a checkbox or radio inside its <label> is hit anywhere on the label, so the
                    // label is its target (WCAG 2.5.8); the native box alone stays 13px
                    height: target(el).offsetHeight,
                    width: target(el).offsetWidth,
                    // FACE and WEIGHT are separate, because their exemptions are (see above).
                    face: [s.fontSize, s.fontFamily, s.textTransform, s.letterSpacing].join('|'),
                    weight: s.fontWeight,
                };
            }),
    }));
}"""


def _walk_control_rows(page: Page) -> dict[str, list[dict[str, str | int | bool]]]:
    """Every control row on the CURRENT page with its rendered controls, keyed UNIQUELY.

    The caller has already reached the screen (``screen.reach``), because two of them are POST-only and
    a URL cannot describe them.

    The index suffix is load-bearing, not decoration. The name alone is not unique — every media row's
    toolbar names itself ``span.file-row-tools[toolbar]``, and the ledger's former row toolbars did the
    same — so keying by it collapsed 50 rows into one dict entry and the walker silently proved ONE
    toolbar instead of all of them. A guard that narrows itself and still reports green is the most dangerous kind, so the key
    carries the row's position and the name stays a readable PREFIX (callers match on it).

    A dropped overlay panel is a control row too (it declares the knob), but its entries are only
    MEASURABLE while it is open — a closed <details> or popover keeps them out of checkVisibility. So
    each overlay is opened in turn by its trigger and the walk repeated; one at a time, because
    opening one popover closes the others. Row indices are stable
    across the passes (same DOM), so the open pass fills in the rows the closed pass saw empty."""
    rows: list[dict[str, object]] = page.evaluate(_CONTROL_ROW_WALKER_JS, OVERLAY_PANELS)
    walked: dict[str, list[dict[str, str | int | bool]]] = {}
    for i, row in enumerate(rows):
        walked[f"{row['name']}#{i}"] = row["controls"]  # type: ignore[assignment]
    triggers = page.locator(OVERLAY_TRIGGERS)
    for index in range(triggers.count()):
        trigger = triggers.nth(index)
        if not trigger.is_visible():  # e.g. "Feld ändern …" before any row is picked
            continue
        trigger.click()
        for i, row in enumerate(page.evaluate(_CONTROL_ROW_WALKER_JS, OVERLAY_PANELS)):
            if row["controls"]:
                walked[f"{row['name']}#{i}"] = row["controls"]
        trigger.click()  # close before opening the next one
    return walked


#: The WCAG 2.2 AA target-size floor (law D's a11y floor, 24 CSS px). A row's controls agreeing on a
#: height that is BELOW it is a uniform defect, which C8's equality check cannot see — the 23px facet
#: entry (learning G.38) agreed with nothing and was found by eye. Checked per control, so it holds for
#: a lone control too, where there is no equality to compare — and on BOTH axes: the active facet ✕
#: once kept its height and fell to 10px wide.
_AA_TARGET_FLOOR = 24


def _control_row_defects(by_name: dict[str, list[dict[str, str | int | bool]]]) -> list[str]:
    """Law C8 + the AA target floor, computed: every interactive child of a row clears 24px and shares
    the row's one height (offsetHeight within 1px), and the row's CONTROLS share one type treatment.

    The type check is TWO checks, because the licensed deviations are one axis wide, not five. FACE
    (size, family, transform, tracking) is compared over every control, and WEIGHT additionally
    excuses the active panel entry's register-row-3 mark, which is exactly a semibold. A single five-axis exemption meant a
    marked control could differ in ANY of them undetected. The two named text occupants (see the
    walker) are outside both; every exempted element still has to match on HEIGHT."""
    defects: list[str] = []
    for name, controls in by_name.items():
        defects.extend(
            f"row '{name}' control '{c['label']}' is {c['width']}x{c['height']}px — under the"
            f" WCAG 2.2 AA {_AA_TARGET_FLOOR}px target floor"
            for c in controls
            if min(int(str(c["width"])), int(str(c["height"]))) < _AA_TARGET_FLOOR
        )
        if len(controls) < 2:
            continue  # nothing to compare within this row
        # Keyed by POSITION, not by label (learning G.37): the header holds two "Bundesarchiv" links —
        # the wordmark and the root breadcrumb — so a label-keyed dict silently dropped one of them and
        # compared a SHRUNKEN row while reporting green.
        heights = {f"{i}:{c['label']}": int(str(c["height"])) for i, c in enumerate(controls)}
        if max(heights.values()) - min(heights.values()) > 1:
            defects.append(f"row '{name}' computes more than one height: {heights}")
        compared = [c for c in controls if not c["text"]]
        faces = {c["face"] for c in compared}
        if len(faces) > 1:
            defects.append(f"row '{name}' computes mixed control faces: {faces}")
        weights = {c["weight"] for c in compared if not c["inverted"]}
        if len(weights) > 1:
            defects.append(f"row '{name}' computes mixed control weights: {weights}")
    return defects


def test_control_rows_compute_one_height_source(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # Law C8 proven computed (the generalized G.1 pattern, section E) over every control row the app
    # composes — on EVERY archivist screen the app has, derived from the one screen inventory
    # (_pages.SCREENS) instead of three hand-picked URLs. The three URLs had already drifted: only the
    # PUBLISHED record carries media, so the media register's icon toolbar — the form wave's new
    # control row — was composed on a screen this walk never visited (G.21 applied to page coverage).
    #
    # Per screen the walk finds the header cluster, the search sentence, the
    # list's tool row, the dropped overlay panels' entries, the edit form's action row
    # (Speichern, the lifecycle action and "Mehr …" must
    # compute one height) and the media register's row toolbars. Each screen NAMES the row prefixes it
    # must compose, so a silent no-find can never pass as a green walk.
    #
    # The toolbar-BUTTON ink walk (below) rides the same loop: it is a second measurement of the same
    # rows on the same reached page, and giving it its own test cost a second full pass over every
    # screen — 18 more page loads, two POST flows among them, for findings on one screen.
    page = archivist_page
    defects: list[str] = []
    ink_defects: list[str] = []
    buttons = 0
    for screen in screens_for(archivist=True):
        screen.reach(page, live_workbench, e2e_corpus)
        by_name = _walk_control_rows(page)
        for prefix in screen.control_rows:
            found = [n for n in by_name if n.startswith(prefix)]
            assert found, f"[{screen.name}] no control row named {prefix!r}: {sorted(by_name)}"
        defects += [f"[{screen.name}] {d}" for d in _control_row_defects(by_name)]
        found_buttons, found_ink = _toolbar_button_defects(page, screen.name)
        buttons += found_buttons
        ink_defects += found_ink
    assert not defects, "control rows violating C8 (one height source):\n" + "\n".join(defects)
    assert buttons >= 2, (
        f"the walk measured {buttons} toolbar buttons — the ink check proves nothing"
    )
    assert not ink_defects, "a toolbar button lost its button roles:\n" + "\n".join(ink_defects)


#: Every `a.button` in a toolbar slot, with the ink/fill it computes — and the three colour ROLES
#: resolved on a probe element, because a token's raw value is a `light-dark()` expression that only a
#: rendered element resolves to the mode's rgb. Comparing against roles rather than against literals
#: keeps the proof true in both modes and after any retint (themability law).
_TOOLBAR_BUTTON_JS = """() => {
    const probe = document.createElement('span');
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    document.body.appendChild(probe);
    const role = (name) => {
        probe.style.color = 'var(' + name + ')';
        return getComputedStyle(probe).color;
    };
    const roles = {ground: role('--ground'), ink: role('--ink')};
    probe.remove();
    const buttons = [...document.querySelectorAll('[role=toolbar] a.button')].map((a) => {
        const s = getComputedStyle(a);
        return {label: a.textContent.trim(), primary: a.classList.contains('primary'),
                color: s.color, background: s.backgroundColor};
    });
    return {roles: roles, buttons: buttons};
}"""


def _toolbar_buttons(page: Page) -> tuple[dict[str, str], list[dict[str, str | bool]]]:
    """The resolved colour roles plus one record per toolbar `a.button` on the current page."""
    facts: dict[str, dict[str, str] | list[dict[str, str | bool]]] = page.evaluate(
        _TOOLBAR_BUTTON_JS
    )
    roles = facts["roles"]
    buttons = facts["buttons"]
    assert isinstance(roles, dict) and isinstance(buttons, list)
    return roles, buttons


def _toolbar_button_defects(page: Page, where: str) -> tuple[int, list[str]]:
    """Every toolbar `a.button` on the current page, checked against the two role pairs the elements
    layer declares for it: `.primary` is the INVERSION (`--ground` ink on `--ink`), a plain one is
    `--ink` on `--ground`. Returns (how many were measured, defects) so the caller can also assert
    the walk was not empty."""
    roles, buttons = _toolbar_buttons(page)
    defects: list[str] = []
    for button in buttons:
        want = (
            (roles["ground"], roles["ink"])
            if button["primary"]
            else (roles["ink"], roles["ground"])
        )
        got = (button["color"], button["background"])
        if got != want:
            defects.append(
                f"{where}: '{button['label']}' computes {got}, not the button roles {want}"
            )
    return len(buttons), defects


def test_the_primary_toolbar_button_keeps_its_button_roles_under_the_pointer(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The RESTING ink of every toolbar button on every screen is walked by the C8 test above; this is
    # the state that needs a real pointer. The shared icon-ink rule for a toolbar's children reached
    # the pane's Öffnen/Bearbeiten, which are `a.button`s and not icon controls, and WON because it
    # sits in @layer components while the button's look is in @layer elements — layer order beats
    # specificity, so even a :where() rule overrides. Measured: 14.98:1 -> 2.24:1 light,
    # 14.06:1 -> 1.64:1 dark, and the hover rule dropped the inversion entirely, so the mark vanished
    # under the pointer. A computed check is the only honest one here — axe's color-contrast is
    # disabled by owner ruling (2026-08 audit), and in source a layer-outranked declaration looks
    # exactly like a live one. Under the pointer the primary turns to its outline (DESIGN.md).
    page = archivist_page
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(live_workbench + f"{LIST}?artikel={e2e_corpus.published_ulid}")
    primary = page.locator(".pane [role=toolbar] a.button.primary")
    expect(primary).to_be_visible()
    primary.hover()
    roles, buttons = _toolbar_buttons(page)
    marks = [b for b in buttons if b["primary"]]
    assert marks and all(
        (b["color"], b["background"]) == (roles["ink"], roles["ground"]) for b in marks
    ), f"hover loses the primary's outline roles: {marks}"


def test_the_control_row_walk_sees_what_the_screens_compose(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The walk above asserts uniformity; this asserts it is not walking an empty page. The row KINDS
    # the app composes, each on the screen that has the most of them: the header's control cluster, the
    # dropped panels' entries, and the edit form's action row plus the media
    # register's per-row toolbars on the published edit surface (every one of those names itself
    # "span.file-row-tools[toolbar]" — keying rows by name once collapsed 50 such rows into one entry
    # and the walk proved a SINGLE toolbar while reporting green, G.37).
    page = archivist_page
    page.goto(live_workbench + f"{LIST}?schlagwort=sommer")
    filtered = _walk_control_rows(page)
    header = next(n for n in filtered if n.startswith("header"))
    assert filtered[header]  # the "+ Neu …" button (the search field is the sentence's here)
    panels = [n for n in filtered if n.startswith("ul#") and len(filtered[n]) >= 2]
    assert len(panels) >= 2, f"the walker measured no panel entries: {sorted(filtered)}"

    page.goto(live_workbench + f"/articles/{e2e_corpus.published_ulid}/edit")
    edit = _walk_control_rows(page)
    row = next(n for n in edit if "record-meta-actions" in n)
    # Speichern and "Mehr …"
    assert len(edit[row]) >= 2, f"the edit form's action row was not found: {edit[row]}"
    # the media register's row toolbars: the corpus record has three files, so three toolbars of three
    # icon buttons each (up · down · remove) — the control row this wave ADDED, unguarded until now
    media = [n for n in edit if n.startswith("span.file-row-tools[toolbar]") and len(edit[n]) >= 3]
    assert len(media) >= 3, f"the media register's row toolbars were not walked: {sorted(edit)}"


#: One overlay's containment facts: the panel's box against the viewport, the panel's top edge
#: against its own trigger's bottom edge (issue #53 — the anchored tier landed both panels OVER
#: their trigger row, and no fact here measured it), the document's own horizontal overflow while it
#: is open, and — added after a sticky control row was found painting over the header's create
#: menu — whether each of the panel's own entries is HIT-TESTABLE at its centre. Being on-viewport is not the same as being reachable: a panel can sit
#: perfectly inside the viewport under an opaque sticky row that eats every click, which is the
#: regression class CLAUDE.md records. elementFromPoint answers the reachability question the way the
#: browser will answer it for the archivist's pointer, and it costs the walker one loop, so EVERY
#: overlay gets it rather than the one that failed (learning G.21).
#: Opens EVERY overlay on the page in turn (one at a time — opening one popover closes
#: the others anyway) and returns one facts record per panel. One evaluate per
#: (screen, width) instead of two clicks plus an evaluate per panel: the whole measurement is
#: synchronous DOM work (opening forces layout before getBoundingClientRect reads it), so
#: paying a Playwright round-trip per open/close bought nothing but wall clock.
_OVERLAY_WALK_JS = (
    (
        """(triggers) => {
    const panelOf = PANEL_OF;
    const facts = [];
    for (const trigger of document.querySelectorAll(triggers)) {
        const panel = panelOf(trigger);
        // a trigger inside a closed panel ("Löschen …" in a menu) is reached through that panel
        const host = trigger.parentElement.closest('[popover]:not(:popover-open)');
        if (host) host.showPopover();
        const opened = !panel.checkVisibility();
        if (opened) trigger.click();
        const r = panel.getBoundingClientRect();
        // opening the panel closed its menu, so it hangs from the menu's own button (menu.js)
        const from = host && !host.matches(':popover-open')
            ? document.querySelector('[popovertarget="' + host.id + '"]') : trigger;
        const edge = from.getBoundingClientRect();
        const d = document.documentElement;
        const covered = [];
        for (const entry of panel.querySelectorAll('a, button, input, select')) {
            const b = entry.getBoundingClientRect();
            if (b.width === 0 || b.height === 0) continue;   // not rendered — nothing to reach
            const hit = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
            if (!(hit === entry || entry.contains(hit)
                  || entry.contains(hit && hit.parentElement))) {
                covered.push((entry.textContent || entry.getAttribute('aria-label') || '?').trim()
                    + ' <- ' + (hit ? hit.tagName.toLowerCase()
                        + (typeof hit.className === 'string' && hit.className
                            ? '.' + hit.className.trim().split(/\\s+/).join('.') : '')
                        : 'nothing'));
            }
        }
        facts.push({
            label: trigger.textContent.trim(),
            centred: panel.matches(CENTRED),
            top: Math.round(r.top), triggerBottom: Math.round(edge.bottom),
            left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width),
            viewport: d.clientWidth,
            docOverflow: d.scrollWidth - d.clientWidth,
            covered: covered,
        });
        if (opened) trigger.click();
        if (host) host.hidePopover();
    }
    return facts;
}"""
    )
    .replace("PANEL_OF", OVERLAY_PANEL_OF_JS)
    .replace("CENTRED", json.dumps(OVERLAY_CENTRED_PANEL))
)

#: The width range every overlay must survive. 360 is the narrowest phone, 1440 a wide desktop;
#: 540/680/900 straddle the header wrap and the rail's own wrapping. 1100 closes a 540px hole between
#: 900 and 1440 — the widest unswept stretch of the range, and the one the pane's 80rem switch sits
#: just above, so a panel that only escapes on a laptop-width desk had nowhere to be caught. One more
#: width costs the walk ~10%; the gap cost it a whole viewport class.
_CONTAINMENT_WIDTHS = (360, 540, 680, 900, 1100, 1440)


def _walk_overlay_containment(
    page: Page, live_workbench: str, corpus: CorpusHandles, *, anchored: bool
) -> list[str]:
    """Open every overlay on every screen that composes one, at every containment width, and return the
    containment defects.

    The screens come from the ONE inventory (``_pages.SCREENS``), each carrying the MINIMUM number of
    overlay panels it must compose, so a silent no-find can never pass as a green walk — and a new
    screen is covered the day it joins the inventory (G.21 applied to page coverage).

    ONE ``goto`` per screen, widths swept INSIDE it, and one ``evaluate`` per (screen, width):
    containment and reachability are pure CSS-geometry questions, so re-loading the page at each width
    and paying two click round-trips per panel bought nothing. The old two-page list spent 16 avoidable
    page loads on it; this walk visits nine more screens for less wall clock.

    ``anchored`` adds the anchored tier's own promise (G.50): each panel hangs from ITS trigger, the
    drop gap below it and no more. Two menus on one page resolving one anchor name land a panel under
    the other menu's button, which stays on-viewport and below its trigger."""
    defects: list[str] = []
    for screen in SCREENS:
        if not screen.overlays:
            continue
        screen.reach(page, live_workbench, corpus)
        found = page.locator(OVERLAY_TRIGGERS).count()
        assert found >= screen.overlays, (
            f"the overlay walker found only {found} panels on {screen.name}"
        )
        for width in _CONTAINMENT_WIDTHS:
            page.set_viewport_size({"width": width, "height": 900})
            for rect in page.evaluate(_OVERLAY_WALK_JS, OVERLAY_TRIGGERS):
                where = f"{width}px · {screen.name} · {rect['label']}"
                if rect["covered"]:
                    defects.append(f"{where}: entries painted over: {rect['covered']}")
                # unanchored, a popover panel (help, menu) is the centred native one by design
                centred = rect["centred"] and not anchored
                if not centred and float(str(rect["top"])) < float(str(rect["triggerBottom"])) - 1:
                    defects.append(
                        f"{where}: panel top {rect['top']}px covers its trigger "
                        f"(bottom {rect['triggerBottom']}px)"
                    )
                # the drop gap is --space-1 (4px); the slack covers rounding
                if anchored and float(str(rect["top"])) > float(str(rect["triggerBottom"])) + 8:
                    defects.append(
                        f"{where}: panel top {rect['top']}px does not hang from its trigger "
                        f"(bottom {rect['triggerBottom']}px)"
                    )
                if float(str(rect["left"])) < -1:
                    defects.append(f"{where}: panel starts off-viewport at {rect['left']}px")
                if float(str(rect["right"])) > float(str(rect["viewport"])) + 1:
                    defects.append(
                        f"{where}: panel ends at {rect['right']}px > {rect['viewport']}px"
                    )
                if float(str(rect["docOverflow"])) > 1:
                    defects.append(f"{where}: the open panel scrolls the document {rect}")
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
    # positioning drops each panel from its own trigger and shifts it clear of the row's edges, and the
    # FALLBACK render, where the row-pinned placement has to hold containment alone — a
    # pre-Baseline feature is licensed only where its absence is acceptable, so the fallback is
    # not something to reason about from the enhanced render.
    page = archivist_page
    assert page.evaluate("() => CSS.supports('anchor-name: --a')"), (
        "this browser has no anchor positioning — the anchored tier would go unproven"
    )
    defects = [
        f"[anchored] {d}"
        for d in _walk_overlay_containment(page, live_workbench, e2e_corpus, anchored=True)
    ]
    page.route("**/static/components.css", _serve_components_css_without_anchor_positioning)
    page.goto(live_workbench + LIST)
    anchors = page.evaluate(
        "() => ['ul.menu[popover]'].map("
        "(s) => getComputedStyle(document.querySelector(s)).positionAnchor)"
    )
    assert "--menu-button" not in anchors, (
        f"the enhancement is still live — the fallback tier would go unproven: {anchors}"
    )
    defects += [
        f"[fallback] {d}"
        for d in _walk_overlay_containment(page, live_workbench, e2e_corpus, anchored=False)
    ]
    assert not defects, "overlays leaving the viewport (G.26):\n" + "\n".join(defects)


def test_the_header_menu_is_clickable_on_the_edit_screen(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The recorded regression class (CLAUDE.md): a fixed/sticky element whose paint order lets it
    # intercept clicks — once a sticky control row painted over the header's "+ Neu …" panel on this
    # screen, and the form's margin is sticky now. The guard is a real CLICK, not a geometry
    # measurement: the walker's hit-test above catches the class generically, this proves the
    # archivist's actual path end to end.
    page = archivist_page
    page.set_viewport_size({"width": 1440, "height": 900})
    for entry, panel in (("Neuer Artikel …", "#neu-artikel"), ("Neuer Bestand …", "#neu-bestand")):
        page.goto(live_workbench + f"/articles/{e2e_corpus.draft_ulid}/edit")
        page.click("header .menu-button")
        page.get_by_role("button", name=entry).click(timeout=5000)
        expect(page.locator(panel)).to_be_visible()
        expect(page.locator(panel).locator('input[type="text"]').first).to_be_focused()


def test_a_tool_panel_opened_from_a_menu_closes_the_menu(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The platform nests a popover opened from inside an open one, so the menu would stay open
    # under the panel (owner, 2026-09-30). Closing the panel hands focus back to the menu's button,
    # not to <body> or wherever the focus was: the entry that opened it is hidden. The menu opens
    # without focusing its button, as a click in Safari does.
    page = archivist_page
    edit = f"/articles/{e2e_corpus.draft_ulid}/edit"
    for path, menu, entry, panel in (
        (edit, "#neu-menu", "Neuer Artikel …", "#neu-artikel"),
        (edit, "#mehr-menu", "Löschen …", "#loeschen"),
        (f"/articles/{e2e_corpus.published_ulid}", "#aktionen-menu", "Löschen …", "#loeschen"),
    ):
        page.goto(live_workbench + path)
        page.locator(menu).evaluate("menu => menu.showPopover()")
        page.locator(menu).get_by_role("button", name=entry).click()
        expect(page.locator(panel)).to_be_visible()
        expect(page.locator(menu)).to_be_hidden()
        page.keyboard.press("Escape")
        expect(page.locator(panel)).to_be_hidden()
        expect(page.locator(f'[popovertarget="{menu[1:]}"]')).to_be_focused()


def test_the_count_rides_the_pager_and_a_live_swap_announces_it(
    archivist_page: Page, live_workbench: str
) -> None:
    # a2 round 10: the result count lives in the pager's range; a one-page list shows it alone. The
    # type-to-search swap replaces the pager with #results, and an aria-live element inserted with
    # its content is not announced — so the announcement lives in a node OUTSIDE the swap target
    # (#trefferzahl), refreshed out-of-band. It is silent on a full page load: nothing changed.
    page = archivist_page
    page.goto(live_workbench + LIST)
    expect(page.locator(".pager")).to_have_text("4 Artikel")  # the canonical corpus, one page
    count = page.locator("#trefferzahl")
    expect(count).to_have_text("")
    # The live region's NODE must survive the swap or the polite announcement dies silently. Stamp
    # the node with an expando — a property, so no server render can reproduce it — and look for it
    # afterwards.
    page.evaluate("() => { document.querySelector('#trefferzahl').__probe = 'same-node'; }")
    # real keystrokes (the hx-trigger is keyup; fill() sets the value without key events)
    page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
    expect(count).to_have_text("1 Treffer")  # refreshed out-of-band, no full navigation
    expect(page.locator(".pager")).to_have_text("1 Artikel")
    assert "q=Sommerfahrt" in page.url  # it was the hx swap (pushed URL), not a page load
    assert page.evaluate("() => document.querySelector('#trefferzahl').__probe") == "same-node", (
        "the count's aria-live node was replaced by the swap — announcements die silently"
    )
    # zero hits: the empty state says so, and there is no range to show
    page.goto(live_workbench + f"{LIST}?q=zzzznomatch")
    expect(page.get_by_text("Keine Treffer")).to_be_visible()
    expect(page.locator(".pager")).to_have_count(0)


def test_the_way_back_keeps_the_lists_filters(archivist_page: Page, live_workbench: str) -> None:
    # Filter by a decade and a file type (through "+ Filter"), open an article: "Archiv" leads to
    # the list as it was left. Editing and saving the article changes nothing about that.
    page = archivist_page
    page.goto(live_workbench + f"{LIST}?jahrzehnt=1960", wait_until="networkidle")
    page.locator(".search-sentence-add .menu-button").click()
    page.locator("#plus-filter").get_by_role("link", name="mit Fotos").click()
    page.wait_for_url("**file=image**")
    page.get_by_role("link", name="Sommerfahrt 1962", exact=True).click()
    page.wait_for_url("**/articles/**")
    page.locator(".crumbs").get_by_role("link", name="Archiv", exact=True).click()
    page.wait_for_url("**file=image**")
    assert "jahrzehnt=1960" in page.url
    page.get_by_role("link", name="Sommerfahrt 1962", exact=True).click()
    page.get_by_role("link", name="Bearbeiten", exact=True).click()
    page.wait_for_url("**/edit**")
    page.fill('input[name="ref_code"]', "WEG-1")
    page.click('button:has-text("Speichern")')
    page.wait_for_url(lambda url: "/edit" not in url and "/articles/" in url)
    page.locator(".crumbs").get_by_role("link", name="Archiv", exact=True).click()
    page.wait_for_url("**file=image**")
    assert "jahrzehnt=1960" in page.url


def test_a_start_page_bestand_opens_the_list_the_crumb_returns_to(
    archivist_page: Page, live_workbench: str
) -> None:
    # Start → a Bestand → its list → an article → "Archiv": the list as it was left, Bestand set;
    # the wordmark leads back to the start page.
    page = archivist_page
    page.goto(live_workbench + "/", wait_until="networkidle")
    page.locator("main").get_by_role("link", name="Bundesarchiv").click()
    page.wait_for_url(f"**{LIST}?bestand=ROOT")
    page.get_by_role("link", name="Sommerfahrt 1962", exact=True).click()
    page.wait_for_url("**/articles/**")
    page.locator(".crumbs").get_by_role("link", name="Archiv", exact=True).click()
    page.wait_for_url(f"**{LIST}?bestand=ROOT")
    page.locator(".wordmark").click()
    page.wait_for_url(lambda url: url.rstrip("/") == live_workbench.rstrip("/"))


def test_each_start_page_area_opens_the_list_with_its_preset(
    archivist_page: Page, live_workbench: str
) -> None:
    # Nach Art, Zeitleiste and Weiter bearbeiten each lead somewhere: a preset of the list, or the
    # draft's edit page.
    page = archivist_page
    for name, url_part in (("Foto(s)", "medienart="), ("1960er", "jahrzehnt=1960")):
        page.goto(live_workbench + "/", wait_until="networkidle")
        page.locator("main").get_by_role("link", name=name).first.click()
        page.wait_for_url(f"**{LIST}?*{url_part}*")
    page.goto(live_workbench + "/", wait_until="networkidle")
    page.locator(".resume").get_by_role("link").first.click()
    page.wait_for_url("**/articles/**/edit")


def test_an_old_list_link_lands_on_the_list_and_its_clear_links_stay_there(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The list's links are relative ("?…"): rendered at "/", closing the pane (an empty query)
    # would have led to the start page.
    page = archivist_page
    page.goto(f"{live_workbench}/?artikel={e2e_corpus.published_ulid}", wait_until="networkidle")
    assert urlparse(page.url).path == LIST
    page.get_by_role("link", name="Vorschau schließen").click()
    page.wait_for_url(lambda url: urlparse(url).path == LIST and "artikel" not in url)


def test_a_way_back_remembered_before_the_list_moved_is_not_followed(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # A tab that remembered the list at "/" (before it moved to LIST) keeps the crumb on the list.
    page = archivist_page
    page.goto(f"{live_workbench}/articles/{e2e_corpus.published_ulid}", wait_until="networkidle")
    page.evaluate("() => sessionStorage.setItem('list-address', '/?jahrzehnt=1960')")
    page.reload(wait_until="networkidle")
    crumb = page.locator(".crumbs").get_by_role("link", name="Archiv", exact=True)
    expect(crumb).to_have_attribute("href", LIST)


def test_sentence_links_keep_the_typed_q_after_a_live_swap(
    archivist_page: Page, live_workbench: str
) -> None:
    # The search sentence lives OUTSIDE the #results swap target, so an htmx q-swap would leave
    # every slot link rendered from the PREVIOUS request: removing a filter after typing
    # "Sommerfahrt" navigated to a query with no q and destroyed the search. One fact, one source:
    # the slots refresh out-of-band with the count, so no link describes a query the URL no longer
    # has. Both set filters here are ones no slot shows, so each is its own removing link.
    page = archivist_page
    for nth in (0, 1):
        page.goto(live_workbench + f"{LIST}?schlagwort=sommer&medienart=Foto(s)")
        page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
        page.wait_for_url("**q=Sommerfahrt**")
        expect(page.locator("#trefferzahl")).not_to_be_empty()
        link = page.locator(".search-sentence .is-set > a").nth(nth)
        assert "q=Sommerfahrt" in (link.get_attribute("href") or ""), (
            f"set filter {nth} was rendered before the q existed: {link.get_attribute('href')}"
        )
        link.click()
        page.wait_for_load_state()
        assert "q=Sommerfahrt" in page.url, (
            f"removing set filter {nth} destroyed the search: {page.url}"
        )


def test_on_a_phone_the_folded_slots_stay_reachable(
    archivist_page: Page, live_workbench: str
) -> None:
    # Review U4 (blocking): on S the unset Jahrzehnt and Typ slots fold away; "Filter" must still
    # reach them, or a phone cannot filter by decade or type at all.
    page = archivist_page
    page.set_viewport_size({"width": 390, "height": 900})
    for param in ("jahrzehnt", "dokumenttyp"):
        page.goto(live_workbench + LIST)
        page.locator(".search-sentence-more .menu-button").click()
        entry = page.locator(f'.search-sentence-more .menu a[href*="{param}="]').first
        expect(entry).to_be_visible()
        entry.click()
        page.wait_for_url(f"**{param}=**")


def test_pane_open_never_folds_the_ledger(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # Decision 1 (owner 2026-08-07), proven computed (learning G.1): at the NARROWEST viewport
    # that still shows the pane (the 80rem switch = 1280px at default root font), the pane-open
    # ledger keeps its one-line row anatomy — the header row stays visible (the phone fold is
    # the only state that hides it) and the tracks merely tighten (law C11 — no column drops).
    page = archivist_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_workbench + f"{LIST}?artikel={e2e_corpus.published_ulid}")
    expect(page.locator(".pane")).to_be_visible()
    expect(page.locator(".ledger thead")).to_be_visible()  # the fold's signature is hidden heads


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
_LONG_TYP = max(vocab.DOKUMENTTYPEN, key=len)  # derived: the vocabulary IS the ceiling here
#: Long HERKUNFT values: an institutional author and a full place name.
_LONG_CREATOR = "Bundesleitung des Bundes Deutscher Pfadfinderinnen, Referat Öffentlichkeitsarbeit"
_LONG_PLACE = "Burg Rieneck im Sinntal, Unterfranken"
_LONG_ULID = "01KXE2E1ANG0000000000000AA"


def _seed_long_content(root: Path, blocker: DjangoDbBlocker) -> None:
    """Add ONE article whose fields are as long as real archive content gets: a Signatur at the
    8-character ceiling, an unbounded free-text Titel, the widest vocabulary Dokumenttyp, a full-date
    EDTF interval, and an institutional Autor/Ort pair. Seeded per test (not into the shared corpus)
    so the count-asserting journeys keep their canonical hit count."""
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
            media_type="Gegenstand",
            document_type=_LONG_TYP,
            date=EdtfDate("1948-01-01/1952-12-31"),
            tags=("pfingstlager",),
            creator=_LONG_CREATOR,
            subject_place=_LONG_PLACE,
        ),
        0,
        changed_by="tester",
    )
    with blocker.unblock():
        indexer.rebuild(store)


#: The ledger's OWN horizontal overflow. It is the last-resort scroll box, so it CAN scroll — but a
#: scrolling ledger hides columns, which is exactly what law C11 forbids, so this must stay zero.
_LEDGER_OVERFLOW_JS = """() => {
    const t = document.querySelector('.ledger');
    return t.scrollWidth - t.clientWidth;
}"""

#: The DOCUMENT's horizontal overflow — ledger.html's standing contract is "the page body never
#: scrolls sideways" (the [role=table] may scroll in its OWN box; the page may not).
_DOC_OVERFLOW_JS = """() => {
    const d = document.documentElement;
    return {overflow: d.scrollWidth - d.clientWidth,
            scrollX: (window.scrollTo(99999, 0), window.scrollX)};
}"""


def _sideways_scroll_defects(
    page: Page,
    cases: tuple[tuple[int, str], ...],
    extra: Callable[[Page], list[str]] | None = None,
) -> list[str]:
    """The standing contract, ONE walker for every surface that has to keep it: the PAGE BODY never
    scrolls sideways, at each (width, url) in ``cases``. Both long-content proofs need it — the record
    card's was a clone of the ledger's tail, driven by the same seed — so the walk lives once and each
    caller passes its own ``extra`` probe (the ledger's own scroll box and its wrapping Titel) to run
    inside the same navigation rather than paying for a second pass."""
    defects: list[str] = []
    for width, url in cases:
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(url)
        doc: dict[str, float] = page.evaluate(_DOC_OVERFLOW_JS)
        if doc["overflow"] > 1 or doc["scrollX"] > 1:
            defects.append(f"{width}px: the page body scrolls sideways {doc}")
        if extra is not None:
            defects.extend(f"{width}px: {d}" for d in extra(page))
    return defects


#: Does the long TITEL give its width back? It is the elastic column and the archive's one unbounded
#: field, and every other cell keeps its line (round 10) — so it WRAPS: its link spans more than one
#: line box. If it never wraps, the facts cannot keep their line and the table overflows instead.
#: The seeded long row is the only Titel over 60 characters, so it is found by length rather than by
#: a duplicated literal.
_LONG_TITEL_LINES_JS = """() => {
    const link = [...document.querySelectorAll('.ledger td.titel > a:first-child')]
        .find((e) => e.textContent.trim().length > 60);
    if (!link) throw new Error('the long-Titel row is not on this page');
    return link.getClientRects().length;
}"""


def test_ledger_absorbs_long_content_without_hiding_a_value(
    archivist_page: Page,
    live_workbench: str,
    e2e_corpus: CorpusHandles,
    _e2e_root: Path,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    # Law C11 (intrinsic first): the ledger drops no column. The Titel wraps, every other cell keeps
    # its line and a word cell ends in "…" (round 10). G.24's red case stays pinned: long content must
    # never push the PAGE BODY into sideways scroll. Hence the long-content seed — the short demo
    # corpus made this proof pass vacuously. WHAT is long follows the domain (owner, 2026-08-07): a
    # Signatur has no spaces and tops out around 8 characters, and Typ comes from the vocabulary —
    # the TITEL is the one genuinely unbounded field, so it carries the pressure.
    _seed_long_content(_e2e_root, django_db_blocker)
    page = archivist_page
    for width, path in (
        (680, LIST),
        (1280, f"{LIST}?artikel={e2e_corpus.published_ulid}"),
    ):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(live_workbench + path)
        for col in ("titel", "datierung", "typ", "digital", "signatur"):
            expect(page.locator(f".ledger td.{col}").first).to_be_visible()

    def ledger_probes(current: Page) -> list[str]:
        found: list[str] = []
        overflow: int = current.evaluate(_LEDGER_OVERFLOW_JS)
        if overflow > 1:
            found.append(f"the ledger overflows its own box by {overflow}px")
        lines: int = current.evaluate(_LONG_TITEL_LINES_JS)
        if lines < 2:
            found.append(f"the long Titel never wrapped ({lines} line box)")
        return found

    defects = _sideways_scroll_defects(
        page,
        (
            (560, live_workbench + LIST),
            (640, live_workbench + LIST),
            (800, live_workbench + LIST),
            (1280, live_workbench + f"{LIST}?artikel={e2e_corpus.published_ulid}"),
        ),
        ledger_probes,
    )
    assert not defects, "the ledger does not absorb long content intrinsically:\n" + "\n".join(
        defects
    )
    # S (the space budget's container size): the heads go and each row is its title over one line
    # of its facts. The fold is a form, not a drop: it hides no value (G.33).
    page.set_viewport_size({"width": 500, "height": 900})
    page.goto(live_workbench + LIST)
    expect(page.locator(".ledger thead")).to_be_hidden()
    long_row = page.locator(".ledger tbody tr", has_text=_CEILING_REF_CODE)
    for col in ("datierung", "typ", "signatur"):
        expect(long_row.locator(f"td.{col}")).to_be_visible()


def test_public_never_sees_a_draft(public_page: Page, live_workbench: str) -> None:
    # the leak spine, end to end: a public visitor's workbench shows the published articles but never
    # the draft (search scopes it out) and no archivist chrome (no bulk column, no "+ Neu …" create
    # menu — Mock B, owner 2026-08-07).
    public_page.goto(live_workbench + LIST)
    expect(public_page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(public_page.get_by_text("Lagerchronik")).not_to_be_visible()  # the draft's title
    expect(public_page.get_by_role("button", name="+ Neu …")).to_have_count(0)
    expect(public_page.locator('input[name="auswahl"]')).to_have_count(0)


def test_an_anonymous_visitor_signs_in_through_the_door(
    public_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    reach_door(public_page, live_workbench, e2e_corpus)
    public_page.get_by_role("link", name="Anmelden mit DPB Login").click()
    public_page.wait_for_url("**/login?**")
    assert_login_target(public_page.url, f"/articles/{e2e_corpus.published_ulid}")


def test_static_assets_serve_in_the_live_server(public_page: Page, live_workbench: str) -> None:
    # A 404'd stylesheet renders an unstyled page the gallery's size-only assertion cannot catch.
    page = public_page
    page.goto(live_workbench + LIST)
    refs = page.eval_on_selector_all(
        "link[rel=stylesheet], script[src]", "els => els.map(e => e.href || e.src)"
    )
    static_urls = [u for u in refs if "/static/" in u]
    assert static_urls, "the workbench references no /static/ assets"
    for url in static_urls:
        assert page.request.get(url).status == 200, url


# --- detail read view (4.6) --------------------------------------------------------


def test_detail_read_from_search_result(public_page: Page, live_workbench: str) -> None:
    page = public_page
    # a member/public visitor: the Titel click IS the navigation to the Lesesaal detail read view
    # (one-click entry, owner 2026-08-07 — no pane interception, no JS in the loop).
    page.goto(live_workbench + LIST)
    page.get_by_role("link", name="Sommerfahrt 1962", exact=True).click()
    page.wait_for_url("**/articles/**")
    # the reading structure: title, the origin line (Signatur, date), the cover Platte
    expect(page.locator("main h1")).to_have_text("Sommerfahrt 1962")
    expect(page.locator("main time")).to_have_attribute("datetime", "1962-07")
    expect(page.get_by_text("F12")).to_be_visible()  # Signatur (no spaces — the domain fact)
    expect(page.locator("main .platte img")).to_be_visible()  # cover Platte
    expect(page.locator(".filmstrip figure")).to_have_count(2)  # the two files after the cover
    # a plate links its gated media byte route; the crumbs lead back into the list
    href = page.locator(".filmstrip figure > a").first.get_attribute("href")
    assert href is not None and href.startswith("/media/")
    page.get_by_role("link", name="Archiv", exact=True).click()
    page.wait_for_url(lambda url: url.endswith(LIST))


def test_herunterladen_saves_the_original_under_its_own_name(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # The original is one click away (owner, 2026-10-01): the media route answers inline (ADR
    # 0017's Content-Disposition and sandbox), and the download attribute still saves it, named.
    page = archivist_page
    page.goto(live_workbench + f"/articles/{e2e_corpus.ceiling_ulid}")
    with page.expect_download() as saved:
        page.locator(".platte").get_by_role("link", name="Herunterladen").click()
    assert saved.value.suggested_filename == MINUTES_FILENAME


# --- create a Bestand (4.8) --------------------------------------------------------


def test_create_bestand_then_file_an_article_under_it(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # "+ Neu …" → "Neuer Bestand …" (its panel) → fill Name → Anlegen → LAND on the create-article form
    # (create→catalog is one flow), the new Bestand pre-selected + a success hinweis. File the
    # first article under it. The create actions live in the header's ONE menu (Mock B, owner
    # 2026-08-07) — a native popover, opened by a plain click.
    page.goto(live_workbench + LIST)
    page.click(".menu-button")
    page.get_by_role("button", name="Neuer Bestand …").click()
    panel = page.locator("#neu-bestand")
    panel.locator('input[name="name"]').fill("Plakate")
    panel.get_by_role("button", name="Anlegen").click()
    page.wait_for_url("**/articles/new?**")  # HX-Redirect to the create-article form, not the list
    expect(page.get_by_text("Bestand „Plakate“ angelegt.")).to_be_visible()  # success hinweis
    expect(page.locator('main select[name="collection_id"]')).to_contain_text("Plakate")
    page.fill('textarea[name="title"]', "Ein Plakat")  # the new Bestand is already pre-selected
    page.click('main button:has-text("Anlegen")')
    page.wait_for_url("**/edit**")
    # now the Bestand has an article, so it appears in the search sentence's Bestand slot menu
    page.goto(live_workbench + LIST)
    page.locator(".search-sentence-slots .menu-button").first.click()
    expect(page.locator(".search-sentence .menu a", has_text="Plakate")).to_be_visible()


# --- create a draft ----------------------------------------------------------------


def _create_draft(page: Page, base: str, title: str) -> str:
    """Drive the create step (Titel + Bestand → Anlegen) then set the required Medienart on the edit
    form, so the draft is saveable/publishable. Returns the new draft's edit-form URL."""
    page.goto(base + "/articles/new")
    page.fill('textarea[name="title"]', title)
    page.select_option('main select[name="collection_id"]', "FOTOS")
    page.click('main button:has-text("Anlegen")')
    page.wait_for_url("**/edit**")
    # Medienart is required to save/publish (spec §3) — set it so downstream steps aren't blocked.
    page.select_option('select[name="media_type"]', "Foto(s)")
    return page.url


def test_create_draft_lands_on_edit_form(archivist_page: Page, live_workbench: str) -> None:
    edit_url = _create_draft(archivist_page, live_workbench, "E2E Neuer Entwurf")
    assert "/edit" in edit_url
    # the edit form is seeded with the new title, its Status a draft
    expect(archivist_page.locator('textarea[name="title"]')).to_have_value("E2E Neuer Entwurf")
    expect(archivist_page.locator('select[name="lifecycle"]')).to_have_value("draft")


# --- edit + save -------------------------------------------------------------------


def test_edit_and_save_redirects_to_read_view(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Zu Bearbeiten")
    page.fill('input[name="ref_code"]', "E2E-1")
    page.fill('input[name="creator"]', "K. Meyer")
    # Saved by pressing ENTER in a field, not by clicking: Speichern lives in the form's margin,
    # OUTSIDE #bearbeiten-form's subtree and associated to it by form=. Implicit submission still has
    # to find Speichern as the form's default button, and Speichern applies the Status (a1 round 4):
    # Enter publishes exactly when the archivist set Veröffentlicht. Every other journey clicks.
    page.select_option('select[name="lifecycle"]', "published")
    page.click('input[name="ref_code"]')
    page.keyboard.press("Enter")
    # save 302s to the read view
    page.wait_for_url(lambda url: "/edit" not in url and "/articles/" in url)
    expect(page.get_by_text("E2E-1")).to_be_visible()  # Enter saved the form...
    expect(page.get_by_text("Entwurf", exact=True)).to_have_count(0)  # ...and applied the Status


def test_failed_save_banner_leaves_speichern_clickable(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # A failed save reveals the global error banner, fixed at the viewport BOTTOM. On L the form's
    # margin, which holds Speichern, is sticky at the TOP, so the recorded regression class — a
    # Speichern occluded by the banner at exactly the moment the archivist needs to retry — cannot
    # occur there. This journey pins that: while the banner is up, a real browser hit-test at
    # Speichern's center still reaches the button, and the retry fires again.
    page.set_viewport_size({"width": 1440, "height": 900})
    _create_draft(page, live_workbench, "E2E Fehlschlag")

    def fail_saves(route: Route) -> None:
        # abort only the save POSTs; the edit page's own GET (same URL) must keep loading normally
        if route.request.method == "POST":
            route.abort()
        else:
            route.fallback()

    page.route("**/edit", fail_saves)
    page.click('button:has-text("Speichern")')  # htmx:error → the banner reveals
    expect(page.get_by_text("Aktion fehlgeschlagen. Bitte erneut versuchen.")).to_be_visible()
    # Scrolled to the very bottom — the harshest position for a viewport-bottom banner — the margin
    # is still pinned at the top and its Speichern is still the topmost element at its own center. A bare page.click cannot pin this: Playwright's actionability retry scrolls an
    # occluded element into a clickable position and the click lands anyway.
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    state = page.evaluate(
        """() => {
        const banner = document.querySelector('.error-banner');
        const btn = document.querySelector('.record-meta button.primary');
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
        f"the margin overlaps the banner: Speichern bottom {state['speichernBottom']}px "
        f"vs banner top {state['bannerTop']}px"
    )
    # and the retry itself works end to end: the second Speichern fires another save while the
    # banner stays visible through it (the error is never sacrificed to keep the button clickable)
    page.click('button:has-text("Speichern")', timeout=5000)
    expect(page.get_by_text("Aktion fehlgeschlagen. Bitte erneut versuchen.")).to_be_visible()


def test_a_denied_save_swaps_nothing_and_a_later_success_hides_the_banner(
    archivist_page: Page, live_workbench: str
) -> None:
    # A deny is an empty 404. Swapped through hx-select="#form-region" it would replace the whole
    # edit region with nothing and take the unsaved edits with it; htmx 4 swaps non-2xx unless the
    # htmx-config meta in base.html says otherwise.
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Verweigert")
    page.fill('textarea[name="title"]', "E2E Ungespeichert")

    def deny_saves(route: Route) -> None:
        if route.request.method == "POST":
            route.fulfill(status=404, body="")
        else:
            route.fallback()

    page.route("**/edit", deny_saves)
    page.click('button:has-text("Speichern")')
    banner = page.get_by_text("Aktion fehlgeschlagen. Bitte erneut versuchen.")
    expect(banner).to_be_visible()
    expect(page.locator('textarea[name="title"]')).to_have_value("E2E Ungespeichert")
    # a later success hides it: a validation re-render is a 200 that stays on the page
    page.unroute("**/edit")
    page.fill('textarea[name="title"]', "")
    page.click('button:has-text("Speichern")')
    expect(page.locator(".form-sheet .error").first).to_be_visible()
    expect(banner).to_be_hidden()


# --- dirty register (PE)-----------------------------------------------------------


def test_dirty_register_covers_fields_outside_the_form_subtree(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # Custom-bag fields are form= ASSOCIATED with #bearbeiten-form but sit outside its
    # DOM subtree (the #medien-drawer split) — the dirty register must still see their first edit.
    edit_url = _create_draft(page, live_workbench, "E2E Ungespeichert")
    page.goto(edit_url)  # fresh load: _create_draft's Medienart pick already revealed the chip
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_hidden()
    page.click('button:has-text("+ Angabe hinzufügen")')
    page.fill('input[name="custom_key"]', "Quelle")
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_visible()
    # and the plain path still works: a field inside the form reveals it too
    page.goto(edit_url)
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_hidden()
    page.fill('input[name="ref_code"]', "E2E-U2")
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_visible()


def test_a_schlagwort_is_taken_from_the_suggestions_with_the_keyboard(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    reach_schlagwort_suggestions(page, live_workbench, e2e_corpus)
    field = page.locator("main #feld-tags")
    options = page.locator('.autocomplete-list [role="option"]')
    # "lager" is on the field already, so only the corpus's other two
    expect(options).to_have_text(["fahrt", "sommer"])
    hangs = page.evaluate(
        """() => {
        const list = document.querySelector('.autocomplete-list').getBoundingClientRect();
        const field = document.querySelector('#feld-tags').getBoundingClientRect();
        return list.top >= field.bottom && list.left >= field.left && list.right <= field.right;
    }"""
    )
    assert hangs, "the suggestion list does not hang under its field"
    page.keyboard.press("Escape")
    expect(page.locator(".autocomplete-list")).to_be_hidden()
    page.keyboard.press("Backspace")
    field.press_sequentially("so")
    expect(options).to_have_text(["sommer"])
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.locator(".autocomplete-list")).to_be_hidden()
    expect(field).to_have_value("lager\nsommer")
    page.click('main button:has-text("Speichern")')
    page.wait_for_url(f"**/articles/{e2e_corpus.second_ulid}")
    expect(page.locator('main dt:has-text("Schlagworte") + dd a')).to_have_text(["lager", "sommer"])


def test_moving_the_caret_off_the_line_ends_the_offer_and_changes_nothing(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    reach_schlagwort_suggestions(page, live_workbench, e2e_corpus)  # "lager" / "r"
    field = page.locator("main #feld-tags")
    page.locator('.autocomplete-list [role="option"]').first.wait_for()
    # a click into line 1: the list closes, so Enter is a plain newline and nothing is replaced
    field.click(position={"x": 8, "y": 8})
    expect(page.locator(".autocomplete-list")).to_be_hidden()
    expect(field).to_have_value("lager\nr")
    # the caret at 0 over a leading empty line: the same, and no error
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    field.fill("\n")
    field.press_sequentially("r")
    expect(page.locator(".autocomplete-list")).to_be_visible()
    field.evaluate("(el) => el.setSelectionRange(0, 0)")
    expect(page.locator(".autocomplete-list")).to_be_hidden()
    page.keyboard.press("Enter")
    assert not errors


def test_a_suggestion_is_not_taken_into_a_line_whose_text_changed(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    reach_schlagwort_suggestions(page, live_workbench, e2e_corpus)  # "lager" / "r"
    field = page.locator("main #feld-tags")
    page.keyboard.press("ArrowDown")  # an option is marked
    # the line changes under the open list without a key (a script, an extension)
    field.evaluate("(el) => { el.value = 'lager\\nrx'; }")
    page.keyboard.press("Enter")
    expect(field).to_have_value("lager\nrx")
    expect(page.locator(".autocomplete-list")).to_be_hidden()


def test_the_live_region_speaks_only_for_matches(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    reach_schlagwort_suggestions(page, live_workbench, e2e_corpus)
    status = page.locator("#feld-tags-vorschlaege-status")
    expect(status).to_have_text("2 Vorschläge")
    page.locator("main #feld-tags").press_sequentially("zzzq")
    expect(page.locator(".autocomplete-list")).to_be_hidden()
    expect(status).to_have_text("")
    # a failed request is as silent as a miss
    page.route("**/tags/suggestions*", lambda route: route.fulfill(status=500))
    page.locator("main #feld-tags").press_sequentially("x")
    page.wait_for_timeout(500)
    expect(status).to_have_text("")


def test_a_stale_failed_request_leaves_the_newer_list_open(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    reach_schlagwort_suggestions(page, live_workbench, e2e_corpus)  # "r" on the last line

    held: list[Route] = []

    def hold_rx(route: Route) -> None:
        if "q=rx" in route.request.url:
            held.append(route)  # answered by the test, after the newer request
        else:
            route.continue_()

    page.route("**/tags/suggestions*", hold_rx)
    field = page.locator("main #feld-tags")
    field.press_sequentially("x")  # "rx": its request hangs
    expect(page.locator(".autocomplete-list")).to_be_hidden()
    page.wait_for_timeout(300)  # past the debounce, the request is out
    page.keyboard.press("Backspace")  # "r" again: a newer request, answered at once
    expect(page.locator(".autocomplete-list")).to_be_visible()
    held[0].abort()  # the old request fails late
    page.wait_for_timeout(500)
    expect(page.locator(".autocomplete-list")).to_be_visible()


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
    page2.select_option('select[name="media_type"]', "Foto(s)")

    # archivist 1 saves first (wins)
    archivist_page.fill('input[name="creator"]', "Erster")
    archivist_page.click('button:has-text("Speichern")')
    archivist_page.wait_for_url(lambda url: "/edit" not in url)

    # archivist 2 saves the now-stale form → the conflict panel appears inline, values preserved
    page2.fill('input[name="creator"]', "Zweiter")
    page2.click('button:has-text("Speichern")')
    expect(page2.get_by_text("Inzwischen geändert")).to_be_visible()
    # the re-render preserves every submitted value
    expect(page2.locator('input[name="creator"]')).to_have_value("Zweiter")
    ctx2.close()


# --- Duplizieren loop --------------------------------------------------------------


def test_kopieren_creates_draft_copy_signatur_focused(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # from the published article's page, Duplizieren (in Bearbeiten's menu) → a fresh draft's edit
    # form, Signatur focused
    page.goto(live_workbench + f"/articles/{e2e_corpus.published_ulid}")
    page.get_by_label("Weitere Aktionen").click()
    page.click('button:has-text("Duplizieren")')
    page.wait_for_url("**/edit**")
    # the copy cleared the Signatur (ref_code) and the field is focused (spec §5)
    expect(page.locator('input[name="ref_code"]')).to_have_value("")
    expect(page.locator('input[name="ref_code"]')).to_be_focused()
    # title carried over
    expect(page.locator('textarea[name="title"]')).to_have_value("Sommerfahrt 1962")


# --- Löschen, the Papierkorb (ADR 0022) ---------------------------------------------


def _delete_new_draft(page: Page, base: str, title: str) -> None:
    """A new draft, put in the Papierkorb from its article page's "Löschen …"."""
    _create_draft(page, base, title)
    ulid = page.url.split("/articles/")[1].split("/")[0]
    page.goto(base + f"/articles/{ulid}")
    page.get_by_label("Weitere Aktionen").click()
    page.click('[popovertarget="loeschen"]')
    panel = page.locator("#loeschen")
    expect(panel).to_be_visible()
    panel.locator('button[type="submit"]').click()
    page.wait_for_url(lambda url: url.endswith(LIST))  # → the list


def test_a_deleted_article_waits_in_the_papierkorb_and_comes_back(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    title = "E2E Wiederzuholen"
    _delete_new_draft(page, live_workbench, title)
    expect(page.locator("main")).not_to_contain_text(title)
    page.locator("main [role=toolbar]").get_by_role("link", name="Papierkorb").click()
    page.get_by_role("button", name=f"Wiederherstellen: {title}").click()
    page.wait_for_url("**/articles/*")
    page.goto(live_workbench + LIST)
    expect(page.locator("main").get_by_role("link", name=title, exact=True)).to_be_visible()


def test_delete_permanently_removes_it_from_the_papierkorb(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    title = "E2E Endgültig weg"
    _delete_new_draft(page, live_workbench, title)
    page.goto(live_workbench + "/trash")
    detail = page.locator("main").get_by_role("link", name=title, exact=True).get_attribute("href")
    page.get_by_role("link", name=f"Endgültig löschen: {title}").click()
    page.locator("main form button[type=submit]").click()
    page.wait_for_url("**/trash")
    expect(page.locator("main")).not_to_contain_text(title)
    gone = page.goto(live_workbench + str(detail))
    assert gone is not None and gone.status == 404


# --- publish -------------------------------------------------------------------------


def test_publish_from_the_article_page_confirms_first(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # a3 round 7: Veröffentlichen opens a confirmation saying who will see the record; Esc cancels,
    # Jetzt veröffentlichen publishes and lands on the published page.
    _create_draft(page, live_workbench, "E2E Vom Artikel veröffentlicht")
    page.click('button:has-text("Speichern")')
    page.wait_for_url(lambda url: "/edit" not in url and "/articles/" in url)
    panel = page.locator("#veroeffentlichen")
    expect(panel).to_be_hidden()
    page.click('button:has-text("Veröffentlichen")')
    expect(panel).to_contain_text("Nach dem Veröffentlichen ist dieser Artikel öffentlich.")
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    page.click('button:has-text("Veröffentlichen")')
    page.click('button:has-text("Jetzt veröffentlichen")')
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="Veröffentlichen", exact=True)).to_have_count(0)


def test_publish_by_status_saves_the_form(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    # SAVING IS PART OF PUBLISHING (owner decision 2026-08-08): the Status select sits in the margin
    # (a1 round 4), so the archivist sets it with unsaved edits on screen, and Speichern must write
    # both. Type into two fields — one inside #bearbeiten-form's subtree and one OUTSIDE it (the
    # media/custom split), because they are wired to the form differently — then publish and find
    # both on the read view.
    _create_draft(page, live_workbench, "E2E Zu Veröffentlichen")
    page.fill('input[name="ref_code"]', "E2E-42")
    page.click(
        'button:has-text("+ Angabe hinzufügen")'
    )  # a round trip that keeps the Signatur typed
    page.fill('input[name="custom_key"]', "Quelle")
    page.fill('input[name="custom_value"]', "Privatbesitz Meyer")
    page.select_option('select[name="lifecycle"]', "published")
    page.click('button:has-text("Speichern")')
    # straight to the read view, published — no panel, no checkbox, no second step
    page.wait_for_url(lambda url: "/edit" not in url and "/articles/" in url)
    expect(page.get_by_text("Entwurf", exact=True)).to_have_count(0)
    expect(page.get_by_text("E2E-42")).to_be_visible()  # the unsaved Signatur survived
    expect(page.get_by_text("Privatbesitz Meyer")).to_be_visible()  # ...and the custom row


# --- bulk select → confirm → result ------------------------------------------------


def test_bulk_select_confirm_apply(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # The cold start: no checkbox column until "Auswählen" turns selection mode on. Ticks move the
    # live count → "Feld ändern …" → choose a field → Änderung prüfen posts the checked boxes →
    # confirm → apply.
    page.goto(live_workbench + LIST)
    expect(page.locator('input[name="auswahl"]')).to_have_count(0)
    page.get_by_role("link", name="Auswählen").click()
    page.wait_for_url("**auswahl=**")
    # the head box ticks every row on the page and unticks them again
    rows = page.locator('input[name="auswahl"]')
    page.check('input[name="alle"]')
    expect(page.locator('input[name="auswahl"]:checked')).to_have_count(rows.count())
    page.uncheck('input[name="alle"]')
    expect(page.locator('input[name="auswahl"]:checked')).to_have_count(0)
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()  # JS live count on tick
    page.click('[popovertarget="feld-aendern"]')
    expect(page.locator("#feld-aendern")).to_be_visible()
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    # the confirm page lists the field + count; apply → the result page
    expect(page.locator(BULK_COMMIT)).to_be_visible()  # the check page
    page.click(BULK_COMMIT)
    expect(page.locator(BULK_COMMIT)).to_have_count(0)  # the result page


def test_bulk_chooser_shows_exactly_one_value_widget(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # The chooser's contract, on both surfaces that render it: the chosen Feld's widget and no other.
    # The confirm page's error mode sits in a .column, whose field rule once outranked the hide.
    page.goto(
        live_workbench
        + f"{LIST}?auswahl={e2e_corpus.published_ulid}&auswahl={e2e_corpus.second_ulid}"
    )
    page.click('[popovertarget="feld-aendern"]')
    widgets = page.locator("[data-bulk-wert]:visible")
    page.select_option('select[name="feld"]', "media_type")
    expect(widgets).to_have_count(1)
    page.select_option('select[name="wert_media_type"]', "")
    page.click('button:has-text("Änderung prüfen")')
    expect(page.locator(".column .error")).to_be_visible()
    expect(widgets).to_have_count(1)
    page.select_option('select[name="feld"]', "creator")
    expect(widgets).to_have_count(1)
    expect(page.locator('input[name="wert_text"]')).to_be_visible()


def test_bulk_url_seeded_selection_still_works(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # The pagination-persistence path: a selection seeded in the URL (?auswahl=) renders the
    # selection mode with the count + confirm flow.
    page.goto(
        live_workbench
        + f"{LIST}?auswahl={e2e_corpus.published_ulid}&auswahl={e2e_corpus.second_ulid}"
    )
    expect(page.locator(".bulk")).to_be_visible()
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()  # server-rendered count
    page.click('[popovertarget="feld-aendern"]')
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    expect(page.locator(BULK_COMMIT)).to_be_visible()  # the check page


def test_bulk_enhancement_survives_a_history_restore(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    # Learning G.25, restated for htmx 4: Back after an htmx search is ONE server GET that swaps the
    # whole workbench body. Only after it lands, the page states the URL's selection (none), the
    # bulk enhancement is wired to the fresh nodes, type-to-search works again, and no script re-ran
    # (the same htmx instance). (Under htmx 2 the restore came from a localStorage snapshot that
    # carried the enhancement's stale leftovers — the defect this journey was born from.)
    page = archivist_page
    page.goto(live_workbench + f"{LIST}?auswahl=")
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()
    # a live search pushes a history entry
    page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
    page.wait_for_url("**q=Sommerfahrt**")
    page.evaluate("() => { window.__htmxAtLoad = htmx; }")
    page.go_back()
    page.wait_for_url(lambda url: "q=Sommerfahrt" not in url)
    # the restore is a server GET that swaps the body; judge nothing before the full ledger is back
    expect(page.get_by_text("Herbstlager 1963")).to_be_visible()
    # the restored page states the URL's selection (none), never the snapshot's stale count
    expect(page.locator('input[name="auswahl"]:checked')).to_have_count(0)
    expect(page.get_by_text("ausgewählt")).to_have_count(0)
    # ...and the enhancement is WIRED again: a fresh tick moves the live count
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(page.get_by_text("1 ausgewählt")).to_be_visible()
    # the TYPE-TO-SEARCH enhancement has to survive the same restore: it lives on #results (the
    # region it swaps), which the restore replaces, so the new #results must be processed (H.8/G.25).
    page.locator('input[name="q"]').press_sequentially("Herbstlager")
    page.wait_for_url("**q=Herbstlager**")
    expect(page.get_by_text("Herbstlager 1963")).to_be_visible()
    # the swap announced its count through the node outside #results
    expect(page.locator("#trefferzahl")).to_have_text("1 Treffer")
    # htmx 4 re-runs the <script>s of swapped content; a restore swaps the body, so a script there
    # would start a second htmx (and every later Back would restore twice)
    assert page.evaluate("() => htmx === window.__htmxAtLoad"), "the restore re-ran htmx.min.js"


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
                media_type="Foto(s)",
            ),
            0,
            changed_by="tester",
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
    # state into the prev/next links on every change, so the URL stays the canonical shareable
    # state — the landed page renders exactly as a cold visit to it would.
    _seed_second_page(_e2e_root, django_db_blocker)
    page = archivist_page
    # land with a URL-seeded selection (the no-JS-persisted baseline state)
    page.goto(live_workbench + f"{LIST}?auswahl={e2e_corpus.published_ulid}")
    seeded = page.locator(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(seeded).to_be_checked()
    # a fresh tick + a fresh UNTICK of the URL-seeded item — both unsubmitted, DOM-only
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    seeded.uncheck()
    # "Abbrechen" is NEVER rewritten — its purpose is leaving selection mode
    abbrechen_href = page.get_by_role("link", name="Abbrechen").get_attribute("href")
    assert "auswahl" not in (abbrechen_href or "")
    page.click('a[rel="next"]')
    page.wait_for_url("**seite=2**")
    # the URL carries the fresh state: the tick travelled, the untick stuck
    assert e2e_corpus.second_ulid in _auswahl_in_url(page)
    assert e2e_corpus.published_ulid not in _auswahl_in_url(page)
    # ...and the archivist can SEE it here. Learning G.25: the progressive-visibility JS counted
    # only THIS page's checkboxes, so an off-page selection (nothing ticked on page 2) was hidden
    # at wire time, stranding the selection. Asserted BEFORE any tick on this page.
    expect(page.locator('input[name="auswahl"]:checked')).to_have_count(0)  # none of it is here
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
    # "Abbrechen" leaves selection mode from either page and drops both pages' ulids
    page.get_by_role("link", name="Abbrechen").click()
    expect(page.locator('input[name="auswahl"]')).to_have_count(0)
    assert "auswahl" not in urlparse(page.url).query


# --- edit form guards ----------------------------------------------------------------

#: Every field on the edit surface that CARRIES AN ERROR, with its control's four border colors and
#: the ink its own error message computes. Written as a WALKER over all errored fields (learning
#: G.21 — never one instance), and comparing against the message's OWN ink rather than a colour
#: constant, so the proof reads "the border is the error ink" in whatever mode/theme resolved it.
_ERROR_FIELD_WALKER_JS = """() => {
    const fields = document.querySelectorAll('.form-sheet .field:has(.error)');
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
    # Law C13 / learning G.29, proven computed: a field carrying an error must out-rank the resting
    # look and actually draw the red border (a form wave mock bug: an error border that existed in
    # the stylesheet and was invisible on screen). In SOURCE an out-ranked state rule is
    # indistinguishable from a correct one, so the only honest check is the browser's.
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Fehlerhaft")
    page.select_option('select[name="media_type"]', "")  # Medienart is required
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


def test_a_gruppen_error_shows_in_the_margin_with_the_focus(
    archivist_page: Page, live_workbench: str
) -> None:
    # Gruppen shows only while Sichtbarkeit says Gruppe(n) (CSS :has). An empty Gruppen at that rung
    # re-renders the message in the margin, and the caret must land on the input — "on screen" and
    # "focused" are browser facts.
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Fehler am Rand")
    gruppen = page.locator('main textarea[name="gruppen"]')
    expect(gruppen).to_be_hidden()  # not at the GROUPS rung
    # Gruppen stays empty -> invalid
    page.select_option('main select[name="sichtbarkeit"]', "groups")
    expect(gruppen).to_be_visible()
    page.click('main button:has-text("Speichern")')
    error = page.locator(".record-meta .error")
    expect(error).to_have_text("Bitte mindestens eine Gruppe angeben.")
    expect(page.locator('main textarea[name="gruppen"]')).to_be_focused()


def test_weitere_angaben_adds_and_removes_rows_by_round_trip(
    archivist_page: Page, live_workbench: str
) -> None:
    # The bag renders no empty pair; "+ Angabe hinzufügen" and the remove cross are submits the
    # server answers with the region re-rendered, so the swap must keep the caret in the new row.
    page = archivist_page
    page.goto(_create_draft(page, live_workbench, "E2E Fachwerk"))
    rows = page.locator("#custom-bag .pairs")
    expect(rows).to_have_count(0)
    page.click('button:has-text("+ Angabe hinzufügen")')
    expect(rows).to_have_count(1)
    expect(rows.first.locator('input[name="custom_key"]')).to_be_focused()
    page.keyboard.type("Quelle")
    page.click('button:has-text("+ Angabe hinzufügen")')
    expect(rows).to_have_count(2)
    expect(rows.first.locator('input[name="custom_key"]')).to_have_value("Quelle")
    expect(rows.last.locator('input[name="custom_key"]')).to_be_focused()
    page.keyboard.type("Fotograf")
    rows.first.get_by_role("button", name="Quelle entfernen").click()
    expect(rows).to_have_count(1)
    expect(rows.first.locator('input[name="custom_key"]')).to_have_value("Fotograf")


def test_a_chosen_file_uploads_at_once_and_its_removal_asks_first(
    archivist_page: Page, live_workbench: str
) -> None:
    # With JS the "+ Dateien hinzufügen" label over the hidden input is the whole upload, and the
    # remove cross deletes for good only after the browser's own confirm.
    page = archivist_page
    page.goto(_create_draft(page, live_workbench, "E2E Hochladen"))
    expect(page.locator('#medien-drawer button:has-text("Hochladen")')).to_be_hidden()
    page.set_input_files(
        '#medien-drawer input[type="file"]',
        {"name": "neu.png", "mimeType": "image/png", "buffer": _png((10, 20, 30))},
    )
    rows = page.locator("#medien-drawer .file-row")
    expect(rows).to_have_count(1)
    remove = page.get_by_role("button", name="neu.png entfernen")
    asked: list[str] = []

    def dismiss(dialog: Dialog) -> None:
        asked.append(dialog.message)
        dialog.dismiss()

    page.once("dialog", dismiss)
    remove.click()
    expect(rows).to_have_count(1)
    assert asked == [
        "neu.png entfernen? Die Datei wird gelöscht; das lässt sich nicht rückgängig machen."
    ]
    page.once("dialog", lambda dialog: dialog.accept())
    remove.click()
    expect(page.get_by_text("Noch keine Medien")).to_be_visible()


def test_the_forms_own_media_actions_never_make_its_save_conflict(
    archivist_page: Page, live_workbench: str
) -> None:
    # Each media route saves on its own and swaps only #medien-drawer; the form's expected_version
    # has to follow, or Speichern loses to the archivist's own upload, reorder or removal.
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Medien dann Speichern")
    page.set_input_files(
        '#medien-drawer input[type="file"]',
        [
            FilePayload(name="eins.png", mimeType="image/png", buffer=_png((10, 20, 30))),
            FilePayload(name="zwei.png", mimeType="image/png", buffer=_png((30, 20, 10))),
        ],
    )
    rows = page.locator("#medien-drawer .file-row")
    expect(rows).to_have_count(2)
    page.get_by_role("button", name="Nach unten").first.click()
    expect(rows.first).to_contain_text("zwei.png")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="eins.png entfernen").click()
    expect(rows).to_have_count(1)
    page.select_option('select[name="lifecycle"]', "published")
    page.click('button:has-text("Speichern")')
    page.wait_for_url(lambda url: "/edit" not in url and "/articles/" in url)


def test_a_media_action_never_hides_anothers_save_from_the_form(
    archivist_page: Page, live_workbench: str, browser: Browser
) -> None:
    # The other half of the contract above: another archivist saved after this form loaded, so the
    # form's media action must not advance its version past that save (ADR 0013).
    edit_url = _create_draft(archivist_page, live_workbench, "E2E Medien nach fremdem Speichern")

    from tests.e2e.conftest import _archivist_cookie

    ctx2 = browser.new_context()
    ctx2.add_cookies([_archivist_cookie(live_workbench)])  # type: ignore[list-item]
    page2 = ctx2.new_page()
    page2.goto(edit_url)
    page2.select_option('select[name="media_type"]', "Foto(s)")
    page2.fill('input[name="creator"]', "Zweiter")
    page2.click('button:has-text("Speichern")')
    page2.wait_for_url(lambda url: "/edit" not in url)
    ctx2.close()

    page = archivist_page
    page.set_input_files(
        '#medien-drawer input[type="file"]',
        {"name": "eins.png", "mimeType": "image/png", "buffer": _png((10, 20, 30))},
    )
    expect(page.locator("#medien-drawer .file-row")).to_have_count(1)
    page.fill('input[name="creator"]', "Erster")
    page.click('button:has-text("Speichern")')
    expect(page.get_by_text("Inzwischen geändert")).to_be_visible()


def test_a_media_action_keeps_the_captions_typed_before_it(
    archivist_page: Page, live_workbench: str
) -> None:
    # A media action swaps #medien-drawer, which re-renders every caption: the unsaved ones typed
    # before it must come back with their files and still save with Speichern (ADR 0015).
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Bildunterschrift vor Medienaktion")
    page.set_input_files(
        '#medien-drawer input[type="file"]',
        [
            FilePayload(name="eins.png", mimeType="image/png", buffer=_png((10, 20, 30))),
            FilePayload(name="zwei.png", mimeType="image/png", buffer=_png((30, 20, 10))),
        ],
    )
    rows = page.locator("#medien-drawer .file-row")
    expect(rows).to_have_count(2)
    rows.nth(0).get_by_label("Bildunterschrift").fill("Erste Seite")
    rows.nth(1).get_by_label("Bildunterschrift").fill("Zweite Seite")
    page.get_by_role("button", name="Nach unten").first.click()
    expect(rows.first).to_contain_text("zwei.png")
    expect(rows.nth(0).get_by_label("Bildunterschrift")).to_have_value("Zweite Seite")
    expect(rows.nth(1).get_by_label("Bildunterschrift")).to_have_value("Erste Seite")
    expect(page.locator("#dirty-flag")).to_be_visible()  # still unsaved, and still said
    page.click('button:has-text("Speichern")')
    page.wait_for_url(lambda url: "/edit" not in url and "/articles/" in url)
    expect(page.locator("main")).to_contain_text("Zweite Seite")
    expect(page.locator("main")).to_contain_text("Erste Seite")


def test_the_edit_form_absorbs_long_content(
    archivist_page: Page,
    live_workbench: str,
    _e2e_root: Path,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    # Learning G.24: an intrinsic-sizing proof run on short demo data passes VACUOUSLY, so the stress
    # sits where content really grows — the Titel is the archive's one unbounded field (free text an
    # archivist types). It reaches the form as the heading's textarea and the <title>; neither may
    # push the page body sideways. Walked at the narrow widths where the form is one column and at the
    # wide one where the margin sits beside it.
    _seed_long_content(_e2e_root, django_db_blocker)
    url = live_workbench + f"/articles/{_LONG_ULID}/edit"
    # 360 is in the range because a grid's column floor bites there: a bare minmax(floor, 1fr) track
    # cannot shrink below its floor (G.24) and scrolls the page body. The walk itself is the shared one
    # (the ledger proof drives it too, with its own extra probes).
    defects = _sideways_scroll_defects(
        archivist_page, tuple((width, url) for width in (360, 680, 1000, 1440))
    )
    assert not defects, "the edit form does not absorb long content:\n" + "\n".join(defects)


# --- no-JS baseline ----------------------------------------------------------------


def test_no_js_bulk_flow_completes(
    no_js_archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = no_js_archivist_page
    # The no-JS half: with JavaScript OFF "Auswählen" is a plain link into selection mode, and the
    # archivist completes the whole bulk flow: Auswählen → the head box ("every row on this page")
    # → "Feld ändern …" → choose a field → prüfen → anwenden.
    page.goto(live_workbench + LIST)
    page.get_by_role("link", name="Auswählen").click()
    page.wait_for_url("**auswahl=**")  # selection mode is URL state
    rows = page.locator('input[name="auswahl"]').count()
    page.check('input[name="alle"]')
    expect(page.locator('input[name="auswahl"]:checked')).to_have_count(0)  # no JS ticks them
    page.click('[popovertarget="feld-aendern"]')  # native popover, no JS involved
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    expect(page.locator(BULK_COMMIT)).to_be_visible()  # the check page
    # the confirm page carries every row of the page the head box sat on
    expect(page.locator('input[name="auswahl"]')).to_have_count(rows)
    page.click(BULK_COMMIT)
    expect(page.locator(BULK_COMMIT)).to_have_count(0)  # the result page


def test_no_js_create_and_save_baseline(no_js_archivist_page: Page, live_workbench: str) -> None:
    page = no_js_archivist_page
    # The whole create→edit→save flow must work with JavaScript OFF: plain server-rendered forms,
    # no HTMX swap, no PE enhancements. This pins the baseline promise the other journeys (JS on)
    # take for granted. Create step → edit form (server 302, not an hx-swap).
    page.goto(live_workbench + "/articles/new")
    page.fill('textarea[name="title"]', "E2E Ohne JS")
    page.select_option('main select[name="collection_id"]', "FOTOS")
    page.click('main button:has-text("Anlegen")')
    page.wait_for_url("**/edit**")
    expect(page.locator('textarea[name="title"]')).to_have_value("E2E Ohne JS")
    # save: a plain form POST that 302s to the read view (no JS in the loop at all)
    page.select_option('select[name="media_type"]', "Foto(s)")
    page.fill('input[name="creator"]', "K. Meyer")
    page.click('button:has-text("Speichern")')
    page.wait_for_url(lambda url: "/edit" not in url and "/articles/" in url)
    assert "/edit" not in page.url
