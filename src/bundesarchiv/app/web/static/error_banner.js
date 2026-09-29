// htmx failures are otherwise silent: a failed request reveals the banner; dismiss or a fresh
// success hides it again.
// On the document and looked up per event: htmx fires on the document when the source element is
// gone, and a history restore replaces the banner node.
(() => {
  "use strict";
  function setBannerHidden(hidden) {
    const banner = document.querySelector(".error-banner");
    if (banner) {
      banner.hidden = hidden;
    }
  }
  document.addEventListener("htmx:response:error", () => {
    setBannerHidden(false);
  });
  document.addEventListener("htmx:error", (event) => {
    // an abort (a newer history restore, leaving the page) is not a failure — htmx 2 parity
    if (event.detail.error?.name !== "AbortError") {
      setBannerHidden(false);
    }
  });
  document.addEventListener("htmx:after:request", (event) => {
    if (event.detail.ctx.response.status < 400) {
      setBannerHidden(true);
    }
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest?.(".error-banner button")) {
      setBannerHidden(true);
    }
  });
})();
