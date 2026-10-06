// The article page's media: rows justified by each tile's ratio, and the lightbox over its images.
// Without this script the tiles are plain links to the files and the rows keep equal height.
const rows = document.querySelector(".media-rows > div");
if (rows) {
  for (const figure of rows.children) {
    const img = figure.querySelector("img");
    const ratio = img ? img.getAttribute("width") / img.getAttribute("height") : 1;
    figure.style.setProperty("--r", ratio); // the CSSOM, not a style attribute: CSP
  }
  rows.dataset.justified = "";
}

const dialog = document.querySelector(".lightbox");
if (dialog) {
  const strip = dialog.querySelector(".lightbox-strip");
  const figures = [...strip.children];
  const count = dialog.querySelector(".lightbox-count");
  const prev = dialog.querySelector(".lightbox-prev");
  const next = dialog.querySelector(".lightbox-next");
  const last = figures.length - 1;
  const black = ".lightbox, .lightbox-bar, .lightbox-strip, figure, figcaption"; // not the picture, the buttons, the caption text
  let at = 0;
  let moving = false; // a smooth move is in flight: the observer must not rewrite the counter
  let transition;

  const mark = () => {
    count.textContent = `${at + 1} / ${figures.length}`;
    // a button about to go dead must not take the focus out of the dialog with it
    if (at === 0 && document.activeElement === prev) {
      next.focus();
    }
    if (at === last && document.activeElement === next) {
      prev.focus();
    }
    prev.disabled = at === 0;
    next.disabled = at === last;
  };
  const go = (index, behavior) => {
    const target = Math.max(0, Math.min(last, index));
    moving = behavior !== "instant" && target !== at;
    at = target;
    figures[at].scrollIntoView({ behavior, inline: "center", block: "nearest" });
    mark();
  };
  strip.addEventListener("scrollend", () => {
    moving = false;
  });
  const seen = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && !moving) {
          at = figures.indexOf(entry.target);
          mark();
        }
      }
    },
    { root: strip, threshold: 0.6 },
  );
  for (const figure of figures) {
    seen.observe(figure);
  }
  window.addEventListener("resize", () => dialog.open && go(at, "instant"));

  for (const link of document.querySelectorAll("a[data-lightbox]")) {
    link.addEventListener("click", (event) => {
      if (event.button || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return; // the link's own way: a new tab
      }
      event.preventDefault();
      link.focus(); // the dialog hands focus back here on close
      const index = Number(link.dataset.lightbox);
      const thumb = link.querySelector("img");
      const shown = figures[index].querySelector("img");
      const open = () => {
        if (!dialog.open) {
          dialog.showModal();
        }
        go(index, "instant");
      };
      if (!document.startViewTransition || transition || !thumb) {
        open(); // one morph at a time; a second click just opens
        return;
      }
      thumb.style.setProperty("view-transition-name", "lightbox-image");
      transition = document.startViewTransition(() => {
        open();
        thumb.style.removeProperty("view-transition-name");
        shown.style.setProperty("view-transition-name", "lightbox-image");
      });
      transition.ready.catch(() => {}); // skipped: the dialog still opens
      transition.finished
        .catch(() => {})
        .finally(() => {
          thumb.style.removeProperty("view-transition-name");
          shown.style.removeProperty("view-transition-name");
          transition = undefined;
        });
    });
  }

  prev.addEventListener("click", () => go(at - 1, "auto"));
  next.addEventListener("click", () => go(at + 1, "auto"));
  dialog.querySelector(".lightbox-bar button").addEventListener("click", () => dialog.close());
  // the black: the dialog is full-bleed, so closedby never sees a backdrop click. Closing takes
  // the press and the click both on the black, so a drag that began on the picture never closes.
  let pressedBlack = false;
  dialog.addEventListener("pointerdown", (event) => {
    pressedBlack = event.target.matches(black);
  });
  dialog.addEventListener("click", (event) => {
    if (pressedBlack && event.target.matches(black)) {
      dialog.close();
    }
    pressedBlack = false;
  });
  dialog.addEventListener("keydown", (event) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (step && !(event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)) {
      event.preventDefault();
      go(at + step, "auto");
    }
  });
}
