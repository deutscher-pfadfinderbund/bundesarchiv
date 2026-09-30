// Tool-panel behaviour the platform lacks.
//
// A menu entry that opens a tool panel closes its menu. The platform nests a popover opened from
// inside an open one (its invoker sits in the menu), so without this the menu stays open under the
// panel. The panel is shown with no invoker once the menu is hidden, so nothing nests it. It opens
// from the menu's own button, so closing it hands the focus back there, not to <body>: the entry is
// hidden, and a click in Safari never focused the button. (showPopover's `source` would do both,
// but is not Baseline widely available: law F.)
//
// A panel marked data-reset-on-close puts its controls back as the page rendered them whenever it
// closes, so a change the archivist abandoned never rides along with a later submit.
(() => {
  "use strict";
  document.addEventListener("click", (event) => {
    const entry = event.target.closest?.(".menu [popovertarget]");
    const panel = entry?.popoverTargetElement;
    if (!panel) {
      return;
    }
    event.preventDefault();
    const menu = entry.closest(".menu");
    const button = document.querySelector(`[popovertarget="${menu.id}"]`);
    menu.hidePopover();
    button?.focus();
    // a light dismiss restores no focus: one that lands nowhere goes to the button too
    panel.addEventListener("toggle", function back(toggle) {
      if (toggle.newState !== "closed") {
        return;
      }
      panel.removeEventListener("toggle", back);
      const focused = document.activeElement;
      if (!focused || focused === document.body || panel.contains(focused)) {
        button?.focus();
      }
    });
    panel.togglePopover();
  });

  // beforetoggle does not bubble; capture sees it on every panel, before the panel hides.
  document.addEventListener(
    "beforetoggle",
    (event) => {
      if (event.newState === "closed" && event.target.matches?.("[data-reset-on-close]")) {
        event.target.querySelectorAll("input, select, textarea").forEach(restore);
      }
    },
    true,
  );

  function restore(control) {
    let changed;
    if (control instanceof HTMLSelectElement) {
      const rendered = [...control.options].find((o) => o.defaultSelected) ?? control.options[0];
      changed = rendered !== undefined && !rendered.selected;
      if (changed) {
        rendered.selected = true;
      }
    } else if (control.type === "checkbox" || control.type === "radio") {
      changed = control.checked !== control.defaultChecked;
      control.checked = control.defaultChecked;
    } else {
      changed = control.value !== control.defaultValue;
      control.value = control.defaultValue;
    }
    if (changed) {
      // what listens to the control (the dependent Dokumenttyp list) follows it back
      control.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
})();
