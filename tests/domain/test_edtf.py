"""Tests for EdtfDate — EDTF Level 0/1 value object (table-driven)."""

import datetime

import pytest

from bundesarchiv.domain.edtf import EdtfDate

# ---------------------------------------------------------------------------
# Valid-input table: (edtf_string, earliest, latest_or_None, decades_tuple)
# decades are computed with cap_year=2030 for all fixed rows; open-end rows
# use cap_year values stated inline.
# ---------------------------------------------------------------------------

VALID_ROWS: list[tuple[str, datetime.date, datetime.date | None, tuple[int, ...]]] = [
    # --- Level 0: date-only ---
    (
        "1968",
        datetime.date(1968, 1, 1),
        datetime.date(1968, 12, 31),
        (1960,),
    ),
    (
        "2001",
        datetime.date(2001, 1, 1),
        datetime.date(2001, 12, 31),
        (2000,),
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
        "1968~",
        datetime.date(1968, 1, 1),
        datetime.date(1968, 12, 31),
        (1960,),
    ),
    (
        "1968%",
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
        "2001-21",
        datetime.date(2001, 3, 1),
        datetime.date(2001, 5, 31),
        (2000,),
    ),
    (
        "2001-22",  # summer
        datetime.date(2001, 6, 1),
        datetime.date(2001, 8, 31),
        (2000,),
    ),
    (
        "2001-23",
        datetime.date(2001, 9, 1),
        datetime.date(2001, 11, 30),
        (2000,),
    ),
    (
        "2001-24",
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
    """'1964/..' — open upper end: bounds()[1] is None; decades capped at cap_year."""
    ed = EdtfDate("1964/..")
    lo, hi = ed.bounds()
    assert lo == datetime.date(1964, 1, 1)
    assert hi is None
    # cap_year=1980: covers 1960s and 1970s
    assert ed.decades(cap_year=1980) == (1960, 1970)


def test_open_lower_end_bounds_and_capped_decades() -> None:
    """'../1973' — open lower end: bounds()[0] is still defined from the upper side."""
    ed = EdtfDate("../1973")
    _, hi = ed.bounds()
    assert hi == datetime.date(1973, 12, 31)
    # Open lower end anchors bounds()[0] at B's start (1973-01-01), so the span
    # covers exactly B's decade. No cap involved — the upper end is fixed.
    assert ed.decades(cap_year=2030) == (1970,)


# ---------------------------------------------------------------------------
# Invalid-input table
# ---------------------------------------------------------------------------

INVALID_VALUES = [
    "garbage",
    "19",  # only 2 year digits
    "1970-13",  # month 13
    "1970/",  # missing B in interval
    "",  # empty
    "1970-00",  # month 00
    "1970-06-00",  # day 00
    "1970-06-32",  # day 32
    "1970-25",  # bad season code
    "197Y",  # invalid unspecified digit position
    "1970-06-15-extra",  # trailing garbage
    "1975/1970",  # inverted interval (start after end)
]


@pytest.mark.parametrize("bad", INVALID_VALUES)
def test_invalid_edtf_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        EdtfDate(bad)


def test_edtf_is_frozen_and_hashable() -> None:
    ed = EdtfDate("1968")
    assert hash(ed) is not None
    with pytest.raises((AttributeError, TypeError)):
        ed.value = "2000"  # type: ignore[misc]


def test_edtf_equality() -> None:
    assert EdtfDate("1968") == EdtfDate("1968")
    assert EdtfDate("1968") != EdtfDate("1969")
