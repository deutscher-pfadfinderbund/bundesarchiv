// The way back keeps the list's filters.
//
// The list (body.workbench) remembers its address, path and query, per tab in sessionStorage: on
// load, and after an htmx swap that pushes a new URL. On every other screen the links marked
// data-list-link (the "Archiv" crumb, back links) then lead there. Without JS or storage
// (private mode can throw) they stay as rendered.
(() => {
  "use strict";
  const KEY = "list-address";

  // A write whose search index lagged lands here with this flag (landing.LAG_FLAG). The page has
  // shown the notice; the address drops the flag so a reload, Back or bookmark does not repeat it.
  function clearLagFlag() {
    const query = new URLSearchParams(location.search);
    if (query.get("index") !== "lagging") {
      return;
    }
    query.delete("index");
    const rest = query.toString();
    history.replaceState(
      history.state,
      "",
      location.pathname + (rest ? `?${rest}` : "") + location.hash,
    );
  }

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
    // an address from before the list moved (it lived at "/") leads elsewhere: only the list's path
    const path = new URL(address, location.origin).pathname;
    document.querySelectorAll("a[data-list-link]").forEach((link) => {
      if (link.pathname === path) {
        link.setAttribute("href", address);
      }
    });
  }

  clearLagFlag();
  remember();
  if (!document.body.classList.contains("workbench")) {
    restore();
  }
  document.addEventListener("htmx:pushedIntoHistory", () => {
    clearLagFlag();
    remember();
  });
  document.addEventListener("htmx:historyRestore", remember);
})();
