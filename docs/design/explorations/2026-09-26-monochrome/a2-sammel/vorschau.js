// Mock only: the preview pane's behaviour for the three variants (NOTES-VORSCHAU.md).
// ?v=spalte|rand|zeile picks the variant, ?offen=<Signatur> opens a record. A row opens by a click
// on its free space or its "Vorschau" link; ↑ ↓ move, Esc closes. The app would render the pane on
// the server (?artikel=<ulid>, as today) and enhance the same links.
const params = new URLSearchParams(location.search);
const variante = ["spalte", "rand", "zeile"].includes(params.get("v")) ? params.get("v") : "spalte";
document.body.dataset.variante = variante;

const pane = document.getElementById("vorschau");
const rows = [...document.querySelectorAll(".ledger tbody tr")];
const toggle = document.querySelector(".toolbar-preview");
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
let records = {};
let current = null;

const cell = (row, cls) => row.querySelector(`.${cls}`)?.textContent.trim() ?? "";

function render(row) {
  const sig = row.querySelector(".ledger-pick input")?.value ?? cell(row, "ledger-sig");
  const r = records[sig] ?? {};
  const title = row.querySelector(".ledger-title > a")?.textContent.trim() ?? r.title;
  const digital = cell(row, "ledger-digital");
  const kind = !digital ? null : digital.startsWith("PDF") ? "pdf" : "foto";
  const typ = r.document_type ?? r.media_type ?? cell(row, "ledger-type");
  const standort = r.physical_location?.split(/\s*--\s*/).join(" › ");
  const byline = [
    `<data value="${esc(sig)}">${esc(sig)}</data>`,
    typ && `<span>${esc(typ)}</span>`,
    cell(row, "ledger-date") && `<time>${esc(cell(row, "ledger-date"))}</time>`,
    r.subject_place && `<span>${esc(r.subject_place)}</span>`,
    r.creator && `<span>von ${esc(r.creator)}</span>`,
  ].filter(Boolean).join("");
  const lead = kind
    ? `<figure class="preview-lead" data-kind="${kind}" style="--r: ${kind === "pdf" ? "0.707" : "1.5"}" aria-label="${kind === "pdf" ? "Erste Seite der PDF" : "Erstes Foto"} (Platzhalter)"></figure>
       <p class="preview-files">${esc(digital)}</p>`
    : "";
  pane.innerHTML = `
    <div class="preview-head">
      <h2 class="preview-title">${esc(title)}</h2>
      <a class="preview-close" href="?v=${variante}" aria-label="Vorschau schließen" title="Vorschau schließen"><svg class="icon" aria-hidden="true"><use href="../system/icons.svg#x"/></svg></a>
    </div>
    ${lead}
    <p class="byline">${byline}</p>
    <dl class="facts quiet">
      ${r.bestand ? `<div><dt>Bestand</dt><dd>${esc(r.bestand)}</dd></div>` : ""}
      ${standort ? `<div><dt>Standort</dt><dd>${esc(standort)}</dd></div>` : ""}
    </dl>
    <div class="cluster">
      <a class="button button-primary" href="../r4-system/artikel.html">Öffnen</a>
      <a class="button" href="../a1-formular/bearbeiten.html">Bearbeiten</a>
    </div>
    <p class="preview-keys"><kbd>↑</kbd> <kbd>↓</kbd> nächster Artikel · <kbd>Esc</kbd> schließt</p>`;
  // a title in the pane leads, so the lead comes after the head only in the side variants; in the
  // unfolded row the lead takes the start column (CSS grid), the order above stays the reading order
}

function open(row) {
  if (!row) return;
  rows.forEach((r) => r.removeAttribute("aria-current"));
  document.querySelector(".ledger-unfold")?.remove();
  row.setAttribute("aria-current", "true");
  render(row);
  if (variante === "zeile") {
    const band = document.createElement("tr");
    band.className = "ledger-unfold";
    const td = document.createElement("td");
    td.colSpan = row.children.length;
    td.append(pane);
    band.append(td);
    row.after(band);
  }
  current = row;
  document.body.dataset.offen = "";
  toggle?.setAttribute("aria-pressed", "true");
}

function close() {
  rows.forEach((r) => r.removeAttribute("aria-current"));
  document.querySelector(".ledger-unfold")?.remove();
  if (pane.parentElement !== document.body) document.body.append(pane);
  delete document.body.dataset.offen;
  toggle?.setAttribute("aria-pressed", "false");
  current = null;
}

rows.forEach((row) => {
  row.addEventListener("click", (e) => {
    if (e.target.closest("a:not(.ledger-preview), input, button")) return;
    e.preventDefault();
    if (current === row && variante === "zeile") close();
    else open(row);
  });
});
toggle?.addEventListener("click", () => (current ? close() : open(rows[0])));
document.addEventListener("keydown", (e) => {
  if (!current || e.target.closest("input, select, textarea")) return;
  const i = rows.indexOf(current);
  if (e.key === "ArrowDown" && i < rows.length - 1) { e.preventDefault(); open(rows[i + 1]); rows[i + 1].scrollIntoView({ block: "nearest" }); }
  if (e.key === "ArrowUp" && i > 0) { e.preventDefault(); open(rows[i - 1]); rows[i - 1].scrollIntoView({ block: "nearest" }); }
  if (e.key === "Escape") close();
});

fetch("../data.json")
  .then((r) => r.json())
  .then((d) => {
    records = Object.fromEntries(d.sample_articles.map((a) => [a.ref_code, a]));
  })
  .catch(() => {})
  .finally(() => {
    const sig = params.get("offen");
    if (sig) open(rows.find((r) => r.querySelector(".ledger-pick input")?.value === sig));
  });
