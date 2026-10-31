"""``browse.parse_query``, the one strict-but-total parser of the workbench's GET params: garbage in any field falls to that field's default, never a 500."""

import datetime
from typing import get_args

import pytest
from django.http import QueryDict

from bundesarchiv.app.web.browse import PAGE_SIZE, PAGE_SIZES, ParsedQuery, parse_query
from bundesarchiv.index.query import FileKind, SearchFilters, SortOrder


def _parse(**params: str) -> ParsedQuery:
    return parse_query(params)


def test_empty_params_yield_all_defaults() -> None:
    parsed = _parse()
    assert parsed.text is None
    assert parsed.filters == SearchFilters()
    assert parsed.sort == "relevance"
    assert parsed.page == 1


def test_text_is_read_from_q_and_stripped() -> None:
    assert _parse(q="  Fahrt ").text == "Fahrt"


def test_blank_q_is_no_text() -> None:
    assert _parse(q="   ").text is None
    assert _parse(q="").text is None


def test_scalar_filters_map_to_german_params() -> None:
    parsed = _parse(collection="LAGER", media_type="Foto", document_type="Karte", tag="fahrten")
    assert parsed.filters.collection == "LAGER"
    assert parsed.filters.media_type == "Foto"
    assert parsed.filters.document_type == "Karte"
    assert parsed.filters.tag == "fahrten"


def test_decade_is_parsed_as_int() -> None:
    assert _parse(decade="1970").filters.decade == 1970


def test_garbage_decade_falls_to_none() -> None:
    assert _parse(decade="not-a-number").filters.decade is None
    assert _parse(decade="").filters.decade is None


def test_dateless_truthy_and_falsy() -> None:
    assert _parse(dateless="1").filters.dateless is True
    assert _parse(dateless="true").filters.dateless is True
    assert _parse(dateless="0").filters.dateless is False
    assert _parse().filters.dateless is False


def test_the_digital_and_drafts_filters_are_toggles() -> None:
    assert _parse(digital="1").filters.has_files is True
    assert _parse(drafts="1").filters.drafts_only is True
    assert _parse(templates="1").filters.templates_only is True
    assert _parse(digital="0", drafts="vielleicht", templates="").filters == SearchFilters()


def test_date_bounds_parsed_from_date_from_and_date_to() -> None:
    parsed = _parse(date_from="1965-01-01", date_to="1972-12-31")
    assert parsed.filters.date_from == datetime.date(1965, 1, 1)
    assert parsed.filters.date_to == datetime.date(1972, 12, 31)


def test_garbage_date_falls_to_none_not_a_crash() -> None:
    parsed = _parse(date_from="fruehjahr", date_to="2020-99-99")
    assert parsed.filters.date_from is None
    assert parsed.filters.date_to is None


def test_sort_maps_from_german_and_defaults_on_garbage() -> None:
    assert _parse(sort="ref_code").sort == "ref_code"
    assert _parse(sort="date").sort == "date"
    assert _parse(sort="title").sort == "title"
    assert _parse(sort="relevance").sort == "relevance"
    assert _parse(sort="woven-nonsense").sort == "relevance"


def test_every_sort_order_survives_its_url_label() -> None:
    # A preset link (the start page's "Alle ansehen") carries its order as its sort value; an
    # order the parser does not list would fall to relevance on arrival.
    for order in get_args(SortOrder.__value__):
        assert _parse(sort=order).sort == order


def test_sort_direction_from_minus_prefix() -> None:
    # The header cycle encodes descending as a "-" prefix on the sort value; the whole sort state
    # is one URL param (URL-as-state).
    asc = _parse(sort="ref_code")
    assert asc.sort == "ref_code" and asc.descending is False
    desc = _parse(sort="-ref_code")
    assert desc.sort == "ref_code" and desc.descending is True
    rel = _parse(sort="-relevance")
    assert rel.sort == "relevance" and rel.descending is False
    # a bare "-" or a "-garbage" falls to the default, ascending.
    assert _parse(sort="-woven-nonsense").sort == "relevance"
    assert _parse(sort="-woven-nonsense").descending is False


def test_page_parsed_and_clamped_to_at_least_one() -> None:
    assert _parse(page="3").page == 3
    assert _parse(page="0").page == 1
    assert _parse(page="-5").page == 1
    assert _parse(page="garbage").page == 1
    assert _parse().page == 1


def test_each_offered_page_size_is_read() -> None:
    assert [_parse(page_size=str(size)).page_size for size in PAGE_SIZES] == [25, 50, 100, 200]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "0",
        "-25",
        "51",
        "1000",
        "9" * 400,
        "50.0",
        " 25",
        "25 ",
        "+25",
        "025",
        "0x19",
        "25abc",
        "\N{ARABIC-INDIC DIGIT TWO}\N{ARABIC-INDIC DIGIT FIVE}",
        "\N{FULLWIDTH DIGIT TWO}\N{FULLWIDTH DIGIT FIVE}",
        "zwanzig",
    ],
)
def test_any_other_page_size_falls_to_the_default(raw: str) -> None:
    # int() accepts several of these (" 25", "+25", "025", unicode digits): only the offered
    # spellings count
    assert _parse(page_size=raw).page_size == PAGE_SIZE == 50


def test_a_missing_page_size_is_the_default() -> None:
    assert _parse().page_size == PAGE_SIZE


def test_a_repeated_page_size_reads_its_last_value() -> None:
    assert parse_query(QueryDict("page_size=25&page_size=100")).page_size == 100
    assert parse_query(QueryDict("page_size=25&page_size=junk")).page_size == PAGE_SIZE


def test_the_file_kind_parses_and_an_unknown_one_is_ignored() -> None:
    assert _parse(file="pdf").filters.file_kind == FileKind.PDF
    assert _parse(file=" PDF ").filters.file_kind == FileKind.PDF
    assert _parse(file="exe").filters == SearchFilters()
    assert _parse(file="").filters == SearchFilters()


def test_a_query_reads_in_the_lesesaal_unless_the_table_is_asked_for() -> None:
    assert _parse(q="Lager").reading
    assert not _parse(q="Lager", view="table").reading
    # any other value is the rule's default, never an error
    assert _parse(q="Lager", view="Tabelle").reading


def test_without_a_query_the_list_is_the_table() -> None:
    assert not _parse().reading
    assert not _parse(q="  ", view="reading").reading
