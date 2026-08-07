"""URL-as-state link helpers (Part 4.5-MVP, plan §4.5: URL-as-state, forms/links stable).

The workbench's whole state lives in the query string. These pure helpers build the links the
facet sidebar / pagination / sort control emit, and pin the round-trip: a param set that
``parse_query`` reads back is exactly what a link that ADDS that facet produces, and removing it
(sidebar ✕) drops just that one dimension. No DB, no request — pure query-string algebra.
"""

from bundesarchiv.app.web.browse import (
    has_next_page,
    page_query,
    pane_query_prefix,
    parse_query,
    with_param,
    without_param,
)


def _params(query: str) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(query))


def test_with_param_adds_a_facet_and_resets_page() -> None:
    q = with_param({"q": "Lager", "seite": "3"}, "medienart", "Foto")
    params = _params(q)
    assert params["medienart"] == "Foto"
    assert params["q"] == "Lager"
    # Adding a facet changes the result set, so pagination resets to page 1 (drop stale ``seite``).
    assert "seite" not in params


def test_with_param_replaces_an_existing_value_for_the_same_key() -> None:
    q = with_param({"medienart": "Karte"}, "medienart", "Foto")
    assert _params(q)["medienart"] == "Foto"


def test_without_param_removes_one_dimension_only() -> None:
    q = without_param({"q": "Lager", "medienart": "Foto", "bestand": "LAGER"}, "medienart")
    params = _params(q)
    assert "medienart" not in params
    assert params["q"] == "Lager"
    assert params["bestand"] == "LAGER"


def test_without_param_also_resets_page() -> None:
    q = without_param({"medienart": "Foto", "seite": "4"}, "medienart")
    assert "seite" not in _params(q)


def test_add_then_parse_round_trips() -> None:
    q = with_param({"q": "Fahrt"}, "schlagwort", "fahrten")
    parsed = parse_query(_params(q))
    assert parsed.text == "Fahrt"
    assert parsed.filters.tag == "fahrten"


def test_page_query_sets_seite_preserving_the_rest() -> None:
    q = page_query({"q": "Lager", "medienart": "Foto"}, 2)
    params = _params(q)
    assert params["seite"] == "2"
    assert params["q"] == "Lager"
    assert params["medienart"] == "Foto"


# --- pane-link prefix (pane_query_prefix) -----------------------------------------
# The row-invariant half of every Vorschau link: search state (blanks dropped, same _clean rule
# as every sibling helper) + the multi-valued auswahl selection. Rows append artikel=<ulid>.


def test_pane_query_prefix_carries_state_and_selection() -> None:
    q = pane_query_prefix({"q": "Lager", "medienart": "Foto"}, ["01A", "01B"])
    assert q == "q=Lager&medienart=Foto&auswahl=01A&auswahl=01B"


def test_pane_query_prefix_drops_blank_params() -> None:
    assert pane_query_prefix({"q": "", "medienart": "Foto"}, []) == "medienart=Foto"


def test_pane_query_prefix_empty_when_stateless() -> None:
    # No search, no selection: the row link is just ?artikel=<ulid> — no dangling separator.
    assert pane_query_prefix({}, []) == ""


# --- pagination boundary (has_next_page) ------------------------------------------
# The bug this pins: computing "rows consumed" from page * len(hits) understates consumption on a
# partial last page (total=60, page 2 with 10 hits -> 2*10=20 < 60 -> a spurious "Weiter" link to
# an empty page). Consumed rows are (page-1)*page_size + hits_on_page.


def test_has_next_true_on_full_non_final_page() -> None:
    assert has_next_page(page=1, page_size=50, hits_on_page=50, total=60) is True


def test_has_next_false_on_partial_last_page() -> None:
    # total=60, page 2 carries the remaining 10 — there is no page 3.
    assert has_next_page(page=2, page_size=50, hits_on_page=10, total=60) is False


def test_has_next_false_on_exactly_full_last_page() -> None:
    # total == page * page_size: the last page is full, but it IS the last.
    assert has_next_page(page=2, page_size=50, hits_on_page=50, total=100) is False


def test_has_next_false_on_empty_results() -> None:
    assert has_next_page(page=1, page_size=50, hits_on_page=0, total=0) is False


def test_has_next_false_on_overshot_empty_page() -> None:
    # A hand-edited seite beyond the end (no hits) must not offer a further page.
    assert has_next_page(page=3, page_size=50, hits_on_page=0, total=60) is False
