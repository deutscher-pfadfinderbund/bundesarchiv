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
  // With tus each file goes up in pieces and is finished on its own, one after another (ADR 0026);
  // without it the form posts the files in one request.
  document.documentElement.dataset.uploadOnChoose = "";
  const PIECE_BYTES = 8 * 1024 * 1024;
  // the pieces' and the finish's retries, in ms
  const RETRY_DELAYS = [0, 1000, 3000, 5000];
  const TOO_LARGE = "Datei zu groß (>4 GB)";
  const ABORTED = "Hochladen abgebrochen";
  const queue = [];
  let batch = null;
  const UPLOAD_INPUT = '.upload input[type="file"]';
  document.addEventListener("change", (event) => {
    if (event.target.matches?.(UPLOAD_INPUT)) {
      choose(event.target);
    }
  });
  // A finish swaps the drawer, input and all, while the picker may be open: the files then come to
  // a detached input, whose change never reaches the document.
  document.addEventListener("click", (event) => {
    if (event.target.matches?.(UPLOAD_INPUT)) {
      event.target.addEventListener("change", chosenAfterSwap);
    }
  });
  function chosenAfterSwap(event) {
    if (!event.target.isConnected) {
      choose(event.target);
    }
  }

  function choose(input) {
    if (input.files.length === 0) {
      return;
    }
    if (!globalThis.tus?.isSupported) {
      input.form.requestSubmit();
      return;
    }
    queue.push(...input.files);
    // a finish posts this form, which must not carry the files again
    input.value = "";
    if (batch) {
      drawProgress();
    } else {
      uploadQueued();
    }
  }

  async function uploadQueued() {
    batch = { position: 0, percent: 0, failures: [] };
    addEventListener("beforeunload", askBeforeLeaving);
    try {
      while (queue.length > 0) {
        batch.position += 1;
        const file = queue.shift();
        const failure = await uploadOne(file);
        if (failure !== null) {
          batch.failures.push(`${file.name}: ${failure}`);
        }
        if (batch.failures.length > 0) {
          showUploadNotice(batch.failures);
        }
      }
    } finally {
      showProgress(null);
      removeEventListener("beforeunload", askBeforeLeaving);
      batch = null;
    }
  }

  // Why the file did not land, or null once it did; anything thrown on its way fails it alone.
  async function uploadOne(file) {
    try {
      return (await finish(await sendPieces(file))) ? null : ABORTED;
    } catch (error) {
      return error?.originalResponse?.getStatus() === 413 ? TOO_LARGE : ABORTED;
    }
  }

  function askBeforeLeaving(event) {
    event.preventDefault();
  }

  // Resolves to the upload's id once all its bytes are in; rejects with tus's error.
  function sendPieces(file) {
    const form = document.getElementById("media-upload");
    const progress = (percent) => {
      batch.percent = percent;
      drawProgress();
    };
    progress(0);
    return new Promise((resolve, reject) => {
      const upload = new globalThis.tus.Upload(file, {
        endpoint: form.dataset.tusEndpoint,
        chunkSize: PIECE_BYTES,
        retryDelays: RETRY_DELAYS,
        metadata: { filename: file.name, filetype: file.type },
        headers: { "X-CSRFToken": form.elements.csrfmiddlewaretoken.value },
        removeFingerprintOnSuccess: true,
        onProgress: (sent, total) => {
          const percent = Math.floor((sent / total) * 100);
          if (percent !== batch.percent) {
            progress(percent);
          }
        },
        onSuccess: () => resolve(upload.url.split("/").pop()),
        onError: reject,
      });
      upload
        .findPreviousUploads()
        .then((previous) => {
          if (previous.length > 0) {
            upload.resumeFromPreviousUpload(previous[0]);
          }
          upload.start();
        })
        .catch(reject);
    });
  }

  // Whether the file landed. The server answers a repeated finish as it did the first (ADR 0026),
  // so a finish that got no answer or a 5xx goes again after the pieces' delays; any other refusal
  // is final.
  async function finish(uploadId) {
    const delays = RETRY_DELAYS;
    for (let attempt = 0; ; attempt += 1) {
      const status = await postFinish(uploadId);
      if (status > 0 && status < 400) {
        return true;
      }
      if ((status > 0 && status < 500) || attempt === delays.length) {
        return false;
      }
      await new Promise((resume) => setTimeout(resume, delays[attempt]));
    }
  }

  // Posts the upload form as htmx does, so its answer swaps the drawer like a posted file's;
  // resolves to the answer's status, 0 without one (htmx.ajax resolves on every failure).
  async function postFinish(uploadId) {
    const form = document.getElementById("media-upload");
    let status = 0;
    const answered = (event) => {
      status = event.detail.ctx.response.status;
    };
    form.addEventListener("htmx:after:request", answered);
    try {
      await htmx.ajax("POST", form.action, { source: form, values: { upload_id: uploadId } });
    } finally {
      form.removeEventListener("htmx:after:request", answered);
    }
    return status;
  }

  function drawProgress() {
    const { position, percent } = batch;
    showProgress({ position, total: position + queue.length, percent });
  }

  // The one place the busy state is drawn: "2/3 · 40 %", a single file just "40 %"; null when done.
  function showProgress(progress) {
    const shown = document.getElementById("upload-progress");
    if (!shown) {
      return;
    }
    shown.hidden = progress === null;
    if (progress !== null) {
      const { position, total, percent } = progress;
      shown.textContent = total > 1 ? `${position}/${total} · ${percent} %` : `${percent} %`;
    }
  }

  // 3. Upload notice — a failed upload swaps nothing (the htmx-config noSwap), so the drawer says
  // why its files did not arrive, a line per file in a batch. A later swap of the drawer brings
  // the notice back hidden, so a running batch shows it again after each file; the batch decides
  // its own failures, the events below are the no-tus post's.
  function showUploadNotice(lines) {
    const notice = document.getElementById("upload-notice");
    if (notice) {
      notice.replaceChildren(
        ...lines.flatMap((line, n) => (n > 0 ? [document.createElement("br"), line] : [line])),
      );
      notice.hidden = false;
    }
  }
  document.addEventListener("htmx:response:error", (event) => {
    if (event.target.id === "media-upload" && !batch) {
      showUploadNotice([ABORTED]);
    }
  });
  document.addEventListener("htmx:error", (event) => {
    if (event.target.id === "media-upload" && !batch && event.detail.error?.name !== "AbortError") {
      showUploadNotice([ABORTED]);
    }
  });
})();
