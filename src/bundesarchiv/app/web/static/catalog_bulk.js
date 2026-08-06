// Bulk-edit (Sammelbearbeitung) progressive enhancement (spec §5). Enhancement-only: the no-JS
// baseline works without it (page-select is the "Alle auf dieser Seite" link; the bar visibility
// + count come from the server off ?auswahl=; paging carries the URL-borne selection, so fresh
// ticks need a submit first — this file lifts that limit, GH #22). Row inversion and the
// Feld→value-widget switch are pure CSS now (:has over the checkbox / the select's checked
// option) — JS for state CSS can express is a blacklist defect. Self-contained, same-origin, no
// framework (dormancy rule). HTMX (loaded separately) handles the dependent-Dokumenttyp swap.
(function () {
  "use strict";

  // Re-init on load AND after any htmx swap of #results (the search hx-swaps it, replacing the form
  // + bar), so the enhancement survives a live search. Idempotent: a data-flag guards double-binding.
  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:afterSwap", init);

  function init() {
    var form = document.querySelector("#results > form");
    if (!form || form.dataset.bulkBound === "1") return;
    form.dataset.bulkBound = "1";
    wire(form);
  }

  function wire(form) {
    var rowBoxes = function () {
      return Array.prototype.slice.call(form.querySelectorAll('input[name="auswahl"]'));
    };

    // 1. Live count + selection-carrying links on every tick/untick.
    form.addEventListener("change", function (event) {
      if (event.target.name !== "auswahl") return;
      updateCount();
      rewriteSelectionLinks();
    });

    // The bar (and its <output>) is always in the DOM (cold-start fix, #16), so the count goes
    // live on the first tick — no early-return. Empty text at zero keeps signals-once (no "0
    // ausgewählt").
    function updateCount() {
      var zahl = form.querySelector(".bulkbar output");
      var n = rowBoxes().filter(function (b) {
        return b.checked;
      }).length;
      zahl.textContent = n > 0 ? n + " ausgewählt" : "";
    }

    // 2. Selection-carrying links (GH #22): fold the LIVE checkbox state into the prev/next pager
    // links + "Alle auf dieser Seite" on every change, so unsubmitted ticks/unticks survive paging
    // while the URL stays the canonical shareable state. Per link, from its own href: drop this
    // page's ulids from ?auswahl= (fresh unticks stick), keep the rest (other pages' selections),
    // append the added set. "Auswahl aufheben" is NEVER rewritten — its purpose is clearing.
    function rewriteSelectionLinks() {
      var boxes = rowBoxes();
      var pageUlids = boxes.map(function (b) {
        return b.value;
      });
      var checked = boxes
        .filter(function (b) {
          return b.checked;
        })
        .map(function (b) {
          return b.value;
        });
      var results = form.closest("#results") || document;
      var pagers = results.querySelectorAll('.pager a[rel="prev"], .pager a[rel="next"]');
      Array.prototype.forEach.call(pagers, function (link) {
        rewriteAuswahl(link, pageUlids, checked);
      });
      // "Alle auf dieser Seite" re-adds the FULL page set (checked ⊆ page, which the union
      // absorbs), so it keeps meaning "current selection ∪ this page" — never shrunk.
      var alleLink = form.querySelector("[data-bulk-alle]");
      if (alleLink) rewriteAuswahl(alleLink, pageUlids, pageUlids);
    }

    // Rewrite ONLY the auswahl params of one link, from its own href: every non-auswahl param
    // keeps its place and decoded value (re-serialization may normalize percent-encoding — the
    // server parses both spellings identically), the auswahl list becomes
    // (href's list − this page's ulids) + add.
    function rewriteAuswahl(link, pageUlids, add) {
      var url = new URL(link.getAttribute("href"), window.location.href);
      var kept = url.searchParams.getAll("auswahl").filter(function (u) {
        return pageUlids.indexOf(u) === -1;
      });
      url.searchParams.delete("auswahl");
      kept.concat(add).forEach(function (u) {
        url.searchParams.append("auswahl", u);
      });
      link.setAttribute("href", "?" + url.searchParams.toString());
    }

    // Fold once at wire time too: back/forward navigation restores checkbox state without firing
    // change events, and the server-rendered links only carry the URL-borne selection.
    rewriteSelectionLinks();
  }
})();
