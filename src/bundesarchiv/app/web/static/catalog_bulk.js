// Bulk-edit (Sammelbearbeitung) progressive enhancement (spec §5). Enhancement-only: the no-JS
// baseline works without it (page-select is the "Alle auf dieser Seite" link; the bar visibility
// + count come from the server off ?auswahl=; paging carries the URL-borne selection, so fresh
// ticks need a submit first — this file lifts that limit, GH #22). PROGRESSIVE visibility
// (owner 2026-08-07, reverses the #16 cold-start ruling): the server always renders the
// disclosure VISIBLE (so a no-JS archivist can reach "Alle auf dieser Seite"); with JS this
// file hides it via the [hidden] attribute while the TOTAL selection count is 0 — this page's
// live checkboxes PLUS the off-page URL-borne selection the server hands over in
// data-bulk-offpage (learning G.25: an enhancement may only hide what it can account for; a
// box-counting client hid a live cross-page selection) — and reveals it the moment the total
// reaches 1 — hiding rides the modes-layer `[hidden] { display: none
// !important }` rule, so no display rule can ever make the hidden disclosure intercept clicks
// (the recorded regression class). Row inversion and the Feld→value-widget switch are pure CSS
// (:has over the checkbox / the select's checked option) — JS for state CSS can express is a
// blacklist defect. Self-contained, same-origin, no framework (dormancy rule). HTMX (loaded
// separately) handles the dependent-Dokumenttyp swap.
(function () {
  "use strict";

  // Re-init on load AND after any htmx swap of #results (the search hx-swaps it, replacing the form
  // + bar), so the enhancement survives a live search. Idempotent: a data-flag guards double-binding.
  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:afterSwap", init);
  // A history restore (Back after a hx-push-url search) is its OWN lifecycle event: htmx 2.0.4
  // replaces the body from its snapshot and fires ONLY htmx:historyRestore — never afterSwap — so
  // the plain init above never runs. Worse, the snapshot was serialized WITH this enhancement's
  // leftovers: the bound flag (an attribute, so it survives), the disclosure's [hidden] state and
  // the count text, while the checkbox ticks (properties) do not. The restored page therefore came
  // back with a stale count over a dead form. Re-init from the restored state instead (learning
  // G.25). document.body itself survives the restore (htmx swaps its innerHTML), so this listener
  // stays attached.
  document.body.addEventListener("htmx:historyRestore", reinit);

  function init() {
    var form = document.querySelector("#results > form");
    if (!form || form.dataset.bulkBound === "1") return;
    form.dataset.bulkBound = "1";
    wire(form);
  }

  // Drop the restored snapshot's bound flag so init() wires the fresh nodes, then let wire()'s own
  // closing sync re-derive count + visibility + link state from what is ACTUALLY in the DOM.
  // Idempotent like init(): the flag goes back up immediately.
  function reinit() {
    var form = document.querySelector("#results > form");
    if (form) delete form.dataset.bulkBound;
    init();
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

    // The count target [data-bulk-zahl] (in the disclosure's summary) is always in the DOM,
    // so the count goes live on the first tick — visible even while the details is collapsed.
    // Empty text at zero keeps signals-once (no "0 ausgewählt"). The data-hook is the contract:
    // markup may restructure freely as long as it keeps the hook. The same count drives the
    // disclosure's progressive visibility (see the file header): hidden at 0, revealed at ≥ 1.
    //
    // The TOTAL is this page's live checkboxes PLUS the off-page part of the URL-borne selection
    // (data-bulk-offpage, from the server). Both halves matter: on THIS page the live checkbox
    // state supersedes the URL (fresh ticks/unticks count immediately, GH #22), while the
    // selection on other pages is invisible to the DOM and can only come from the server. An
    // enhancement may only hide what it accounts for (learning G.25) — counting the boxes alone
    // hid a live cross-page selection and stranded the archivist on page 2.
    function updateCount() {
      var zahl = form.querySelector("[data-bulk-zahl]");
      var bulk = form.querySelector("details.bulk");
      var offPage = bulk ? parseInt(bulk.dataset.bulkOffpage, 10) || 0 : 0;
      var n =
        offPage +
        rowBoxes().filter(function (b) {
          return b.checked;
        }).length;
      zahl.textContent = n > 0 ? n + " ausgewählt" : "";
      if (bulk) bulk.hidden = n === 0;
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
    // change events, and the server-rendered links only carry the URL-borne selection. The count
    // sync doubles as the initial visibility verdict (hide the server-visible disclosure at 0).
    updateCount();
    rewriteSelectionLinks();
  }
})();
