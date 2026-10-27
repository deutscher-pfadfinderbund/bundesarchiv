"""The expandable list's fold rule (DESIGN.md "Expandable list"): the caller marks the rows past
``shown`` as ``.expandable-rest`` and adds the control when any are."""


def shown(rows: int, n: int) -> int:
    """How many of ``rows`` ranked rows show closed: the first ``n``, but a single row never folds."""
    return rows if rows <= n + 1 else n
