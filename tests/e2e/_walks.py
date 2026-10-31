"""Walks over a reached screen: ``(page, screen) -> defects``, an empty list passes."""

import json
from typing import Any

from playwright.sync_api import Page, Route
from tests.e2e._pages import (
    OVERLAY_CENTRED_PANEL,
    OVERLAY_PANEL_OF_JS,
    OVERLAY_PANELS,
    OVERLAY_TRIGGERS,
    Screen,
)

#: Set by ``measure_control_rows``, which clicks every overlay trigger open and shut.
_PANELS_OPENED = "walkedControlRows"


def control_row_walk(page: Page, screen: Screen) -> list[str]:
    """Law C8's one height source, the AA target floor and the toolbar buttons' roles; the screen
    names the rows it must show."""
    by_name = measure_control_rows(page)
    missing = [
        f"no control row named {prefix!r}: {sorted(by_name)}"
        for prefix in screen.control_rows
        if not any(name.startswith(prefix) for name in by_name)
    ]
    return missing + _control_row_defects(by_name) + _toolbar_button_defects(page, screen.name)


def overlay_walk(page: Page, screen: Screen, *, anchored: bool) -> list[str]:
    """The overlays at every containment width, in the tier asked for: the fallback needs
    ``serve_css_without_anchor_positioning`` routed before the load. Run it before anything opens
    a panel: anchor positioning remembers a panel's last fallback."""
    if page.evaluate(f"() => window.{_PANELS_OPENED} === true"):
        return ["overlay_walk ran after control_row_walk opened this page's panels: run it first"]
    found = page.locator(OVERLAY_TRIGGERS).count()
    if found < screen.overlays:
        return [f"found only {found} overlay triggers"]
    if anchored and not page.evaluate("() => CSS.supports('anchor-name: --a')"):
        return ["this browser has no anchor positioning — the anchored tier would go unproven"]
    if not anchored and (live := _anchoring(page)):
        return [f"the enhancement is still live — the fallback tier would go unproven: {live}"]
    return _overlay_containment_defects(page, anchored=anchored)


#: Law C8's one proof (design-review-law E): no per-instance copies.
_CONTROL_ROWS_JS = """(overlayPanels) => {
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
        // an overlay panel is a row of its own even when its height equals its trigger row's: it
        // re-declares the knob either way (components.css), so a value match must not hide it
        if (el.matches('[role=toolbar]') || el.matches(overlayPanels) || declaresKnob(el)) {
            rows.push(el);
        }
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
            // there — counting them twice would tie the panel's height to the chrome row's.
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


def measure_control_rows(page: Page) -> dict[str, list[dict[str, str | int | bool]]]:
    """Keyed ``<name>#<index>`` because names repeat. Overlay entries are measurable only while
    open, so each overlay is opened in turn."""
    page.evaluate(f"() => {{ window.{_PANELS_OPENED} = true; }}")
    rows: list[dict[str, Any]] = page.evaluate(_CONTROL_ROWS_JS, OVERLAY_PANELS)
    walked: dict[str, list[dict[str, str | int | bool]]] = {}
    for i, row in enumerate(rows):
        walked[f"{row['name']}#{i}"] = row["controls"]
    triggers = page.locator(OVERLAY_TRIGGERS)
    for index in range(triggers.count()):
        trigger = triggers.nth(index)
        if not trigger.is_visible():  # e.g. "Feld ändern …" before any row is picked
            continue
        trigger.click()
        for i, row in enumerate(page.evaluate(_CONTROL_ROWS_JS, OVERLAY_PANELS)):
            if row["controls"]:
                walked[f"{row['name']}#{i}"] = row["controls"]
        trigger.click()  # close before opening the next one
    return walked


#: WCAG 2.2 AA target size (law D).
_AA_TARGET_FLOOR = 24


def _control_row_defects(by_name: dict[str, list[dict[str, str | int | bool]]]) -> list[str]:
    defects: list[str] = []
    for name, controls in by_name.items():
        defects.extend(
            f"row '{name}' control '{c['label']}' is {c['width']}x{c['height']}px — under the"
            f" WCAG 2.2 AA {_AA_TARGET_FLOOR}px target floor"
            for c in controls
            if min(int(str(c["width"])), int(str(c["height"]))) < _AA_TARGET_FLOOR
        )
        if len(controls) < 2:
            continue
        # Keyed by position: labels repeat.
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


#: Roles resolve on a probe: a token's raw value is a light-dark() expression only a rendered
#: element resolves.
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


def toolbar_buttons(page: Page) -> tuple[dict[str, str], list[dict[str, str | bool]]]:
    facts: dict[str, dict[str, str] | list[dict[str, str | bool]]] = page.evaluate(
        _TOOLBAR_BUTTON_JS
    )
    roles = facts["roles"]
    buttons = facts["buttons"]
    assert isinstance(roles, dict) and isinstance(buttons, list)
    return roles, buttons


def _toolbar_button_defects(page: Page, where: str) -> list[str]:
    roles, buttons = toolbar_buttons(page)
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
    return defects


#: Per overlay, opened in turn: its geometry plus the entries a centre hit-test misses (on-viewport
#: is not reachable: a sticky row can paint over a panel).
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

#: 360 the narrowest phone; 540/680/900 straddle the header and rail wraps; 1100 sits just below
#: the pane's 80rem switch.
_CONTAINMENT_WIDTHS = (360, 540, 680, 900, 1100, 1440)


def _overlay_containment_defects(page: Page, *, anchored: bool) -> list[str]:
    """The reached screen's overlays at every containment width. ``anchored`` also checks the
    anchored tier's promise: each panel hangs from its own trigger."""
    defects: list[str] = []
    for width in _CONTAINMENT_WIDTHS:
        page.set_viewport_size({"width": width, "height": 900})
        for rect in page.evaluate(_OVERLAY_WALK_JS, OVERLAY_TRIGGERS):
            where = f"{width}px · {rect['label']}"
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
                defects.append(f"{where}: panel ends at {rect['right']}px > {rect['viewport']}px")
            if float(str(rect["docOverflow"])) > 1:
                defects.append(f"{where}: the open panel scrolls the document {rect}")
    return defects


#: The one pre-Baseline @supports condition, in every stylesheet that carries it, and a
#: falsification of it. Serving the REAL stylesheets with just this condition negated is how the
#: FALLBACK tier is reached — no fallback CSS is restated in the test, and Chromium's own
#: anchor-positioning support (which no browser flag turns off any more) is left alone.
_ANCHOR_SUPPORTS_CONDITION = "(anchor-name: --anchor-probe)"
_ANCHOR_SUPPORTS_FALSIFIED = "(anchor-name: 0)"


def serve_css_without_anchor_positioning(route: Route) -> None:
    response = route.fetch()
    patched = response.text().replace(_ANCHOR_SUPPORTS_CONDITION, _ANCHOR_SUPPORTS_FALSIFIED)
    route.fulfill(response=response, body=patched)


def _anchoring(page: Page) -> list[str]:
    """The elements that take part in anchor positioning."""
    anchoring: list[str] = page.evaluate(
        "() => [...document.querySelectorAll('*')].flatMap((e) => {"
        " const s = getComputedStyle(e);"
        " return [s.anchorName, s.anchorScope, s.positionAnchor]"
        "  .filter((v) => v.startsWith('--')).map((v) => `${e.localName}.${e.className} ${v}`);"
        "})"
    )
    return anchoring
