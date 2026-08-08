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

  // 1. Dirty register — reveal the neutral "Nicht gespeicherte Änderungen" badge on the first
  // edit (amber is licensed only on the ENTWURF badge — cue-register row 4). No-JS can't detect
  // dirtiness, so the baseline hides the badge (hidden attr); JS unhides it.
  // Listen on the document and match the field's form OWNER, not DOM ancestry: caption and
  // custom-bag fields sit OUTSIDE #bearbeiten-form's subtree (the #medien-drawer fieldset holds the
  // real per-row forms, and forms cannot nest) but still ride its save via form= — an edit there is
  // just as unsaved. Re-querying by id also keeps working after an hx #form-region swap.
  document.addEventListener("input", function (event) {
    var field = event.target;
    if (!field.form || field.form.id !== "bearbeiten-form") return;
    var status = document.getElementById("dirty-flag");
    if (status) status.hidden = false;
  });

  // 2. Custom bag — client-side add/remove of key/value rows. Baseline: the always-present trailing
  // empty row is the "add" affordance and empties drop server-side; this just spares a round-trip.
  //
  // DELEGATED ON THE DOCUMENT, like the dirty register above, and for the same reason one level
  // further on: this used to hold a reference to #custom-bag captured at LOAD time, so after any
  // #form-region swap — which every validation error, CAS conflict and index-lag re-render performs —
  // the bag in the DOM was a NEW node and the client-side add/remove was simply dead until a full
  // reload. Nothing said so; the no-JS baseline still worked, one round-trip at a time. The wave's own
  // fix for the sibling class (catalog_bulk.js re-initialising on htmx:historyRestore) covered only
  // the OTHER enhancement. Delegation needs no re-init at all: there is nothing to bind, so a swap
  // and a history restore are both non-events (learning G.25, H.8).
  document.addEventListener("input", function (event) {
    // typing into the LAST row's key/value grows a fresh empty row (so there's always one spare)
    var row = event.target.closest && event.target.closest(".bag-row");
    var bag = row && row.closest("#custom-bag");
    if (!bag) return;
    var rows = bag.querySelectorAll(".bag-row");
    if (row === rows[rows.length - 1] && event.target.value !== "") {
      var clone = row.cloneNode(true);
      clone.querySelectorAll("input").forEach(function (i) {
        i.value = "";
      });
      row.after(clone);
    }
  });
  document.addEventListener("click", function (event) {
    // a client-side remove link on a row clears + drops it (baseline: the server drops empties)
    if (!event.target.matches || !event.target.matches('button[name="custom_entfernen"]')) return;
    var row = event.target.closest(".bag-row");
    var bag = row && row.closest("#custom-bag");
    if (!bag) return;
    event.preventDefault();
    var rows = bag.querySelectorAll(".bag-row");
    if (rows.length > 1) row.remove();
    else
      row.querySelectorAll("input").forEach(function (i) {
        i.value = "";
      });
  });

  // 3. Upload progress — a discrete sliver reporting XHR upload progress (spec §6.3: no easing, no
  // spinner). HTMX fires htmx:xhr:progress on the upload; we paint the fill width in whole percent.
  // On the DOCUMENT, not document.body: a history restore replaces the body from htmx's snapshot, and
  // a listener bound to the old body node dies with it — the same class as the bag above.
  document.addEventListener("htmx:xhr:progress", function (event) {
    var sliver = document.getElementById("medien-fortschritt-fill");
    if (!sliver || !event.detail || !event.detail.lengthComputable) return;
    var percent = Math.round((event.detail.loaded / event.detail.total) * 100);
    sliver.style.width = percent + "%";
  });
})();
