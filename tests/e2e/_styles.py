"""A computed-style fingerprint of a page: the check for a wave that claims to change no look
(design-review-law C18). ``render_state`` writes it beside each gallery state's screenshots, and
``scripts/gallery_diff.py`` reports the states whose fingerprint differs between two refs.
"""

from playwright.sync_api import BrowserContext, Page

#: Per element and its ``::before`` / ``::after``: the longhands the app's stylesheets set.
_FINGERPRINT_JS = r"""
() => {
  const names = new Set();
  const walk = (rules) => {
    for (const rule of rules) {
      if (rule.style) for (const name of rule.style) if (!name.startsWith('--')) names.add(name);
      if (rule.cssRules) walk(rule.cssRules);
    }
  };
  for (const sheet of document.styleSheets)
    if (sheet.href && sheet.href.includes('/static/')) walk(sheet.cssRules);
  const longhands = [...names].sort();
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    for (const pseudo of [null, '::before', '::after']) {
      const cs = getComputedStyle(el, pseudo);
      if (pseudo && cs.content === 'none') continue;
      const cls = typeof el.className === 'string' && el.className ? '.' + el.className : '';
      const values = longhands.map((name) => name + ':' + cs.getPropertyValue(name));
      out.push(el.tagName + cls + (pseudo || '') + '|' + values.join(';'));
    }
  }
  return out;
}
"""

#: What can take hover, press or focus; a row and a list item too, for the rules that reach
#: through one (``a.register-row:hover .register-label``).
_INTERACTIVE = (
    'a, button, summary, input, select, textarea, label, [role="option"], [tabindex], tr, li'
)


def fingerprint(page: Page) -> list[str]:
    """One line per element and generated box, in document order."""
    lines: list[str] = page.evaluate(_FINGERPRINT_JS)
    return lines


def force_interaction(context: BrowserContext, page: Page) -> None:
    """Hover, press and focus on every interactive element at once (Chromium only), so the rules
    behind ``:hover``, ``:active`` and ``:focus-visible`` take part in the next fingerprint."""
    client = context.new_cdp_session(page)
    client.send("DOM.enable")
    client.send("CSS.enable")
    root = client.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    found = client.send("DOM.querySelectorAll", {"nodeId": root, "selector": _INTERACTIVE})
    for node_id in found["nodeIds"]:
        client.send(
            "CSS.forcePseudoState",
            {
                "nodeId": node_id,
                "forcedPseudoClasses": ["hover", "active", "focus-visible", "focus"],
            },
        )
