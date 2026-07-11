"""Auswahl (selection) query-string algebra for bulk edit (Sammelbearbeitung, spec §2/§3 no-JS).

Selection is URL/form state: checkboxes name="auswahl"; pagination links must PRESERVE the
multi-valued ?auswahl= across pages, and "Alle auf dieser Seite" appends the page's ulids. Pure
query-string helpers in ``browse`` (IO-free, unit-tested) so the no-JS baseline persists selection
with zero server-side session state.
"""

from urllib.parse import parse_qs

from bundesarchiv.app.web import browse


def test_page_query_with_auswahl_preserves_selection() -> None:
    q = browse.page_query_with_auswahl({"q": "fahrt"}, ["01A", "01B"], 2)
    parsed = parse_qs(q)
    assert parsed["seite"] == ["2"]
    assert parsed["q"] == ["fahrt"]
    assert parsed["auswahl"] == ["01A", "01B"]  # multi-valued, both preserved


def test_page_query_with_empty_auswahl_omits_it() -> None:
    q = browse.page_query_with_auswahl({"q": "fahrt"}, [], 2)
    assert "auswahl" not in parse_qs(q)


def test_select_page_query_appends_page_ulids_deduped() -> None:
    # "Alle auf dieser Seite" adds this page's ulids to the existing selection, no duplicates, and
    # resets the page param (the selection changed, page 1 is honest — actually selection is not a
    # filter, but we keep the current page so the archivist stays where they are). Order preserved.
    q = browse.select_page_query({"seite": "3"}, ["01A"], ["01A", "01B", "01C"])
    parsed = parse_qs(q)
    assert parsed["auswahl"] == ["01A", "01B", "01C"]  # 01A not duplicated
    assert parsed["seite"] == ["3"]  # stays on the current page


def test_select_page_query_from_empty_selection() -> None:
    q = browse.select_page_query({}, [], ["01A", "01B"])
    assert parse_qs(q)["auswahl"] == ["01A", "01B"]


def test_auswahl_algebra_ignores_blank_params() -> None:
    # blank filter values never ride into the built URL (same _clean rule as the other helpers)
    q = browse.page_query_with_auswahl({"q": "", "medienart": "Foto"}, ["01A"], 1)
    parsed = parse_qs(q)
    assert "q" not in parsed
    assert parsed["medienart"] == ["Foto"]
