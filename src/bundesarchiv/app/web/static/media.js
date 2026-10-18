// The article page's media: rows justified by each tile's ratio, and opening the lightbox at the clicked image.
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
  const slides = [...strip.children];
  const live = dialog.querySelector("[aria-live]");
  const prev = dialog.querySelector(".lightbox-prev");
  const next = dialog.querySelector(".lightbox-next");
  const last = slides.length - 1;
  let on = 0; // the slide on screen, read off the scroll offset
  let heading; // the slide a step scrolls to, until the strip gets there: a fast second step adds to it

  const arm = (to) => {
    // a button about to go dead hands the focus to its pair, or the focus would leave the dialog
    if (to === 0 && document.activeElement === prev) {
      next.focus();
    }
    if (to === last && document.activeElement === next) {
      prev.focus();
    }
    prev.disabled = to === 0;
    next.disabled = to === last;
  };
  const show = (index) => {
    on = index;
    live.textContent = slides[index].querySelector(".lightbox-count").textContent;
  };
  const go = (step) => {
    heading = Math.max(0, Math.min(last, (heading ?? on) + step));
    arm(heading);
    strip.scrollTo({ left: heading * strip.clientWidth });
  };
  strip.addEventListener("scroll", () => {
    const index = Math.round(strip.scrollLeft / strip.clientWidth);
    if (index === heading) {
      heading = undefined;
    }
    if (index !== on) {
      show(index);
    }
    arm(heading ?? index);
  });
  // a swipe or a wheel takes over from a step: the next step counts from where it lands
  for (const type of ["pointerdown", "wheel"]) {
    strip.addEventListener(type, () => (heading = undefined), { passive: true });
  }
  prev.addEventListener("click", () => go(-1));
  next.addEventListener("click", () => go(1));
  dialog.addEventListener("keydown", (event) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (step && !(event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)) {
      event.preventDefault(); // the browser's own step drops a second press while the first scrolls
      go(step);
    }
  });

  const open = (index) => {
    if (!dialog.open) {
      dialog.showModal();
    }
    strip.scrollTo({ left: index * strip.clientWidth, behavior: "instant" });
    heading = undefined;
    show(index); // opening where the strip already stands scrolls nothing
    arm(index);
  };
  // The morph: detail.css names the image of the [data-morph] tile and slide during a transition
  // of type "lightbox". Without types, or under reduced motion, the dialog only fades.
  const typed = CSS.supports("selector(:active-view-transition-type(lightbox))");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const morphs = () => typed && !reduced.matches;
  const tileOf = (index) => document.querySelector(`a[data-lightbox="${index}"]`);
  const inView = (element) => {
    const box = element.getBoundingClientRect();
    return box.bottom > 0 && box.right > 0 && box.top < innerHeight && box.left < innerWidth;
  };
  const unmark = () => {
    for (const marked of document.querySelectorAll("[data-morph]")) {
      delete marked.dataset.morph;
    }
  };
  // settles when the morph has played or was skipped (an Esc mid-morph): the update runs either way
  const morph = (index, update) => {
    unmark();
    tileOf(index).dataset.morph = "";
    slides[index].dataset.morph = "";
    const transition = document.startViewTransition({ update, types: ["lightbox"] });
    transition.ready.catch(() => {});
    return transition.finished.catch(() => {});
  };
  // The shown image is lazy in the closed dialog: it loads first, or the morph grows into an empty
  // box. A slow load opens without the morph.
  const loaded = (img) => {
    img.loading = "eager";
    return Promise.race([
      img.decode().then(
        () => true,
        () => false,
      ),
      new Promise((resolve) => setTimeout(resolve, 300, false)),
    ]);
  };
  let latest; // the last tile click: an earlier one still waiting for its picture gives way
  let opening; // an open morph under way: a second click would restart it from the open dialog
  for (const link of document.querySelectorAll("a[data-lightbox]")) {
    link.addEventListener("click", async (event) => {
      if (event.button || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return; // the link's own way: a new tab
      }
      event.preventDefault();
      link.focus(); // Safari never focuses a clicked link
      const index = Number(link.dataset.lightbox);
      const click = {};
      latest = click;
      const grow = morphs() && (await loaded(slides[index].querySelector("img")));
      if (click !== latest || opening) {
        return;
      }
      if (grow) {
        opening = morph(index, () => open(index)).then(() => (opening = undefined));
      } else {
        open(index);
      }
    });
  }
  // the morph lands on the shown slide's tile, so only on one in view
  const close = () => {
    if (morphs() && inView(tileOf(on))) {
      morph(on, () => dialog.close());
    } else {
      dialog.close();
    }
  };
  dialog.addEventListener("cancel", (event) => {
    if (event.cancelable) {
      event.preventDefault();
      close();
    }
  });
  dialog.querySelector(".lightbox-close").addEventListener("submit", (event) => {
    event.preventDefault();
    close();
  });
  // the focus lands where the morph does: on the shown slide's tile
  dialog.addEventListener("close", () => tileOf(on).focus());
  // the black: the press and the click both land on it, so a drag that began on the picture or
  // the text never closes
  const black = ".lightbox-strip, .lightbox-strip > figure, figcaption";
  let pressedBlack = false;
  dialog.addEventListener("pointerdown", (event) => {
    pressedBlack = event.target.matches(black);
  });
  dialog.addEventListener("click", (event) => {
    if (pressedBlack && event.target.matches(black)) {
      close();
    }
    pressedBlack = false;
  });
}
