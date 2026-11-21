"""The declaration probe (design-review-law C18): per gallery state it drops each declaration of
the app's stylesheets in turn and records whether any computed value changes. Report only:
``mise run test:css-probe`` runs it and ``scripts/css_probe_report.py`` reads what it wrote.
"""

import json
import os
from pathlib import Path

from playwright.sync_api import Browser, Page
from tests.e2e._corpus import CorpusHandles
from tests.e2e._gallery import GalleryState
from tests.e2e._pages import SCREENS
from tests.e2e._styles import force_interaction
from tests.e2e.conftest import add_archivist_cookies

#: Rows of (stylesheet, absolute selector, declaration, status). A rule is marked with a sentinel
#: property to find the elements it applies to; a status is "effective", "inert" (the computed
#: value is the same without the declaration), "inert-same-value" / "inert-unread" (a custom
#: property), "unmatched" (the rule applies to nothing here) or "unprobeable".
_PROBE_JS = r"""
() => {
  const freeze = new CSSStyleSheet();
  freeze.replaceSync('*,*::before,*::after{transition:none!important;animation:none!important}');
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, freeze];
  try { CSS.registerProperty({name: '--css-probe', syntax: '*', inherits: false}); } catch (e) {}

  const splitTop = (text, sep) => {
    const out = []; let depth = 0, quote = null, cur = '';
    for (const ch of text) {
      if (quote) { cur += ch; if (ch === quote) quote = null; continue; }
      if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
      if (ch === '(' || ch === '[') depth++;
      if (ch === ')' || ch === ']') depth--;
      if (ch === sep && depth === 0) { out.push(cur); cur = ''; } else cur += ch;
    }
    if (cur.trim()) out.push(cur);
    return out.map(s => s.trim()).filter(Boolean);
  };
  const expandCache = new Map();
  const expand = (decl) => {
    if (!expandCache.has(decl)) {
      const s = document.createElement('span').style;
      s.cssText = decl;
      expandCache.set(decl, [...s]);
    }
    return expandCache.get(decl);
  };
  const fileOf = (rule) => {
    let r = rule; while (r.parentRule) r = r.parentRule;
    return (r.parentStyleSheet && r.parentStyleSheet.href || '').split('/').pop().split('?')[0];
  };

  // 1. collect style rules with their absolute selectors
  const found = [];
  const walk = (rules, parentAbs) => {
    for (const rule of rules) {
      if (rule instanceof CSSStyleRule) {
        let abs = rule.selectorText;
        if (parentAbs) {
          abs = splitTop(abs, ',').map(part =>
            part.includes('&') ? part.replaceAll('&', `:is(${parentAbs})`) : `:is(${parentAbs}) ${part}`
          ).join(', ');
        }
        found.push({rule, abs});
        if (rule.cssRules && rule.cssRules.length) walk(rule.cssRules, abs);
      } else if (rule.constructor.name === 'CSSStartingStyleRule') {
        continue;
      } else if (rule.cssRules) {
        walk(rule.cssRules, parentAbs);
      }
    }
  };
  for (const sheet of document.styleSheets) {
    if (!sheet.href || !sheet.href.includes('/static/') || sheet.href.includes('tokens.css')) continue;
    walk(sheet.cssRules, null);
  }
  const standard = new Set();
  for (const {rule} of found)
    for (const decl of splitTop(rule.style.cssText, ';'))
      for (const name of expand(decl)) if (!name.startsWith('--')) standard.add(name);
  const STANDARD = [...standard];

  const subtreePrint = (targets) => {
    const parts = [];
    for (const [el, pseudo] of targets) {
      const nodes = pseudo ? [[el, pseudo]] : [];
      if (!pseudo) for (const n of [el, ...el.querySelectorAll('*')])
        nodes.push([n, null], [n, '::before'], [n, '::after']);
      for (const [n, p] of nodes) {
        const cs = getComputedStyle(n, p);
        if (p && cs.content === 'none') { parts.push('-'); continue; }
        for (const name of STANDARD) parts.push(cs.getPropertyValue(name));
      }
    }
    return parts.join('\u0001');
  };

  const results = [];
  for (const {rule, abs} of found) {
    const original = rule.style.cssText;
    const decls = splitTop(original, ';');
    if (!decls.length) continue;
    // 2. the (element, pseudo) pairs this rule is ACTIVE on right now
    const candidates = [];
    let unprobeable = false;
    for (const part of splitTop(abs, ',')) {
      const m = part.match(/^(.*?)::?(before|after)$/);
      let base = part, pseudo = null;
      if (m) { base = m[1] || '*'; pseudo = '::' + m[2]; }
      else if (part.includes('::')) { unprobeable = true; continue; }
      try { for (const el of document.querySelectorAll(base)) candidates.push([el, pseudo]); }
      catch (e) { unprobeable = true; }
    }
    rule.style.setProperty('--css-probe', '1');
    const targets = candidates.filter(([el, p]) => getComputedStyle(el, p).getPropertyValue('--css-probe') !== '');
    rule.style.cssText = original;
    const file = fileOf(rule);
    if (!targets.length) {
      for (const decl of decls) results.push([file, abs, decl, unprobeable && !candidates.length ? 'unprobeable' : 'unmatched']);
      continue;
    }
    const styles = targets.map(([el, p]) => getComputedStyle(el, p));
    for (let i = 0; i < decls.length; i++) {
      const decl = decls[i];
      const names = expand(decl);
      if (!names.length || /^(transition|animation)/.test(decl)) { results.push([file, abs, decl, 'unprobeable']); continue; }
      const custom = names[0].startsWith('--');
      const read = () => styles.map(cs => names.map(n => cs.getPropertyValue(n)).join('\u0001')).join('\u0002');
      const before = read();
      const beforeTree = custom ? subtreePrint(targets) : null;
      rule.style.cssText = decls.filter((_, j) => j !== i).join('; ');
      const after = read();
      let status;
      if (before === after) status = custom ? 'inert-same-value' : 'inert';
      else if (custom) status = subtreePrint(targets) === beforeTree ? 'inert-unread' : 'effective';
      else status = 'effective';
      rule.style.cssText = original;
      results.push([file, abs, decl, status]);
    }
  }
  return results;
}
"""

