"""Pure param-parsing for the archivist workbench (Part 4.5-MVP).

``browse.parse_query`` is the ONE strict-but-total parser: it turns the raw GET params (German
keys ``q, bestand, medienart, dokumenttyp, schlagwort, jahrzehnt, ohne_datum, von, bis,
sortierung, seite``) into a ``ParsedQuery`` (text + ``SearchFilters`` + sort + page). Garbage in
any field falls to that field's default — never a 500 (plan §4.5: strict parse, never crash).

These tests need NO database and NO request cycle: the parser is a pure function over a plain
mapping, so the whole URL-as-state contract is pinned here, fast, in isolation.
"""

import datetime

from bundesarchiv.app.web.browse import ParsedQuery, parse_query
from bundesarchiv.index.query import SearchFilters


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
    parsed = _parse(bestand="LAGER", medienart="Foto", dokumenttyp="Karte", schlagwort="fahrten")
    assert parsed.filters.collection == "LAGER"
    assert parsed.filters.media_type == "Foto"
    assert parsed.filters.document_type == "Karte"
    assert parsed.filters.tag == "fahrten"


def test_decade_is_parsed_as_int() -> None:
    assert _parse(jahrzehnt="1970").filters.decade == 1970


def test_garbage_decade_falls_to_none() -> None:
    assert _parse(jahrzehnt="not-a-number").filters.decade is None
    assert _parse(jahrzehnt="").filters.decade is None


def test_ohne_datum_truthy_and_falsy() -> None:
    assert _parse(ohne_datum="1").filters.dateless is True
    assert _parse(ohne_datum="true").filters.dateless is True
    assert _parse(ohne_datum="0").filters.dateless is False
    assert _parse().filters.dateless is False


def test_date_bounds_parsed_from_von_bis() -> None:
    parsed = _parse(von="1965-01-01", bis="1972-12-31")
    assert parsed.filters.date_from == datetime.date(1965, 1, 1)
    assert parsed.filters.date_to == datetime.date(1972, 12, 31)


def test_garbage_date_falls_to_none_not_a_crash() -> None:
    parsed = _parse(von="fruehjahr", bis="2020-99-99")
    assert parsed.filters.date_from is None
    assert parsed.filters.date_to is None


def test_sort_maps_from_german_and_defaults_on_garbage() -> None:
    assert _parse(sortierung="signatur").sort == "ref_code"
    assert _parse(sortierung="datierung").sort == "date"
    assert _parse(sortierung="titel").sort == "title"
    assert _parse(sortierung="relevanz").sort == "relevance"
    assert _parse(sortierung="woven-nonsense").sort == "relevance"


def test_sort_direction_from_minus_prefix() -> None:
    # The header cycle encodes descending as a "-" prefix on the German label; the whole sort state
    # is one URL param (URL-as-state).
    asc = _parse(sortierung="signatur")
    assert asc.sort == "ref_code" and asc.descending is False
    desc = _parse(sortierung="-signatur")
    assert desc.sort == "ref_code" and desc.descending is True
    # relevance has no direction — a stray "-relevanz" collapses to plain relevance, not descending.
    rel = _parse(sortierung="-relevanz")
    assert rel.sort == "relevance" and rel.descending is False
    # a bare "-" or a "-garbage" falls to the default, ascending.
    assert _parse(sortierung="-woven-nonsense").sort == "relevance"
    assert _parse(sortierung="-woven-nonsense").descending is False


def test_page_parsed_and_clamped_to_at_least_one() -> None:
    assert _parse(seite="3").page == 3
    assert _parse(seite="0").page == 1
    assert _parse(seite="-5").page == 1
    assert _parse(seite="garbage").page == 1
    assert _parse().page == 1
