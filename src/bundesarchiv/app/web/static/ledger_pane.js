// Ledger row -> preview pane, progressive enhancement (Part 4.5).
//
// The no-JS BASELINE is the canonical detail link: every ledger row's title points at
// /artikel/<ulid>, which works on every viewport without JS. Below 1280px the pane is CSS-hidden,
// so the pane would be a dead click there anyway — the detail page is the right destination.
//
// This layer upgrades the click ONLY on viewports >= 1280px (where layouts.css actually shows the
// pane): a plain left-click on a row title opens the ?artikel=<ulid> pane in place instead of
// navigating to the detail page, preserving the current query string's other params (search text,
// facets, sort, page) so the surrounding search state survives. Modified clicks (new tab / new
// window / download) and the no-JS path fall through to the detail link untouched.
//
// Self-contained, same-origin only (dormancy rule): no external requests, no framework — one
// delegated listener. If this file is ever unavailable the baseline detail link still works.
(function () {
  "use strict";

  // Mirror the layouts.css pane breakpoint: below this the pane is hidden and the detail link wins.
  var PANE_MIN_WIDTH = 1280;

  function paneEnabled() {
    return window.matchMedia("(min-width: " + PANE_MIN_WIDTH + "px)").matches;
  }

  document.addEventListener("click", function (event) {
    // Only a plain left-click upgrades; let the browser handle modified clicks (new tab, download,
    // middle-click) and non-primary buttons — those must reach the real detail URL.
    if (event.defaultPrevented) return;
    if (event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    var link = event.target.closest("a[data-artikel]");
    if (!link) return;
    if (!paneEnabled()) return; // narrow viewport: the pane is hidden, keep the detail link

    var ulid = link.getAttribute("data-artikel");
    if (!ulid) return;

    // Preserve every OTHER query param; set (or replace) artikel = this row's ulid. Pane state is
    // URL-as-state, so the resulting ?artikel URL is shareable/bookmarkable exactly like a full nav.
    var params = new URLSearchParams(window.location.search);
    params.set("artikel", ulid);
    event.preventDefault();
    window.location.assign(window.location.pathname + "?" + params.toString());
  });
})();
