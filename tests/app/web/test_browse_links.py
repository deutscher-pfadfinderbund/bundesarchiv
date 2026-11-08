"""``SearchState`` as a query string: what a state prints parses back to that state, and each link
it derives changes one dimension."""

import datetime
from dataclasses import replace
from typing import Any, get_args, get_type_hints
from urllib.parse import parse_qs

import pytest
from django.http import QueryDict

from bundesarchiv.app.web.browse import PAGE_SIZES, SearchState, has_next_page
from bundesarchiv.index.query import FileKind, SearchFilters, SortOrder

#: Text a param carries: its own delimiters, percent, plus, unicode, inner whitespace. Leading and
#: trailing whitespace and the empty string are no state's text: ``parse`` strips them.
_TEXTS = (
    "Fahrt",
    "Müller & Söhne",
    "a=b;c",
    "50 %",
    "+ Fahrt #1",
    "?q=x&page=2",
    "Šibenik",
    "Köln,\N{NO-BREAK SPACE}Bonn",
    "夏 \N{GRINNING FACE}",
)

#: The values each filter field's type takes, the edges of its range included.
_BY_TYPE: dict[object, tuple[Any, ...]] = {
    str: _TEXTS,
    int: (-5, 0, 1960, 10**20),
    datetime.date: (datetime.date.min, datetime.date(1960, 1, 1), datetime.date.max),
    bool: (True,),
    FileKind: tuple(FileKind),
}

#: ``deleted`` is the Papierkorb route's, never a param.
_FILTER_TYPES = {
    name: field_type
    for name, field_type in get_type_hints(SearchFilters).items()
    if name != "deleted"
}


def _values(field_type: object) -> tuple[Any, ...]:
    (set_type,) = (t for t in (*get_args(field_type), field_type) if t in _BY_TYPE)
    return _BY_TYPE[set_type]


def _read(query: str) -> SearchState:
    return SearchState.parse(QueryDict(query))


class TestPrintingParsesBack:
    @pytest.mark.parametrize(
        "filters",
        [
            replace(SearchFilters(), **{name: value})
            for name, field_type in _FILTER_TYPES.items()
            for value in _values(field_type)
        ],
        ids=repr,
    )
    def test_a_filter(self, filters: SearchFilters) -> None:
        state = SearchState(text="Fahrt", filters=filters)
        assert _read(state.query()) == state

    @pytest.mark.parametrize("text", _TEXTS)
    def test_a_text(self, text: str) -> None:
        assert _read(SearchState(text=text).query()) == SearchState(text=text)

    @pytest.mark.parametrize("sort", get_args(SortOrder.__value__))
    @pytest.mark.parametrize("descending", [False, True])
    def test_a_sort(self, sort: SortOrder, descending: bool) -> None:
        state = SearchState(sort=sort, descending=descending and sort != "relevance")
        assert _read(state.query()) == state

    @pytest.mark.parametrize("page_size", PAGE_SIZES)
    @pytest.mark.parametrize("table", [False, True])
    @pytest.mark.parametrize("text", [None, "Fahrt"])
    def test_a_page_in_either_view(self, page_size: int, table: bool, text: str | None) -> None:
        state = SearchState(text=text, page=7, page_size=page_size, table=table)
        assert _read(state.query()) == state

    def test_every_field_set_at_once(self) -> None:
        state = SearchState(
            text="+ Fahrt #1",
            filters=replace(
                SearchFilters(),
                **{name: _values(field_type)[-1] for name, field_type in _FILTER_TYPES.items()},
            ),
            sort="date",
            descending=True,
            page=3,
            page_size=200,
            table=True,
        )
        assert _read(state.query()) == state

    def test_the_selection_rides_after_the_state(self) -> None:
        query = SearchState(text="Fahrt", page=2).query(["", "01A", "01B"])
        assert parse_qs(query, keep_blank_values=True) == {
            "q": ["Fahrt"],
            "page": ["2"],
            "selection": ["", "01A", "01B"],
        }
        assert _read(query) == SearchState(text="Fahrt", page=2)


def test_a_default_prints_nothing() -> None:
    assert SearchState().query() == ""


def test_a_param_it_does_not_know_is_dropped() -> None:
    assert _read("q=Lager&article=01A&focus=ref_code&media_type=").query() == "q=Lager"


def test_with_sets_a_facet_and_returns_to_page_one() -> None:
    state = SearchState(text="Lager", filters=SearchFilters(media_type="Karte"), page=3)
    assert state.with_("media_type", "Foto") == SearchState(
        text="Lager", filters=SearchFilters(media_type="Foto")
    )


def test_a_new_medienart_drops_its_dokumenttyp() -> None:
    state = SearchState(filters=SearchFilters(media_type="Schrifttum", document_type="Lagerheft"))
    assert state.with_("media_type", "Foto").filters == SearchFilters(media_type="Foto")
    assert state.without("media_type").filters == SearchFilters()


def test_without_removes_one_dimension_and_returns_to_page_one() -> None:
    state = SearchState(
        text="Lager", filters=SearchFilters(media_type="Foto", collection="LAGER"), page=4
    )
    assert state.without("media_type") == SearchState(
        text="Lager", filters=SearchFilters(collection="LAGER")
    )


def test_without_filters_keeps_the_text_sort_and_view() -> None:
    state = _read(
        "q=Lager&collection=FOTOS&media_type=Foto&decade=1960&dateless=1&sort=-ref_code"
        "&view=table&page_size=100&page=3"
    )
    assert state.without_filters().query() == "q=Lager&sort=-ref_code&view=table&page_size=100"


def test_the_view_switch_keeps_every_other_param_the_page_included() -> None:
    reading = _read("q=Lager&tag=sommer&sort=-date&page=3")
    table = replace(reading, table=True)
    assert table.params() == {**reading.params(), "view": "table"}
    assert (reading.reading, table.reading) == (True, False)


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
