// autocomplete — enhances <div class="autocomplete"> around a text input with list="<datalist id>".
// Without JS the page keeps the plain input: the datalist suggests, and a multiple field is the
// comma-separated text the server already parses. With JS:
//   single (default): a combobox; the listbox suggests, free text stays allowed.
//   [data-multiple]:  chosen values become chips; a hidden input carries "a, b, c" under the
//                     original name, so the server contract does not change.
// Keys: ↓/↑ move, Enter picks the active suggestion (or, multiple, adds the typed text), Esc closes,
// comma adds (multiple), Backspace on an empty input removes the last chip (multiple). Leaving the
// field or submitting the form adds pending text, so nothing typed is lost.
// ARIA: APG combobox with listbox popup (aria-activedescendant); a polite live region says what
// was added or removed.

const ICONS = new URL("icons.svg", import.meta.url).href;
const MAX_SUGGESTIONS = 8;
let uid = 0;

function enhance(root) {
  const input = root.querySelector("input");
  const source = input && document.getElementById(input.getAttribute("list"));
  if (!input || !source) return;
  const multiple = root.hasAttribute("data-multiple");
  const known = [...source.options].map((o) => o.value.trim()).filter(Boolean);
  const id = `ac-${++uid}`;
  const label = input.labels?.[0]?.textContent.trim() ?? "";

  input.removeAttribute("list");
  input.setAttribute("autocomplete", "off");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", `${id}-list`);

  const listbox = document.createElement("ul");
  listbox.id = `${id}-list`;
  listbox.className = "autocomplete-list";
  listbox.setAttribute("role", "listbox");
  if (label) listbox.setAttribute("aria-label", label);
  listbox.hidden = true;

  const live = document.createElement("span");
  live.className = "autocomplete-live";
  live.setAttribute("aria-live", "polite");
  root.append(listbox, live);

  let values = [];
  let chips, hidden;
  if (multiple) {
    values = unique(split(input.value));
    input.value = "";
    hidden = Object.assign(document.createElement("input"), { type: "hidden", name: input.name });
    input.removeAttribute("name");
    chips = document.createElement("ul");
    chips.className = "autocomplete-chips";
    chips.setAttribute("role", "list");
    if (label) chips.setAttribute("aria-label", `Gewählt: ${label}`);
    root.prepend(chips);
    root.append(hidden);
    renderChips();
    root.addEventListener("click", (e) => { if (e.target === root) input.focus(); });
  }
  root.dataset.enhanced = "";

  let matches = [];
  let active = -1;

  function split(text) { return text.split(/[,\n]/).map((v) => v.trim()).filter(Boolean); }
  function unique(list) {
    const seen = new Set();
    return list.filter((v) => !seen.has(v.toLowerCase()) && seen.add(v.toLowerCase()));
  }
  function has(v) { return values.some((x) => x.toLowerCase() === v.toLowerCase()); }
  function say(text) { live.textContent = ""; requestAnimationFrame(() => { live.textContent = text; }); }

  function renderChips() {
    chips.replaceChildren(...values.map((v, i) => {
      const li = document.createElement("li");
      li.className = "chip";
      li.append(v);
      const x = document.createElement("button");
      x.type = "button";
      x.setAttribute("aria-label", `${v} entfernen`);
      x.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${ICONS}#x"/></svg>`;
      x.addEventListener("click", () => removeAt(i));
      li.append(x);
      return li;
    }));
    hidden.value = values.join(", ");
  }

  function add(text) {
    const parts = split(text);
    const added = parts.filter((v) => !has(v) && values.push(v));
    renderChips();
    if (added.length) say(`${added.join(", ")} hinzugefügt`);
    else if (parts.length) say(`${parts.join(", ")} ist schon gewählt`);
  }
  function removeAt(i) {
    const [gone] = values.splice(i, 1);
    renderChips();
    say(`${gone} entfernt`);
    input.focus();
  }
  function commitPending() {
    if (multiple && input.value.trim()) { add(input.value); input.value = ""; }
  }

  function open() {
    const q = input.value.trim().toLowerCase();
    const pool = known.filter((v) => !(multiple && has(v)) && v.toLowerCase().includes(q));
    const starts = pool.filter((v) => v.toLowerCase().startsWith(q));
    matches = [...starts, ...pool.filter((v) => !starts.includes(v))].slice(0, MAX_SUGGESTIONS);
    if (!multiple && matches.length === 1 && matches[0].toLowerCase() === q) matches = [];
    active = -1;
    listbox.replaceChildren(...matches.map((v, i) => {
      const li = document.createElement("li");
      li.id = `${id}-opt-${i}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      li.textContent = v;
      li.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the input
      li.addEventListener("click", () => pick(i));
      return li;
    }));
    listbox.hidden = matches.length === 0;
    input.setAttribute("aria-expanded", String(!listbox.hidden));
    input.removeAttribute("aria-activedescendant");
  }
  function close() {
    listbox.hidden = true;
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }
  function move(step) {
    if (listbox.hidden) { open(); if (listbox.hidden) return; }
    const states = matches.length + 1; // the options plus -1, "back in the input"
    active = (((active + 1 + step) % states) + states) % states - 1;
    [...listbox.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
    if (active < 0) { input.removeAttribute("aria-activedescendant"); return; }
    const li = listbox.children[active];
    input.setAttribute("aria-activedescendant", li.id);
    li.scrollIntoView({ block: "nearest" });
  }
  function pick(i) {
    const v = matches[i];
    if (multiple) { add(v); input.value = ""; } else { input.value = v; input.dispatchEvent(new Event("change", { bubbles: true })); }
    close();
    input.focus();
  }

  input.addEventListener("input", open);
  input.addEventListener("focus", () => { if (input.value.trim()) open(); });
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    switch (e.key) {
      case "ArrowDown": e.preventDefault(); move(1); break;
      case "ArrowUp": e.preventDefault(); move(-1); break;
      case "Escape": if (!listbox.hidden) { e.preventDefault(); close(); } break;
      case "Enter":
        if (active >= 0) { e.preventDefault(); pick(active); }
        else if (multiple && input.value.trim()) { e.preventDefault(); commitPending(); close(); }
        break; // otherwise Enter submits the form, as in any text field
      case ",":
        if (multiple) { e.preventDefault(); commitPending(); close(); }
        break;
      case "Backspace":
        if (multiple && !input.value && values.length) removeAt(values.length - 1);
        break;
      case "Tab": close(); break;
    }
  });
  if (multiple) {
    input.addEventListener("paste", (e) => {
      const text = e.clipboardData?.getData("text") ?? "";
      if (!/[,\n]/.test(text)) return;
      e.preventDefault();
      add(input.value + text);
      input.value = "";
    });
    input.form?.addEventListener("submit", commitPending); // fires before the form data is built
  }
  root.addEventListener("focusout", (e) => {
    if (root.contains(e.relatedTarget)) return;
    close();
    commitPending();
  });
}

document.querySelectorAll(".autocomplete").forEach(enhance);
