---
name: ui-build
description: Rules for building or reviewing web UI on this repo — contexts not variants, CSS that reaches into containers, includes and the page context, the build order for UI features, and how UI is checked (gallery, journeys, live pages, impeccable critique). Preloaded by writer-ui and design-gate.
when_to_use: Any change to templates, CSS or JS under src/bundesarchiv/app/web/, or a review of one.
---

# UI build

## UI work

Before building a UI feature in HTML, CSS or JS, search the `modern-web-guidance` skill for a
standard pattern (`npx -y modern-web-guidance@latest search "<what you build>"`). Browser support:
Baseline widely available is the floor for anything essential; newer features ship as progressive
enhancement — used where supported, no polyfill, no fallback script. The tiers are law section F of
`docs/design/design-review-law.md`, which wins.

UI is built under the Construction law in `docs/design/design-system.md`: semantic HTML first,
compose existing components and layout primitives, every visible element traces to a
wish/ruling/spec section, one pattern per problem. Its component rules decide whether you use,
adapt or build a component, and when a new one needs the owner first ("Component rules"; the
inventory with each row's status is "Component inventory"). A UI wave ends with before/after
gallery renders for the owner's verdict — never with prose claiming the UI is good.

## Design critique through impeccable

Design critique, audit and polish go through the `impeccable` skill (`impeccable:impeccable`;
project config in `.impeccable/`). A UI change ends with an impeccable critique of the touched
screens; its findings are reported to the owner, never fixed unasked.

## UI: contexts, not variants

Before adding a modifier class to a component (`.button-danger`, `.facts-quiet`), ask whether it
is a context: something that only re-points role tokens or knobs and would work on any component
(`.danger` re-points `--ink`). If yes, write it as that context; if it sets the component's own
properties, it is a variant and law C2 forbids it. A context reaches only parts that read the role
(`color: var(--ink)`), not parts that inherit a resolved colour.

## CSS that reaches into a container

A rule that reaches `form`, `p` or `ul` inside a container also hits a popover panel nested there:
author CSS beats the browser's `[popover]` hiding, so `.menu li > form { display: block }` shows a
closed panel. Select what the component owns instead: its own children (`.record-meta > p`) or
the plain element by a class (`.menu-form`); where neither works, exclude the panel
(`form:not([popover])`).

A `biome-ignore` covers only the selector that follows it. Adding a selector to a list keeps
specificity even with `:is(a, b)`, but check that the `:is()` matches the same elements: a factored
`.menu li > :is(button.link, form > button.link)` is not `.menu li > button.link, .menu li > form >
button.link`.

## Includes that inherit the page context

An include without `only` sees the whole page context, so an optional param it tests
(`{% if back %}`) turns on when a page happens to use the same key. Give a page's own keys names
no include takes, or pass the include `only` with its params.

Controls that exist on every page (the header's tool panels) also match a non-strict Playwright
selector first. Scope journey selectors to the region they act in (`main …`).

A unit that adds or moves a `[popovertarget]` runs the overlay journey itself before it reports
(`mise run test:e2e -- -k overlays`, ~30 s): a panel anchored under the wrong trigger shows only
there, and a finisher cycle costs far more.

## Where a partial lives

`templates/components/` holds inventoried components only (the gate
`test_design_lint.py::test_every_component_template_has_an_inventory_row`). A partial that is no
component goes under `templates/workbench/` as an underscore-prefixed file, like `_field.html`
and `_copy.html`.

## Template source stays readable

Django templates have no whitespace control, so the CSS must not depend on whitespace. Lay out inline
runs (facts, links, separators) as flex or grid with `gap`, and draw separators with a generated
`::before` (`content: "·" / ""`), as `.byline` does; whitespace between flex or grid items does not
render. Then write the template source normally: one element per line, indented. No
`{% spaceless %}`, no `&nbsp;` or `&#32;` for layout, no one-line templates. A template you create or
touch follows this.

## Screenshots via the gallery, review on live pages

For any UI change: restart the dev server after EVERY commit (`:8000` runs `--noreload` and serves
stale code otherwise), then judge on the live pages. Send the owner a screenshot only when it is
cheap (the gallery or your own check already made it) and the work is UI work — never extra work
nobody asked for; under Remote Control the owner cannot open live pages, so screenshots are the
medium there. Agents keep their own internal screenshot self-verification loop; the state gallery
(`mise run test:gallery`) is the shared review medium, and `mise run test:e2e` drives the journeys.

A journey that races a debounce or a late answer drives time itself: `page.clock.install(time=0)`
before `goto`, then `pause_at(...)` (install alone lets time flow), `run_for(ms)` to fire the timer,
and `page.route` to hold the answer. A late answer is judged by the field as it is when the answer
arrives, never by values captured when the request left.
