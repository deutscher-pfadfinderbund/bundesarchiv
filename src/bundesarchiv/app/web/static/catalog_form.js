// Cataloging-form progressive enhancement (Part 4.7 Slice E, spec §5).
//
// Every behaviour here is ENHANCEMENT-ONLY: the no-JS baseline works without it (the dirty register
// is simply absent, custom rows are added by the always-present empty row + a save round-trip, the
// upload shows no progress sliver). Self-contained, same-origin, no framework (dormancy rule) — one
// script, three small features. HTMX (loaded separately) handles the AJAX swaps; this only covers
// what HTMX can't express declaratively. No motion (spec law): the progress sliver grows in discrete
// XHR-reported steps, no transitions.
(function () {
  "use strict";

  var form = document.getElementById("bearbeiten-form");

  // 1. Dirty register — reveal the amber "Nicht gespeicherte Änderungen" chip on the first edit.
  // No-JS can't detect dirtiness, so the baseline hides the chip (hidden attr); JS unhides it once.
  if (form) {
    var status = document.querySelector(".c-form-status");
    if (status) {
      // { once: true } — the register only needs revealing the first time an edit happens.
      form.addEventListener(
        "input",
        function () {
          status.hidden = false;
        },
        { once: true }
      );
    }
  }

  // 2. Custom bag — client-side add/remove of key/value rows. Baseline: the always-present trailing
  // empty row is the "add" affordance and empties drop server-side; this just spares a round-trip.
  var bag = document.querySelector(".c-form-details");
  if (bag) {
    bag.addEventListener("input", function (event) {
      // typing into the LAST row's key/value grows a fresh empty row (so there's always one spare)
      var row = event.target.closest(".c-form-bag-zeile");
      if (!row) return;
      var rows = bag.querySelectorAll(".c-form-bag-zeile");
      if (row === rows[rows.length - 1] && event.target.value !== "") {
        var clone = row.cloneNode(true);
        clone.querySelectorAll("input").forEach(function (i) {
          i.value = "";
        });
        row.after(clone);
      }
    });
    bag.addEventListener("click", function (event) {
      // a client-side remove link on a row clears + drops it (baseline: the server drops empties)
      if (!event.target.matches(".c-form-bag-entfernen")) return;
      event.preventDefault();
      var row = event.target.closest(".c-form-bag-zeile");
      var rows = bag.querySelectorAll(".c-form-bag-zeile");
      if (row && rows.length > 1) row.remove();
      else if (row)
        row.querySelectorAll("input").forEach(function (i) {
          i.value = "";
        });
    });
  }

  // 3. Upload progress — a discrete sliver reporting XHR upload progress (spec §6.3: no easing, no
  // spinner). HTMX fires htmx:xhr:progress on the upload; we paint the fill width in whole percent.
  document.body.addEventListener("htmx:xhr:progress", function (event) {
    var sliver = document.getElementById("medien-fortschritt-fill");
    if (!sliver || !event.detail || !event.detail.lengthComputable) return;
    var percent = Math.round((event.detail.loaded / event.detail.total) * 100);
    sliver.style.width = percent + "%";
  });
})();
