"""URL-as-state link helpers (Part 4.5-MVP, plan §4.5: URL-as-state, forms/links stable).

The workbench's whole state lives in the query string. These pure helpers build the links the
facet sidebar / chips / pagination / sort control emit, and pin the round-trip: a param set that
``parse_query`` reads back is exactly what a link that ADDS that facet produces, and removing it
(chip ✕) drops just that one dimension. No DB, no request — pure query-string algebra.
"""

from bundesarchiv.app.web.browse import (
    active_chips,
    page_query,
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


def test_active_chips_lists_each_set_filter_with_a_remove_query() -> None:
    params = {"q": "Lager", "medienart": "Foto", "bestand": "LAGER", "seite": "2"}
    chips = active_chips(params)
    keys = {c.param for c in chips}
    # q is text, not a chip; every set filter dimension IS a chip; seite/sort are not chips.
    assert "medienart" in keys
    assert "bestand" in keys
    assert "q" not in keys
    assert "seite" not in keys
    foto = next(c for c in chips if c.param == "medienart")
    assert foto.value == "Foto"
    assert "medienart" not in _params(foto.remove_query)  # ✕ drops exactly this chip


def test_active_chips_empty_when_no_filters() -> None:
    assert active_chips({"q": "Lager"}) == ()
