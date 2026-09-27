// lightbox — turns every .gallery's image links into a full-screen viewer (native <dialog>).
// Without JS the links open the image file itself. Links with a target (a PDF, new tab) are left alone. showModal gives focus containment, Esc and
// focus return; ‹ › buttons and the arrow keys step through the gallery's images and wrap.
const icons = new URL("icons.svg", import.meta.url).href;
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="${icons}#${name}"/></svg>`;

for (const gallery of document.querySelectorAll(".gallery")) {
  const items = [...gallery.querySelectorAll("a:not([target])")].map((a) => ({
    href: a.href,
    alt: a.querySelector("img")?.alt ?? "",
    caption: a.closest("figure")?.querySelector("figcaption")?.textContent ?? "",
    link: a,
  }));
  if (!items.length) continue;

  const box = document.createElement("dialog");
  box.className = "lightbox";
  box.setAttribute("aria-label", "Bildansicht");
  box.innerHTML = `
    <p class="lightbox-count" aria-live="polite"></p>
    <button class="lightbox-close" type="button" aria-label="Schließen">${icon("x")}</button>
    <button class="lightbox-prev" type="button" aria-label="Vorheriges Bild">${icon("chevron-left")}</button>
    <figure><img alt=""><figcaption></figcaption></figure>
    <button class="lightbox-next" type="button" aria-label="Nächstes Bild">${icon("chevron-right")}</button>`;
  document.body.append(box);
  const [count, img, caption, figure] = ["lightbox-count", "img", "figcaption", "figure"].map((s) => box.querySelector(s.includes("-") ? "." + s : s));
  let at = 0;
  const show = (i) => {
    at = (i + items.length) % items.length;
    const it = items[at];
    img.src = it.href; img.alt = it.alt; caption.textContent = it.caption;
    count.textContent = `${at + 1} / ${items.length}`;
    figure.toggleAttribute("data-single", items.length === 1);
  };
  items.forEach((it, i) => it.link.addEventListener("click", (e) => { e.preventDefault(); show(i); box.showModal(); }));
  box.querySelector(".lightbox-prev").addEventListener("click", () => show(at - 1));
  box.querySelector(".lightbox-next").addEventListener("click", () => show(at + 1));
  box.querySelector(".lightbox-close").addEventListener("click", () => box.close());
  box.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") show(at - 1);
    if (e.key === "ArrowRight") show(at + 1);
  });
  box.addEventListener("close", () => items[at].link.focus());
}
