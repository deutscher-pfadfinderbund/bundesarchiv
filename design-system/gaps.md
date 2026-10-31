# Bundesarchiv design system: open gaps

Keep unresolved design-system gaps here (`design-system` skill, "gaps"). Move closed entries in
full to `design-system/gaps-archive.md` with their disposition, closure date and basis. Resolution
requires demonstrating the original Expected result.

## Open gaps

### The controls have no settled design

- **Source:** owner, 2026-10-28: the controls stay one recorded gap until the clean-room design of
  the control primitives. The Button pilot of 2026-10-27 left the decisions below open.
- **Need:** a component whose CSS styles a control is adopted on a settled design of that control.
- **Actual result:** the native controls (the button and its looks, input, select, textarea,
  checkbox and radio, the file selector, summary) are styled in the elements layer of
  `src/bundesarchiv/app/web/static/components.css`, with no contract. Components that style a
  control cannot be adopted.
- **Expected result:** each control primitive has an approved contract from a clean-room design,
  and the components that style a control can be adopted on it.
- **Evidence:** the ruling above; the elements layer of `components.css`.
- **Next step:** design the control primitives clean-room, then propose their contracts for the
  owner's approval.
- **Decision needed:** when an action outside a menu takes a text look; the button size (DESIGN.md
  and the mock against the shipped CSS); a disabled state for the framed looks.
