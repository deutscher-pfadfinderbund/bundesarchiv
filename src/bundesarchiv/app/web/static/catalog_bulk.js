// Bulk-edit (Sammelbearbeitung) progressive enhancement (spec §5). Enhancement-only: the no-JS
// baseline works without it (page-select is the "Alle auf dieser Seite" link; every value widget
// renders and the server reads the matching one; the bar visibility + count come from the server
// off ?auswahl=). Self-contained, same-origin, no framework (dormancy rule). HTMX (loaded
// separately) handles the dependent-Dokumenttyp swap; this covers what HTMX can't express.
(function () {
  "use strict";

  // Re-init on load AND after any htmx swap of #results (the search hx-swaps it, replacing the form
  // + bar), so the enhancement survives a live search. Idempotent: a data-flag guards double-binding.
  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:afterSwap", init);

  function init() {
    var form = document.querySelector(".wb-sammelform");
    if (!form || form.dataset.bulkBound === "1") return;
    form.dataset.bulkBound = "1";
    wire(form);
  }

  function wire(form) {
  var rowBoxes = function () {
    return Array.prototype.slice.call(form.querySelectorAll('input[name="auswahl"]'));
  };

  // 1. Header "select all on this page" checkbox toggles every row box + updates the live count.
  // Hidden in the no-JS baseline (it has no name, so it's a dead control there); un-hide it now.
  var alle = form.querySelector(".c-ledger-auswahl-alle");
  if (alle) {
    alle.hidden = false;
    alle.addEventListener("change", function () {
      rowBoxes().forEach(function (box) {
        box.checked = alle.checked;
        box.closest(".c-ledger-row").classList.toggle("c-ledger-row--gewaehlt", box.checked);
      });
      updateCount();
    });
  }

  // 2. Live count in the bar (if the bar is present) + row inversion on individual toggle.
  form.addEventListener("change", function (event) {
    if (event.target.name !== "auswahl") return;
    event.target
      .closest(".c-ledger-row")
      .classList.toggle("c-ledger-row--gewaehlt", event.target.checked);
    updateCount();
  });

  // The bar (and its count span) is always in the DOM now (cold-start fix, #16), so the count goes
  // live on the first tick — no early-return. Empty text at zero keeps signals-once (no "0
  // ausgewählt"); the "Alle auf dieser Seite" link + "Änderung prüfen" submit are always present, so
  // a JS user reaches the flow by ticking boxes.
  function updateCount() {
    var zahl = form.querySelector(".wb-sammelleiste-zahl");
    var n = rowBoxes().filter(function (b) {
      return b.checked;
    }).length;
    zahl.textContent = n > 0 ? n + " ausgewählt" : "";
  }

  // 3. Feld chooser: show only the value widget matching the chosen field (no-JS shows all; the
  // server reads the matching one). Widgets carry data-bulk-wert="<space-separated felder>".
  var feld = form.querySelector("[data-bulk-feld]");
  var widgets = Array.prototype.slice.call(form.querySelectorAll("[data-bulk-wert]"));
  if (feld && widgets.length) {
    var sync = function () {
      var chosen = feld.value;
      widgets.forEach(function (w) {
        var owns = w.getAttribute("data-bulk-wert").split(" ").indexOf(chosen) !== -1;
        w.hidden = !owns;
      });
    };
    feld.addEventListener("change", sync);
    sync();
  }
  }
})();
