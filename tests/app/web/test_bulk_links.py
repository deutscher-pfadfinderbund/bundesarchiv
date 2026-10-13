"""Selection query-string algebra for bulk edit: the multi-valued ?selection= survives pagination
and the way back from the bulk pages, with no server-side session state."""

from urllib.parse import parse_qs

from bundesarchiv.app.web import browse


def test_page_query_with_selection_preserves_selection() -> None:
    q = browse.page_query_with_selection({"q": "fahrt"}, ["01A", "01B"], 2)
    parsed = parse_qs(q)
    assert parsed["page"] == ["2"]
    assert parsed["q"] == ["fahrt"]
    assert parsed["selection"] == ["01A", "01B"]  # multi-valued, both preserved


def test_page_query_with_empty_selection_omits_it() -> None:
    q = browse.page_query_with_selection({"q": "fahrt"}, [], 2)
    assert "selection" not in parse_qs(q)


def test_select_page_query_appends_page_ulids_deduped() -> None:
    # the ulids join the existing selection, no duplicates, order preserved; the page stays
    q = browse.select_page_query({"page": "3"}, ["01A"], ["01A", "01B", "01C"])
    parsed = parse_qs(q)
    assert parsed["selection"] == ["01A", "01B", "01C"]  # 01A not duplicated
    assert parsed["page"] == ["3"]  # stays on the current page


def test_select_page_query_from_empty_selection() -> None:
    q = browse.select_page_query({}, [], ["01A", "01B"])
    assert parse_qs(q)["selection"] == ["01A", "01B"]


def test_selection_algebra_ignores_blank_params() -> None:
    # blank filter values never ride into the built URL (same _clean rule as the other helpers)
    q = browse.page_query_with_selection({"q": "", "media_type": "Foto"}, ["01A"], 1)
    parsed = parse_qs(q)
    assert "q" not in parsed
    assert parsed["media_type"] == ["Foto"]
