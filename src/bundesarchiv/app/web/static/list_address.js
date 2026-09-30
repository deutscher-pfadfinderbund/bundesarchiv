// The way back keeps the list's filters.
//
// The list (body.workbench) remembers its address, path and query, per tab in sessionStorage: on
// load, and after an htmx swap that pushes a new URL. On every other screen the links marked
// data-list-link ("Archiv" crumb, wordmark, back links) then lead there. Without JS or storage
// (private mode can throw) they stay as rendered.
(() => {
  "use strict";
  const KEY = "list-address";

  function remember() {
    if (!document.body.classList.contains("workbench")) {
      return;
    }
    try {
      sessionStorage.setItem(KEY, location.pathname + location.search);
    } catch {}
  }

  function restore() {
    let address = null;
    try {
      address = sessionStorage.getItem(KEY);
    } catch {}
    // only a same-origin path: storage is ours, but a link must never leave the site
    if (!address?.startsWith("/") || address.startsWith("//")) {
      return;
    }
    document.querySelectorAll("a[data-list-link]").forEach((link) => {
      link.setAttribute("href", address);
    });
  }

  remember();
  if (!document.body.classList.contains("workbench")) {
    restore();
  }
  document.addEventListener("htmx:pushedIntoHistory", remember);
  document.addEventListener("htmx:historyRestore", remember);
})();
