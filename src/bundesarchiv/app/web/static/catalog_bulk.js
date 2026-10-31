// Bulk selection, enhanced; without it, ticks need a submit before paging.
(() => {
  "use strict";

  // Re-init after every swap: a live search and a history restore both replace the form.
  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:after:swap", init);

  // the bulk form currently in the document (absent for non-archivists and on the zero-hit page);
  // #results also holds the Spalten form, so it is found by its count hook
  function resultsForm() {
    return document.querySelector("#results > form:has([data-bulk-count])");
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
    const rowBoxes = () => Array.from(form.querySelectorAll('input[name="selection"]'));

    // 1. Live count + selection-carrying links on every tick/untick. The head box ("all") ticks
    // or unticks every row on the page, and shows ticked while every row is.
    const head = form.querySelector('input[name="all"]');
    form.addEventListener("change", (event) => {
      if (event.target === head) {
        rowBoxes().forEach((b) => {
          b.checked = head.checked;
        });
      } else if (event.target.name !== "selection") {
        return;
      }
      syncHead();
      updateCount();
      rewriteSelectionLinks();
    });

    function syncHead() {
      if (head) {
        head.checked = rowBoxes().every((b) => b.checked);
      }
    }

    // Other pages' ticks are invisible to the DOM; the server hands their count over in
    // data-bulk-offpage.
    function updateCount() {
      const count = form.querySelector("[data-bulk-count]");
      const bulk = form.querySelector("[data-bulk-offpage]");
      const offPage = bulk ? Number.parseInt(bulk.dataset.bulkOffpage, 10) || 0 : 0;
      const n = offPage + rowBoxes().filter((b) => b.checked).length;
      count.textContent = n > 0 ? `${n} ausgewählt` : "";
    }

    // 2. Only the pager's links (steps and page sizes) carry the live ticks: "Abbrechen" leaves
    // the mode.
    function rewriteSelectionLinks() {
      const boxes = rowBoxes();
      const pageUlids = boxes.map((b) => b.value);
      const checked = boxes.filter((b) => b.checked).map((b) => b.value);
      const results = form.closest("#results") || document;
      const pagers = results.querySelectorAll(".pager a[href]");
      Array.prototype.forEach.call(pagers, (link) => {
        rewriteAuswahl(link, pageUlids, checked);
      });
    }

    // Rewrite ONLY the selection params of one link, from its own href: every non-selection param
    // keeps its place and decoded value (re-serialization may normalize percent-encoding — the
    // server parses both spellings identically), the selection list becomes
    // (href's list − this page's ulids) + add.
    function rewriteAuswahl(link, pageUlids, add) {
      const url = new URL(link.getAttribute("href"), globalThis.location.href);
      const kept = url.searchParams.getAll("selection").filter((u) => pageUlids.indexOf(u) === -1);
      url.searchParams.delete("selection");
      kept.concat(add).forEach((u) => {
        url.searchParams.append("selection", u);
      });
      link.setAttribute("href", `?${url.searchParams.toString()}`);
    }

    // Fold once at wire time too: back/forward navigation restores checkbox state without firing
    // change events, and the server-rendered links only carry the URL-borne selection.
    syncHead();
    updateCount();
    rewriteSelectionLinks();
  }
})();
