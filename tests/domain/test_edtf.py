"""Tests for EdtfDate — EDTF Level 0/1 value object (table-driven)."""

import datetime

import pytest

from bundesarchiv.domain.edtf import (
    Century,
    Day,
    Decade,
    EdtfDate,
    EdtfPart,
    Month,
    OpenEnd,
    Point,
    Season,
    UnknownEnd,
    Year,
    YearSeason,
)

# (value, earliest, latest, decades at cap_year=2030)

VALID_ROWS: list[tuple[str, datetime.date, datetime.date | None, tuple[int, ...]]] = [
    # --- Level 0: date-only ---
    (
        "1968",
        datetime.date(1968, 1, 1),
        datetime.date(1968, 12, 31),
        (1960,),
    ),
    (
        "1968-06",
        datetime.date(1968, 6, 1),
        datetime.date(1968, 6, 30),
        (1960,),
    ),
    (
        "1968-06-15",
        datetime.date(1968, 6, 15),
        datetime.date(1968, 6, 15),
        (1960,),
    ),
    # --- Level 1: qualifiers (bounds unchanged) ---
    (
        "1968?",
        datetime.date(1968, 1, 1),
        datetime.date(1968, 12, 31),
        (1960,),
    ),
    (
        "1968-06~",
        datetime.date(1968, 6, 1),
        datetime.date(1968, 6, 30),
        (1960,),
    ),
    # --- Level 1: unspecified digits ---
    (
        "197X",
        datetime.date(1970, 1, 1),
        datetime.date(1979, 12, 31),
        (1970,),
    ),
    (
        "19XX",
        datetime.date(1900, 1, 1),
        datetime.date(1999, 12, 31),
        (1900, 1910, 1920, 1930, 1940, 1950, 1960, 1970, 1980, 1990),
    ),
    # --- Level 1: seasons ---
    (
        "2001-22",  # summer
        datetime.date(2001, 6, 1),
        datetime.date(2001, 8, 31),
        (2000,),
    ),
    (
        "2001-24",  # winter, crosses the year boundary
        datetime.date(2001, 12, 1),
        datetime.date(2002, 2, 28),
        (2000,),
    ),
    # --- Level 1: intervals ---
    (
        "1968/1973~",
        datetime.date(1968, 1, 1),
        datetime.date(1973, 12, 31),
        (1960, 1970),
    ),
    (
        "1968-06/1973-09",
        datetime.date(1968, 6, 1),
        datetime.date(1973, 9, 30),
        (1960, 1970),
    ),
]


@pytest.mark.parametrize("value,earliest,latest,expected_decades", VALID_ROWS)
def test_valid_edtf_bounds_and_decades(
    value: str,
    earliest: datetime.date,
    latest: datetime.date | None,
    expected_decades: tuple[int, ...],
) -> None:
    ed = EdtfDate(value)
    lo, hi = ed.bounds()
    assert lo == earliest, f"{value!r}: earliest mismatch"
    assert hi == latest, f"{value!r}: latest mismatch"
    assert ed.decades(cap_year=2030) == expected_decades, f"{value!r}: decades mismatch"


def test_open_upper_end_bounds_and_capped_decades() -> None:
    ed = EdtfDate("1964/..")
    lo, hi = ed.bounds()
    assert lo == datetime.date(1964, 1, 1)
    assert hi is None
    # cap_year=1980: covers 1960s and 1970s
    assert ed.decades(cap_year=1980) == (1960, 1970)


@pytest.mark.parametrize("value", ["../1965", "/1965"])
def test_an_open_or_unknown_lower_end_is_unbounded_and_its_decades_start_at_the_point(
    value: str,
) -> None:
    ed = EdtfDate(value)
    assert ed.bounds() == (None, datetime.date(1965, 12, 31))
    assert ed.decades(cap_year=2030) == (1960,)


def test_an_unknown_upper_end_is_unbounded_and_capped_like_an_open_one() -> None:
    ed = EdtfDate("1960/")
    assert ed.bounds() == (datetime.date(1960, 1, 1), None)
    assert ed.decades(cap_year=1980) == (1960, 1970)


