// Cataloging-form progressive enhancement (Part 4.7 Slice E, spec §5).
//
// Every behaviour here is ENHANCEMENT-ONLY: the no-JS baseline works without it (the dirty register
// is simply absent, an upload takes the native input and its submit).
// Self-contained, same-origin, no framework (dormancy rule) — one script, three small features. HTMX
// (loaded separately) handles the AJAX swaps; this only covers what HTMX can't express declaratively.
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
  document.addEventListener("change", (event) => {
    const input = event.target;
    if (input.matches?.('.upload input[type="file"]') && input.files.length > 0) {
      input.form.requestSubmit();
    }
  });

  // 3. Suggestions — a textarea with data-suggest offers the archive's own values for the line the
  // caret is on (the Schlagworte, one per line). ARIA: the textbox keeps its role (a textarea may
  // not be a combobox) and points into the listbox with aria-activedescendant; the list is a manual
  // popover, so the focus never leaves the field. Taking a value replaces that line only.
  const SUGGEST = "textarea[data-suggest]";
  let asked = 0; // the newest request; an older answer arrives too late and is dropped
  let typing;
  let target; // the line the open list was suggested for: { start, text }

  function listOf(field) {
    return document.getElementById(`${field.id}-suggestions`);
  }

  function enhance(field) {
    if (listOf(field)) {
      return;
    }
    const list = document.createElement("ul");
    list.id = `${field.id}-suggestions`;
    list.className = "autocomplete-list";
    list.popover = "manual";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Vorschläge");
    const status = document.createElement("span");
    status.id = `${field.id}-suggestions-status`;
    status.className = "visually-hidden";
    status.setAttribute("aria-live", "polite");
    field.after(list, status);
    field.setAttribute("aria-autocomplete", "list");
    field.setAttribute("aria-controls", list.id);
  }
  document.querySelectorAll(SUGGEST).forEach(enhance);
  // a save re-render swaps in a fresh field
  document.addEventListener("htmx:load", (event) => {
    event.detail.elt.querySelectorAll?.(SUGGEST).forEach(enhance);
  });

  function lineAt(field) {
    const caret = field.selectionStart;
    const start = caret === 0 ? 0 : field.value.lastIndexOf("\n", caret - 1) + 1;
    const end = field.value.indexOf("\n", caret);
    return [start, end < 0 ? field.value.length : end];
  }

  function statusOf(field) {
    return document.getElementById(`${field.id}-suggestions-status`);
  }

  function close(field) {
    asked += 1;
    target = undefined;
    clearTimeout(typing);
    field.removeAttribute("aria-activedescendant");
    const list = listOf(field);
    if (list?.matches(":popover-open")) {
      list.hidePopover();
    }
  }

  function suggest(field) {
    const [start, end] = lineAt(field);
    const q = field.value.slice(start, end).trim();
    close(field);
    statusOf(field).textContent = "";
    if (!q) {
      return;
    }
    const ticket = asked;
    const params = new URLSearchParams({ q, tags: field.value });
    fetch(`${field.dataset.suggest}?${params}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(response.status);
        }
        return response.text();
      })
      .then((html) => {
        const list = listOf(field);
        if (
          ticket !== asked ||
          document.activeElement !== field ||
          !list ||
          lineAt(field)[0] !== start
        ) {
          return;
        }
        list.innerHTML = html;
        const options = [...list.children];
        options.forEach((option, i) => {
          option.id = `${list.id}-${i}`;
        });
        if (options.length > 0) {
          statusOf(field).textContent =
            options.length === 1 ? "1 Vorschlag" : `${options.length} Vorschläge`;
          target = { start, text: q };
          list.showPopover();
        }
      })
      .catch(() => {
        if (ticket === asked) {
          close(field);
        }
      });
  }

  function mark(field, options, index) {
    options.forEach((option, i) => {
      option.ariaSelected = String(i === index);
    });
    if (index < 0) {
      field.removeAttribute("aria-activedescendant");
    } else {
      field.setAttribute("aria-activedescendant", options[index].id);
      options[index].scrollIntoView({ block: "nearest" });
    }
  }

  function take(field, value) {
    const [start, end] = lineAt(field);
    // the list was suggested for one line; if the caret or the text moved off it, change nothing
    if (!target || target.start !== start || field.value.slice(start, end).trim() !== target.text) {
      close(field);
      return;
    }
    field.setRangeText(value, start, end, "end");
    close(field);
    field.dispatchEvent(new Event("input", { bubbles: true })); // the dirty register
  }

  document.addEventListener("input", (event) => {
    const field = event.target;
    // an untrusted input is take()'s own: the line is complete, nothing to suggest
    if (event.isTrusted && field.matches?.(SUGGEST)) {
      clearTimeout(typing);
      typing = setTimeout(() => suggest(field), 150);
    }
  });

  document.addEventListener("keydown", (event) => {
    const field = event.target;
    const list = field.matches?.(SUGGEST) && listOf(field);
    if (!list?.matches(":popover-open") || event.isComposing) {
      return;
    }
    const options = [...list.children];
    const active = options.findIndex((option) => option.ariaSelected === "true");
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      // the positions are the options plus -1, the field itself
      const states = options.length + 1;
      const step = event.key === "ArrowDown" ? 1 : -1;
      mark(field, options, ((active + 1 + step + states) % states) - 1);
    } else if ((event.key === "Enter" || event.key === "Tab") && active >= 0) {
      event.preventDefault();
      take(field, options[active].textContent);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(field);
    }
  });

  // the caret moving to another line (a click, Home/End stay on theirs) ends the offer
  document.addEventListener("selectionchange", () => {
    const field = document.activeElement;
    if (target && field?.matches?.(SUGGEST) && lineAt(field)[0] !== target.start) {
      // hide only: the request or timer already pending belongs to the line the caret moved to
      target = undefined;
      field.removeAttribute("aria-activedescendant");
      listOf(field).hidePopover();
    }
  });

  document.addEventListener("focusout", (event) => {
    if (event.target.matches?.(SUGGEST)) {
      close(event.target);
    }
  });

  // a click on an option must not take the focus out of the field (that would close the list)
  document.addEventListener("mousedown", (event) => {
    if (event.target.closest?.(".autocomplete-list")) {
      event.preventDefault();
    }
  });
  document.addEventListener("click", (event) => {
    const option = event.target.closest?.('.autocomplete-list [role="option"]');
    const field = option && document.querySelector(`[aria-controls="${option.parentElement.id}"]`);
    if (field) {
      take(field, option.textContent);
    }
  });
})();
