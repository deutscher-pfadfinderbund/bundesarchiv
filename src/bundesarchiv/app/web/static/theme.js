// The light/dark toggle (base.html's .page-footer): two states. Without a saved choice the page
// follows the system; a click then saves the scheme opposite to the system's at that moment. With
// one, a click deletes it and the page follows the system again. The server renders a saved
// choice as <html data-theme> (theme.py), so that attribute is the state, and nothing here runs
// before the first paint.
(() => {
  const COOKIE = "theme";
  const YEAR = 365 * 24 * 60 * 60 * 1000;
  const root = document.documentElement;
  const system = matchMedia("(prefers-color-scheme: dark)");

  const name = (button) => {
    const fixed = Boolean(root.dataset.theme);
    const label = fixed ? "Wie das System" : system.matches ? "Helle Ansicht" : "Dunkle Ansicht";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.setAttribute("aria-pressed", String(fixed));
  };

  const toggle = async (button) => {
    if (root.dataset.theme) {
      delete root.dataset.theme;
      await cookieStore.delete({ name: COOKIE, path: "/" });
    } else {
      const opposite = system.matches ? "light" : "dark";
      root.dataset.theme = opposite;
      await cookieStore.set({
        name: COOKIE,
        value: opposite,
        path: "/",
        expires: Date.now() + YEAR,
        sameSite: "lax",
      });
    }
    name(button);
  };

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.querySelector(".page-footer .theme-toggle");
    if (!button || !("cookieStore" in globalThis)) {
      return;
    }
    name(button);
    button.closest(".page-footer").hidden = false;
    system.addEventListener("change", () => name(button));
    button.addEventListener("click", () => toggle(button));
  });
})();
