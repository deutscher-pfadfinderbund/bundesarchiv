// Cataloging-form progressive enhancement (Part 4.7 Slice E, spec §5).
//
// Every behaviour here is ENHANCEMENT-ONLY: the no-JS baseline works without it (the dirty register
// is simply absent, an upload takes the native input and its submit).
// Self-contained, same-origin, no framework (dormancy rule) — one script, two small features. HTMX
// (loaded separately) handles the AJAX swaps; this only covers what HTMX can't express declaratively.
(() => {
  "use strict";

  // 1. Dirty register — reveal the "Nicht gespeicherte Änderungen" mark on the first edit.
  // No-JS can't detect dirtiness, so the baseline hides the mark (hidden attr); JS unhides it.
  // Listen on the document and match the field's form OWNER, not DOM ancestry: caption and
  // custom-bag fields sit OUTSIDE #bearbeiten-form's subtree (the #medien-drawer fieldset holds the
  // real per-row forms, and forms cannot nest) but still ride its save via form= — an edit there is
  // just as unsaved. Re-querying by id also keeps working after an hx #form-region swap.
  document.addEventListener("input", (event) => {
    const field = event.target;
    if (field.form?.id !== "bearbeiten-form") {
      return;
    }
    const status = document.getElementById("dirty-flag");
    if (status) {
      status.hidden = false;
    }
  });

  // 2. Upload on choose — the chosen files go up at once; the CSS hides the native input and the
  // submit only once this script has marked the root, so a page without it keeps the no-JS path.
  document.documentElement.dataset.uploadOnChoose = "";
  document.addEventListener("change", (event) => {
    const input = event.target;
    if (input.matches?.('.upload input[type="file"]') && input.files.length > 0) {
      input.form.requestSubmit();
    }
  });
})();
