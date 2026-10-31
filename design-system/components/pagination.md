---
sourcesHash: f9982ea48f870bf1a3f165e65e90dfa0bd05fbdb95ca17947e8328d9338ba2d1
id: pagination
description: Step through a long list page by page, with the range on screen, the total and an optional page-size chooser.
status: hidden
sources:
  - src/bundesarchiv/app/web/templates/components/pagination.html
  - src/bundesarchiv/app/web/static/components.css
---

# Pagination

## When to use

- A list with at least one hit is cut into pages, or could be, and the reader needs its total.

## When not to use

- The list has no hits: render no pager; the list's empty state explains the absence.
- The reader must jump to an arbitrary page: there are no page numbers.
- Rows load in place without a URL change (load more, infinite scroll).

## Public API

```django
{% include "components/pagination.html" with pager=pager only %}
```

`pager` is the one input; the page computes every field, the component only places them:
- `prev_query`, `next_query` (str or None): each step's full target query, without `?`, with
  every state a step must keep (filters, sort, a selection); None: that step cannot move.
- `first` (int), `shown` (str): first row's number, range on screen ("1–25"); empty: total only.
- `stepped` (bool): more than one page; `total` (int), `total_label` (str): hit count, its text.
- `sizes` (sequence of `label`, `query`; `query` None for the size on screen): sizes on offer,
  in order, when readers need another density; empty or absent: no chooser.

## Behaviour and states

- **None** (`pager` falsy): nothing renders.
- **One page**: the range and the total ("1–6 von 6"), no steps.
- **Stepped**: back step, range "von" total, forward step; one that cannot move stays, inactive.
- **With chooser**: "Pro Seite" and the sizes lead the row, in either state.
- **Narrow space**: wraps only between chooser and steps; in narrow space the steps show only their arrows.
- Every move is a plain link: the URL holds the state; back and a new tab follow it.

## Accessibility

- Provided: a landmark "Seiten" when stepped, named steps, inactive steps unfocusable.
- Required of consumers: keep the list's heading and empty state outside the component.