#: A phone, added for every inventory screen: the viewport-S rules apply only there.
_PHONE = 390
_SCREEN_NAMES = frozenset(screen.name for screen in SCREENS)


def css_probe_dir() -> Path:
    """Where the results land: ``var/css-probe/`` at the repo root by default."""
    default = Path(__file__).resolve().parent.parent.parent / "var" / "css-probe"
    return Path(os.environ.get("BUNDESARCHIV_CSS_PROBE_DIR") or default)


def probe(page: Page) -> list[list[str]]:
    rows: list[list[str]] = page.evaluate(_PROBE_JS)
    return rows


def probe_state(
    browser: Browser, base_url: str, corpus: CorpusHandles, state: GalleryState
) -> list[Path]:
    """Four passes per width: at rest and with hover and focus forced, in light and in dark (a
    colour that equals the browser's default in one scheme differs in the other)."""
    out = css_probe_dir()
    out.mkdir(parents=True, exist_ok=True)
    widths = (*state.widths, _PHONE) if state.name in _SCREEN_NAMES else state.widths
    written: list[Path] = []
    for width in dict.fromkeys(widths):
        context = browser.new_context(
            color_scheme="light", viewport={"width": width, "height": state.height}
        )
        try:
            if state.archivist:
                add_archivist_cookies(context, base_url)
            page = context.new_page()
            state.reach(page, base_url, corpus)
            passes = {"rest-light": probe(page)}
            page.emulate_media(color_scheme="dark")
            passes["rest-dark"] = probe(page)
            force_interaction(context, page)
            passes["forced-dark"] = probe(page)
            page.emulate_media(color_scheme="light")
            passes["forced-light"] = probe(page)
            target = out / f"{state.name}.{width}.json"
            target.write_text(json.dumps(passes))
            written.append(target)
        finally:
            context.close()
    return written
