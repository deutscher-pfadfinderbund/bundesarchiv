// A menu entry that opens a tool panel closes its menu. The platform nests a popover opened from
// inside an open one (its invoker sits in the menu), so without this the menu stays open under the
// panel. The panel is shown with no invoker once the menu is hidden, so nothing nests it.
(() => {
  "use strict";
  document.addEventListener("click", (event) => {
    const entry = event.target.closest?.(".menu [popovertarget]");
    const panel = entry?.popoverTargetElement;
    if (!panel) {
      return;
    }
    event.preventDefault();
    entry.closest(".menu").hidePopover();
    panel.togglePopover();
  });
})();
