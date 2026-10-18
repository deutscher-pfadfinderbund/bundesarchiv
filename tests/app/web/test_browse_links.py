"""URL-as-state link helpers: a param set ``parse_query`` reads back is what a link adding that facet produces, and removing it (the chip ✕) drops just that one dimension."""

from bundesarchiv.app.web.browse import (
    clear_filters_query,
    has_next_page,
    parse_query,
    view_query,
    with_param,
    without_param,
)


def _params(query: str) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(query))


def test_with_param_adds_a_facet_and_resets_page() -> None:
    q = with_param({"q": "Lager", "page": "3"}, "media_type", "Foto")
    params = _params(q)
    assert params["media_type"] == "Foto"
    assert params["q"] == "Lager"
    # Adding a facet changes the result set, so pagination resets to page 1 (drop the stale ``page``).
    assert "page" not in params


def test_with_param_replaces_an_existing_value_for_the_same_key() -> None:
    q = with_param({"media_type": "Karte"}, "media_type", "Foto")
    assert _params(q)["media_type"] == "Foto"


def test_without_param_removes_one_dimension_only() -> None:
    q = without_param({"q": "Lager", "media_type": "Foto", "collection": "LAGER"}, "media_type")
    params = _params(q)
    assert "media_type" not in params
    assert params["q"] == "Lager"
    assert params["collection"] == "LAGER"


def test_without_param_also_resets_page() -> None:
    q = without_param({"media_type": "Foto", "page": "4"}, "media_type")
    assert "page" not in _params(q)


def test_add_then_parse_round_trips() -> None:
    q = with_param({"q": "Fahrt"}, "tag", "fahrten")
    parsed = parse_query(_params(q))
    assert parsed.text == "Fahrt"
    assert parsed.filters.tag == "fahrten"


# --- clear-all (clear_filters_query) -----------------------------------------------


def test_clear_filters_removes_every_filter_keeps_q_and_sort() -> None:
    q = clear_filters_query(
        {
            "q": "Lager",
            "collection": "FOTOS",
            "media_type": "Foto",
            "document_type": "Bericht",
            "tag": "lager",
            "decade": "1960",
            "dateless": "1",
            "date_from": "1960-01-01",
            "date_to": "1969-12-31",
            "sort": "-ref_code",
            "page": "3",
        }
    )
    assert _params(q) == {"q": "Lager", "sort": "-ref_code"}


def test_clear_filters_empty_when_only_filters_active() -> None:
    # Filters were the whole state: the link points at the bare workbench ("?").
    assert clear_filters_query({"media_type": "Foto", "tag": "lager"}) == ""


def test_clear_filters_drops_blank_values_like_every_link_helper() -> None:
    assert clear_filters_query({"q": "Fahrt", "media_type": ""}) == "q=Fahrt"


# --- pagination boundary (has_next_page) ------------------------------------------


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
    assert has_next_page(page=3, page_size=50, hits_on_page=0, total=60) is False


def test_a_creator_or_place_round_trips_through_its_link() -> None:
    # A suggestion pick or facet click carries the stored value verbatim; stored values are
    # stripped (the form and the legacy import strip), so only padding is lost.
    values = ("Müller & Söhne", "a=b;c", "50 %", "Köln, Bonn", "+ Fahrt #1", "Šibenik", " Köln ")
    for value in values:
        creator = parse_query(_params(with_param({}, "creator", value))).filters.creator
        place = parse_query(_params(with_param({}, "place", value))).filters.place
        assert creator == place == value.strip(), value
    assert parse_query(_params(with_param({}, "creator", ""))).filters.creator is None


def test_the_view_switch_keeps_every_other_param_the_page_included() -> None:
    params = {"q": "Lager", "tag": "sommer", "sort": "-date", "page": "3", "view": "table"}
    table = _params(view_query(params, table=True))
    reading = _params(view_query(params, table=False))
    assert table == params
    assert reading == {k: v for k, v in params.items() if k != "view"}
    assert not parse_query(table).reading
    assert parse_query(reading).reading
