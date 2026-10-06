"""Pure param-parsing for the archivist workbench (Part 4.5-MVP).

``browse.parse_query`` is the ONE strict-but-total parser: it turns the raw GET params (English
keys ``q, collection, media_type, document_type, tag, decade, dateless, date_from, date_to,
digital, file, drafts, sort, page``) into a ``ParsedQuery`` (text + ``SearchFilters`` + sort +
page). Garbage in
any field falls to that field's default — never a 500 (plan §4.5: strict parse, never crash).

These tests need NO database and NO request cycle: the parser is a pure function over a plain
mapping, so the whole URL-as-state contract is pinned here, fast, in isolation.
"""

import datetime
from typing import get_args

from bundesarchiv.app.web.browse import ParsedQuery, parse_query
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
    assert _parse(digital="0", drafts="vielleicht").filters == SearchFilters()


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
    # relevance has no direction — a stray "-relevanz" collapses to plain relevance, not descending.
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


def test_the_file_kind_parses_and_an_unknown_one_is_ignored() -> None:
    assert _parse(file="pdf").filters.file_kind == FileKind.PDF
    assert _parse(file=" PDF ").filters.file_kind == FileKind.PDF
    assert _parse(file="exe").filters == SearchFilters()
    assert _parse(file="").filters == SearchFilters()
