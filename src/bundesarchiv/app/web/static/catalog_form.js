(() => {
  "use strict";

  // 1. Dirty register — reveal the "Nicht gespeicherte Änderungen" mark on the first edit.
  // No-JS can't detect dirtiness, so the baseline hides the mark (hidden attr); JS unhides it.
  // Listen on the document and match the field's form OWNER, not DOM ancestry: caption and
  // custom-bag fields sit OUTSIDE #edit-form's subtree (the #media-drawer fieldset holds the
  // real per-row forms, and forms cannot nest) but still ride its save via form= — an edit there is
  // just as unsaved. Re-querying by id also keeps working after an hx #form-region swap.
  document.addEventListener("input", (event) => {
    const field = event.target;
    if (field.form?.id !== "edit-form") {
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
  // The reverse proxy closes any request after 60 s; the archivists' line does about 1.3 MB/s.
  const LARGE_UPLOAD_BYTES = 50 * 1024 * 1024;
  document.addEventListener("change", (event) => {
    const input = event.target;
    if (input.matches?.('.upload input[type="file"]') && input.files.length > 0) {
      if (Array.from(input.files).some((file) => file.size > LARGE_UPLOAD_BYTES)) {
        showUploadNotice("Große Datei. Hochladen, das länger als 60 Sekunden dauert, bricht ab.");
      }
      input.form.requestSubmit();
    }
  });

  // 3. Upload notice — a failed upload swaps nothing (the htmx-config noSwap), so the drawer says
  // why the files did not arrive; a later swap of the drawer brings the notice back hidden.
  function showUploadNotice(text) {
    const notice = document.getElementById("upload-notice");
    if (notice) {
      notice.textContent = text;
      notice.hidden = false;
    }
  }
  const UPLOAD_ABORTED =
    "Abgebrochen: Hochladen darf höchstens 60 Sekunden dauern. Melde dich bei BBI.";
  // the gateway's cuts: nginx answers 400 for a truncated body; the upload view never does
  const GATEWAY_CUT = [400, 502, 504];
  document.addEventListener("htmx:response:error", (event) => {
    if (
      event.target.id === "media-upload" &&
      GATEWAY_CUT.includes(event.detail.ctx.response.status)
    ) {
      showUploadNotice(UPLOAD_ABORTED);
    }
  });
  document.addEventListener("htmx:error", (event) => {
    if (event.target.id === "media-upload" && event.detail.error?.name !== "AbortError") {
      showUploadNotice(UPLOAD_ABORTED);
    }
  });
})();
