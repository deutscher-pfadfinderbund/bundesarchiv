"""Selection query-string algebra for bulk edit: the multi-valued ?selection= survives pagination
and the way back from the bulk pages, with no server-side session state."""

from urllib.parse import parse_qs

from bundesarchiv.app.web import browse


def test_a_page_query_preserves_the_selection() -> None:
    q = browse.SearchState(text="fahrt", page=2).query(["01A", "01B"])
    parsed = parse_qs(q)
    assert parsed["page"] == ["2"]
    assert parsed["q"] == ["fahrt"]
    assert parsed["selection"] == ["01A", "01B"]  # multi-valued, both preserved


def test_a_page_query_without_a_selection_omits_it() -> None:
    q = browse.SearchState(text="fahrt", page=2).query([])
    assert "selection" not in parse_qs(q)


def test_select_page_query_appends_page_ulids_deduped() -> None:
    # the ulids join the existing selection, no duplicates, order preserved
    q = browse.select_page_query(["01A"], ["01A", "01B", "01C"])
    assert parse_qs(q)["selection"] == ["01A", "01B", "01C"]


def test_select_page_query_from_empty_selection() -> None:
    q = browse.select_page_query([], ["01A", "01B"])
    assert parse_qs(q)["selection"] == ["01A", "01B"]
