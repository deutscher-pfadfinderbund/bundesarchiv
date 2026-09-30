// Bulk-edit (Sammelbearbeitung) progressive enhancement (spec §5). Enhancement-only: the no-JS
// baseline works without it (page-select is the "Alle auf dieser Seite" link; the tool row's
// selection tools show on a tick via CSS, and for a URL-borne selection from the server; paging
// carries the URL-borne selection, so fresh ticks need a submit first — this file lifts that
// limit, GH #22). It keeps the live count and hides the selection tools via [hidden] while the
// TOTAL selection is 0: the live checkboxes here PLUS the off-page URL-borne selection the server
// hands over in data-bulk-offpage (learning G.25 — an enhancement may only hide what it can
// account for). Hiding rides the modes-layer `[hidden] { display: none !important }` rule, so no
// display rule can ever make the hidden tools intercept clicks (the recorded regression class).
// Self-contained, same-origin, no framework (dormancy rule). HTMX (loaded separately) handles the
// dependent-Dokumenttyp swap.
(() => {
  "use strict";

  // Re-init on load AND after any htmx swap: the live search swaps #results (replacing the form +
  // bar), and a history restore (Back after a hx-push-url search) is a server GET whose response
  // swaps the whole body — both end in htmx:after:swap (learning G.25). Idempotent: a data-flag
  // guards double-binding.
  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:after:swap", init);

  // the bulk form currently in the document (absent for non-archivists and on the zero-hit page);
  // #results also holds the Spalten form, so it is found by its count hook
  function resultsForm() {
    return document.querySelector("#results > form:has([data-bulk-zahl])");
  }

  function init() {
    const form = resultsForm();
    if (!form || form.dataset.bulkBound === "1") {
      return;
    }
    form.dataset.bulkBound = "1";
    wire(form);
  }

  function wire(form) {
    const rowBoxes = () => Array.from(form.querySelectorAll('input[name="auswahl"]'));

    // 1. Live count + selection-carrying links on every tick/untick.
    form.addEventListener("change", (event) => {
      if (event.target.name !== "auswahl") {
        return;
      }
      updateCount();
      rewriteSelectionLinks();
    });

    // The count target [data-bulk-zahl] is always in the DOM. Empty text at zero keeps
    // signals-once (no "0 ausgewählt"). The data-hook is the contract: markup may restructure
    // freely as long as it keeps the hook. The same count drives the tools' visibility.
    //
    // The TOTAL is this page's live checkboxes PLUS the off-page part of the URL-borne selection
    // (data-bulk-offpage, from the server). Both halves matter: on THIS page the live checkbox
    // state supersedes the URL (fresh ticks/unticks count immediately, GH #22), while the
    // selection on other pages is invisible to the DOM and can only come from the server. An
    // enhancement may only hide what it accounts for (learning G.25) — counting the boxes alone
    // hid a live cross-page selection and stranded the archivist on page 2.
    function updateCount() {
      const zahl = form.querySelector("[data-bulk-zahl]");
      const bulk = form.querySelector("[data-bulk-offpage]");
      const offPage = bulk ? Number.parseInt(bulk.dataset.bulkOffpage, 10) || 0 : 0;
      const n = offPage + rowBoxes().filter((b) => b.checked).length;
      zahl.textContent = n > 0 ? `${n} ausgewählt` : "";
      if (bulk) {
        bulk.hidden = n === 0;
      }
    }

    // 2. Selection-carrying links (GH #22): fold the LIVE checkbox state into the prev/next pager
    // links + "Alle auf dieser Seite" on every change, so unsubmitted ticks/unticks survive paging
    // while the URL stays the canonical shareable state. Per link, from its own href: drop this
    // page's ulids from ?auswahl= (fresh unticks stick), keep the rest (other pages' selections),
    // append the added set. "Auswahl aufheben" is NEVER rewritten — its purpose is clearing.
    function rewriteSelectionLinks() {
      const boxes = rowBoxes();
      const pageUlids = boxes.map((b) => b.value);
      const checked = boxes.filter((b) => b.checked).map((b) => b.value);
      const results = form.closest("#results") || document;
      const pagers = results.querySelectorAll('.pager a[rel="prev"], .pager a[rel="next"]');
      Array.prototype.forEach.call(pagers, (link) => {
        rewriteAuswahl(link, pageUlids, checked);
      });
      // "Alle auf dieser Seite" re-adds the FULL page set (checked ⊆ page, which the union
      // absorbs), so it keeps meaning "current selection ∪ this page" — never shrunk.
      const alleLink = form.querySelector("[data-bulk-alle]");
      if (alleLink) {
        rewriteAuswahl(alleLink, pageUlids, pageUlids);
      }
    }

    // Rewrite ONLY the auswahl params of one link, from its own href: every non-auswahl param
    // keeps its place and decoded value (re-serialization may normalize percent-encoding — the
    // server parses both spellings identically), the auswahl list becomes
    // (href's list − this page's ulids) + add.
    function rewriteAuswahl(link, pageUlids, add) {
      const url = new URL(link.getAttribute("href"), globalThis.location.href);
      const kept = url.searchParams.getAll("auswahl").filter((u) => pageUlids.indexOf(u) === -1);
      url.searchParams.delete("auswahl");
      kept.concat(add).forEach((u) => {
        url.searchParams.append("auswahl", u);
      });
      link.setAttribute("href", `?${url.searchParams.toString()}`);
    }

    // Fold once at wire time too: back/forward navigation restores checkbox state without firing
    // change events, and the server-rendered links only carry the URL-borne selection. The count
    // sync doubles as the initial visibility verdict (hide the server-rendered tools at 0).
    updateCount();
    rewriteSelectionLinks();
  }
})();