# ---------------------------------------------------------------------------
# Invalid-input table
# ---------------------------------------------------------------------------

INVALID_VALUES = [
    "garbage",
    "19",  # only 2 year digits
    "1970-13",  # month 13
    "",  # empty
    "1970-00",  # month 00
    "1970-06-00",  # day 00
    "1970-06-32",  # day 32
    "1970-25",  # bad season code
    "197Y",  # invalid unspecified digit position
    "1970-06-15-extra",  # trailing garbage
    "1975/1970",  # inverted interval (start after end)
    "1965-02-30",  # a day the calendar lacks
    "1965-6",  # one month digit
    "1985-XX-12",  # an unspecified month before a known day
    "1985-0X",  # an unspecified single digit of a month
    # at least one end is a point
    "/",
    "/..",
    "../",
    "../..",
    # the delimiter, whitespace, non-ASCII digits
    "1965/1970/1975",
    "1965//1970",
    " 1965",
    "1965 ",
    "1965\n",
    "1965 / 1970",
    "\N{ARABIC-INDIC DIGIT ONE}965",
]


@pytest.mark.parametrize("bad", INVALID_VALUES)
def test_invalid_edtf_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        EdtfDate(bad)


#: EDTF Level 0/1 (https://www.loc.gov/standards/datetime/) the grammar leaves out.
NOT_SUPPORTED = {
    "a time of day (Level 0)": "1985-04-12T23:20:30",
    "a time zone (Level 0)": "1985-04-12T23:20:30Z",
    "a year past 9999 (Level 1)": "Y170000002",
    "a negative year (Level 1)": "-1985",
    "a qualified season (Level 1, the spec is unclear)": "2001-21?",
}


@pytest.mark.parametrize("value", NOT_SUPPORTED.values(), ids=NOT_SUPPORTED.keys())
def test_edtf_left_out_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        EdtfDate(value)


PARTS: dict[str, tuple[str, tuple[EdtfPart, ...]]] = {
    "a year": ("1968", (Point(Year(1968)),)),
    "a month": ("1968-06", (Point(Month(1968, 6)),)),
    "a day": ("1968-06-15", (Point(Day(datetime.date(1968, 6, 15))),)),
    "a season": ("2001-24", (Point(YearSeason(2001, Season.WINTER)),)),
    "a decade": ("197X", (Point(Decade(1970)),)),
    "a century": ("19XX", (Point(Century(1900)),)),
    "an unspecified month": ("2004-XX", (Point(Year(2004)),)),
    "an unspecified month and day": ("1985-XX-XX", (Point(Year(1985)),)),
    "an unspecified day": ("1985-04-XX", (Point(Month(1985, 4)),)),
    "a qualified unspecified day": ("1985-04-XX?", (Point(Month(1985, 4), uncertain=True),)),
    "uncertain": ("1968?", (Point(Year(1968), uncertain=True),)),
    "approximate": ("1968-06~", (Point(Month(1968, 6), approximate=True),)),
    "uncertain and approximate": (
        "1958-07-01%",
        (Point(Day(datetime.date(1958, 7, 1)), uncertain=True, approximate=True),),
    ),
    "a qualified decade": ("197X~", (Point(Decade(1970), approximate=True),)),
    "an interval, each end qualified on its own": (
        "1968/1973~",
        (Point(Year(1968)), Point(Year(1973), approximate=True)),
    ),
    "an open upper end": ("1964/..", (Point(Year(1964)), OpenEnd())),
    "an open lower end": ("../1973", (OpenEnd(), Point(Year(1973)))),
    "an unknown lower end": ("/1973", (UnknownEnd(), Point(Year(1973)))),
    "an unknown upper end": ("1960/", (Point(Year(1960)), UnknownEnd())),
}


@pytest.mark.parametrize(("value", "parts"), PARTS.values(), ids=PARTS.keys())
def test_parts_decode_the_value(value: str, parts: tuple[EdtfPart, ...]) -> None:
    assert EdtfDate(value).parts() == parts
