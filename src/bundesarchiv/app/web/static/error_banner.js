// htmx failures are otherwise silent: a failed request reveals the banner; dismiss or a fresh
// success hides it again.
// On the document and looked up per event: htmx fires on the document when the source element is
// gone, and a history restore replaces the banner node.
(function () {
  "use strict";
  function setBannerHidden(hidden) {
    var banner = document.querySelector(".error-banner");
    if (banner) banner.hidden = hidden;
  }
  document.addEventListener("htmx:response:error", function () {
    setBannerHidden(false);
  });
  document.addEventListener("htmx:error", function (event) {
    // an abort (a newer history restore, leaving the page) is not a failure — htmx 2 parity
    if (!event.detail.error || event.detail.error.name !== "AbortError") setBannerHidden(false);
  });
  document.addEventListener("htmx:after:request", function (event) {
    if (event.detail.ctx.response.status < 400) setBannerHidden(true);
  });
  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest(".error-banner button")) setBannerHidden(true);
  });
})();
