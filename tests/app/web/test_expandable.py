import pytest

from bundesarchiv.app.web import expandable


@pytest.mark.parametrize(("rows", "shown"), [(5, 5), (7, 7), (8, 8), (9, 7)])
def test_the_first_n_show_but_a_single_row_never_folds(rows: int, shown: int) -> None:
    assert expandable.shown(rows, 7) == shown
