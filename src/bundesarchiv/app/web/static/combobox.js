// Suggestions while typing — a field with data-suggest offers the options its route answers, in a
// manual popover listbox beside it, so the focus never leaves the field (aria-activedescendant).
// Enhancement only: without this script, or without popover support, the field is a plain field.
//
// Two kinds of field share it:
// - a textarea (the edit form's Schlagworte, one per line) is offered values for the line the caret
//   is on; it keeps its textbox role (a textarea may not be a combobox), and a pick replaces that
//   line only.
// - a search input gets role="combobox" and sends its whole form (q and the list's filters); its
//   options are links, so Enter follows the marked one and a click is the browser's own.
(() => {
  "use strict";

  if (!Object.hasOwn(HTMLElement.prototype, "popover")) {
    return;
  }

  const FIELD = "[data-suggest]";
  let asked = 0; // the newest request; an older answer arrives too late and is dropped
  let typing;
  let target; // what the open list was suggested for: { start, text }

  const isLines = (field) => field.localName === "textarea";

  function listOf(field) {
    return document.getElementById(`${field.id}-suggestions`);
  }

  function statusOf(field) {
    return document.getElementById(`${field.id}-suggestions-status`);
  }

  function optionsOf(list) {
    return [...list.querySelectorAll('[role="option"]')];
  }

  function enhance(field) {
    if (listOf(field)) {
      return;
    }
    // grouped options need a div; a textarea's options are the list's own items
    const list = document.createElement(isLines(field) ? "ul" : "div");
    list.id = `${field.id}-suggestions`;
    list.className = "autocomplete-list";
    list.popover = "manual";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Vorschläge");
    const status = document.createElement("span");
    status.id = `${field.id}-suggestions-status`;
    status.className = "visually-hidden";
    status.setAttribute("aria-live", "polite");
    // outside a heading: its accessible name would take in the list and the status
    (field.closest('[role="heading"]') ?? field).after(list, status);
    if (!isLines(field)) {
      field.setAttribute("role", "combobox");
      field.setAttribute("aria-expanded", "false");
      field.autocomplete = "off";
    }
    field.setAttribute("aria-autocomplete", "list");
    field.setAttribute("aria-controls", list.id);
  }
  document.querySelectorAll(FIELD).forEach(enhance);
  // a save re-render swaps in a fresh field
  document.addEventListener("htmx:load", (event) => {
    event.detail.elt.querySelectorAll?.(FIELD).forEach(enhance);
  });

  // [start, end] of the text the field asks about: the caret's line, or the whole value
  function spanOf(field) {
    if (!isLines(field)) {
      return [0, field.value.length];
    }
    const caret = field.selectionStart;
    const start = caret === 0 ? 0 : field.value.lastIndexOf("\n", caret - 1) + 1;
    const end = field.value.indexOf("\n", caret);
    return [start, end < 0 ? field.value.length : end];
  }

  function close(field) {
    asked += 1;
    target = undefined;
    clearTimeout(typing);
    field.removeAttribute("aria-activedescendant");
    statusOf(field).textContent = "";
    const list = listOf(field);
    if (list?.matches(":popover-open")) {
      list.hidePopover();
    }
    if (field.hasAttribute("aria-expanded")) {
      field.setAttribute("aria-expanded", "false");
    }
  }

  function query(field, q) {
    return isLines(field)
      ? new URLSearchParams({ q, tags: field.value })
      : new URLSearchParams(new FormData(field.form));
  }

  function suggest(field) {
    const [start, end] = spanOf(field);
    const q = field.value.slice(start, end).trim();
    if (!q) {
      close(field);
      return;
    }
    // an open list stays until the answer replaces it; only the older request is dropped
    asked += 1;
    const ticket = asked;
    fetch(`${field.dataset.suggest}?${query(field, q)}`)
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
          spanOf(field)[0] !== start
        ) {
          return;
        }
        list.innerHTML = html;
        const options = optionsOf(list);
        options.forEach((option, i) => {
          option.id = `${list.id}-${i}`;
        });
        if (options.length === 0) {
          close(field);
          return;
        }
        field.removeAttribute("aria-activedescendant");
        statusOf(field).textContent =
          options.length === 1 ? "1 Vorschlag" : `${options.length} Vorschläge`;
        target = { start, text: q };
        if (!list.matches(":popover-open")) {
          list.showPopover();
        }
        if (field.hasAttribute("aria-expanded")) {
          field.setAttribute("aria-expanded", "true");
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

  function take(field, option) {
    const [start, end] = spanOf(field);
    // the list was suggested for one text; if the caret or the text moved off it, change nothing
    if (!target || target.start !== start || field.value.slice(start, end).trim() !== target.text) {
      close(field);
      return;
    }
    close(field);
    if (option.href) {
      location.assign(option.href);
    } else {
      field.setRangeText(option.textContent, start, end, "end");
      field.dispatchEvent(new Event("input", { bubbles: true })); // the dirty register
    }
  }

  document.addEventListener("input", (event) => {
    const field = event.target;
    // an untrusted input is take()'s own: the line is complete, nothing to suggest
    if (event.isTrusted && field.matches?.(FIELD)) {
      // the list on show is for the text before this key: nothing in it is marked for Enter
      const list = listOf(field);
      if (list) {
        mark(field, optionsOf(list), -1);
      }
      clearTimeout(typing);
      typing = setTimeout(() => suggest(field), 150);
    }
  });

  document.addEventListener("keydown", (event) => {
    const field = event.target;
    const list = field.matches?.(FIELD) && listOf(field);
    if (!list?.matches(":popover-open") || event.isComposing) {
      return;
    }
    const options = optionsOf(list);
    const active = options.findIndex((option) => option.ariaSelected === "true");
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      // the positions are the options plus -1, the field itself
      const states = options.length + 1;
      const step = event.key === "ArrowDown" ? 1 : -1;
      mark(field, options, ((active + 1 + step + states) % states) - 1);
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      take(field, options[active]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(field);
    }
  });

  // the caret moving to another line (a click, Home/End stay on theirs) ends the offer
  document.addEventListener("selectionchange", () => {
    const field = document.activeElement;
    if (target && field?.matches?.(FIELD) && spanOf(field)[0] !== target.start) {
      // hide only: the request or timer already pending belongs to the line the caret moved to
      target = undefined;
      field.removeAttribute("aria-activedescendant");
      statusOf(field).textContent = "";
      listOf(field).hidePopover();
    }
  });

  document.addEventListener("focusout", (event) => {
    const field = event.target;
    if (field.matches?.(FIELD) && !listOf(field)?.contains(event.relatedTarget)) {
      close(field);
    }
  });

  // a press in the list must not take the focus out of the field (that would close the list) …
  document.addEventListener("mousedown", (event) => {
    if (event.target.closest?.(".autocomplete-list") && !event.target.closest("a[href]")) {
      event.preventDefault();
    }
  });
  // … but a press on a link is let through: a prevented one there makes Chromium drop a modified
  // click's new tab now and then. The link takes the focus and hands it straight back.
  document.addEventListener("focusin", (event) => {
    const list = event.target.closest?.(".autocomplete-list");
    if (list) {
      document.querySelector(`[aria-controls="${list.id}"]`)?.focus();
    }
  });
  // a link option is followed by the browser (a new tab on a middle or modified click)
  document.addEventListener("click", (event) => {
    const option = event.target.closest?.('.autocomplete-list [role="option"]:not([href])');
    const list = option?.closest(".autocomplete-list");
    const field = list && document.querySelector(`[aria-controls="${list.id}"]`);
    if (field) {
      take(field, option);
    }
  });
})();
