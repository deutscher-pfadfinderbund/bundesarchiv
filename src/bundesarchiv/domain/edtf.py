"""EDTF Level 0/1 value object for archival dates. ``_GRAMMAR`` is the supported subset."""

import calendar
import datetime
from dataclasses import dataclass, field
from enum import Enum

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedInput, VisitError

_GRAMMAR = r"""
start     : point | _interval
_interval : point "/" (point | _nonpoint) | _nonpoint "/" point
_nonpoint : open | unknown
open      : ".."
unknown   :
point     : _span [QUAL] | season
_span     : day | month | year | decade | century
day       : YEAR "-" MONTH "-" DAY
month     : YEAR "-" MONTH ["-" "XX"]
season    : YEAR "-" SEASON
year      : YEAR ["-" "XX" ["-" "XX"]]
decade    : DECADE_DIGITS "X"
century   : CENTURY_DIGITS "XX"
YEAR      : DIGIT~4
DECADE_DIGITS  : DIGIT~3
CENTURY_DIGITS : DIGIT~2
MONTH     : "0" "1".."9" | "1" "0".."2"
DAY       : "0" "1".."9" | "1".."2" DIGIT | "3" "0".."1"
SEASON    : "2" "1".."4"
QUAL      : "?" | "~" | "%"
DIGIT     : "0".."9"
"""

_PARSER = Lark(_GRAMMAR, parser="lalr")


class Season(Enum):
    SPRING = 21
    SUMMER = 22
    AUTUMN = 23
    WINTER = 24


#: Each season's first and last month; winter's last lies in the following year.
_SEASON_MONTHS: dict[Season, tuple[int, int]] = {
    Season.SPRING: (3, 5),
    Season.SUMMER: (6, 8),
    Season.AUTUMN: (9, 11),
    Season.WINTER: (12, 2),
}


@dataclass(frozen=True, slots=True)
class Day:
    date: datetime.date


@dataclass(frozen=True, slots=True)
class Month:
    """``1968-06``: June 1968, a month of one year."""

    year: int
    month: int


@dataclass(frozen=True, slots=True)
class YearSeason:
    year: int
    season: Season


@dataclass(frozen=True, slots=True)
class Year:
    year: int


@dataclass(frozen=True, slots=True)
class Decade:
    """``197X``: ``first_year`` 1970."""

    first_year: int


@dataclass(frozen=True, slots=True)
class Century:
    """``19XX``: ``first_year`` 1900."""

    first_year: int


type Span = Day | Month | YearSeason | Year | Decade | Century


@dataclass(frozen=True, slots=True)
class Point:
    """One date, at its precision; ``%`` is both uncertain and approximate."""

    span: Span
    uncertain: bool = False
    approximate: bool = False


@dataclass(frozen=True, slots=True)
class OpenEnd:
    """An interval's ``..`` end."""


@dataclass(frozen=True, slots=True)
class UnknownEnd:
    """An interval's empty end."""


type EdtfPart = Point | OpenEnd | UnknownEnd


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


@v_args(inline=True)
class _Parts(Transformer[Token, tuple[EdtfPart, ...]]):
    """Terminals become numbers, rules become parts."""

    YEAR = MONTH = DAY = int

    def SEASON(self, code: Token) -> Season:
        return Season(int(code))

    def DECADE_DIGITS(self, digits: Token) -> int:
        return int(digits) * 10

    def CENTURY_DIGITS(self, digits: Token) -> int:
        return int(digits) * 100

    month, season, year, decade, century = Month, YearSeason, Year, Decade, Century
    open, unknown = OpenEnd, UnknownEnd

    def day(self, year: int, month: int, day: int) -> Day:
        return Day(datetime.date(year, month, day))

    def point(self, span: Span, qualifier: Token | None = None) -> Point:
        return Point(span, uncertain=qualifier in ("?", "%"), approximate=qualifier in ("~", "%"))

    def start(self, *parts: EdtfPart) -> tuple[EdtfPart, ...]:
        return parts


def _parse(value: str) -> tuple[EdtfPart, ...]:
    try:
        return _Parts().transform(_PARSER.parse(value))
    except UnexpectedInput as err:
        raise ValueError(f"unrecognised EDTF value: {value!r}") from err
    except VisitError as err:  # only ``day`` raises: a day its month lacks
        raise ValueError(f"invalid EDTF date: {value!r}") from err.orig_exc


def _range(span: Span) -> tuple[datetime.date, datetime.date]:
    match span:
        case Day(date):
            return date, date
        case Month(year, month):
            return datetime.date(year, month, 1), datetime.date(year, month, _last_day(year, month))
        case YearSeason(year, season):
            first, last = _SEASON_MONTHS[season]
            end_year = year + (last < first)
            return datetime.date(year, first, 1), datetime.date(
                end_year, last, _last_day(end_year, last)
            )
        case Year(year):
            return datetime.date(year, 1, 1), datetime.date(year, 12, 31)
        case Decade(first_year):
            return datetime.date(first_year, 1, 1), datetime.date(first_year + 9, 12, 31)
        case Century(first_year):
            return datetime.date(first_year, 1, 1), datetime.date(first_year + 99, 12, 31)


def _decade_of(d: datetime.date) -> int:
    return (d.year // 10) * 10


@dataclass(frozen=True, slots=True)
class EdtfDate:
    """Validated EDTF Level 0/1 date. Raises ValueError on invalid input.

    Qualifiers (``?`` ``~`` ``%``) are stored verbatim but do not affect ``bounds()``;
    they carry display-level uncertainty only.
    """

    value: str
    _parts: tuple[EdtfPart, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_parts", _parse(self.value))
        lo, hi = self.bounds()
        # Bounds feed SQL date-range columns; an inverted range would silently match nothing.
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"invalid EDTF interval (start after end): {self.value!r}")

    def parts(self) -> tuple[EdtfPart, ...]:
        """One point, or an interval's two ends; at least one end is a point."""
        return self._parts

    def bounds(self) -> tuple[datetime.date | None, datetime.date | None]:
        """(earliest, latest); ``None`` for an open or unknown end: unbounded."""
        first, last = self._parts[0], self._parts[-1]
        lo = _range(first.span)[0] if isinstance(first, Point) else None
        hi = _range(last.span)[1] if isinstance(last, Point) else None
        return lo, hi

    def decades(self, *, cap_year: int) -> tuple[int, ...]:
        """From the first point's decade; ``cap_year`` caps only an unbounded upper end, at the
        decade of ``cap_year - 1``."""
        first_point = next(part for part in self._parts if isinstance(part, Point))
        _, hi = self.bounds()
        if hi is None:
            hi = datetime.date(cap_year - 1, 12, 31)
        first_decade = _decade_of(_range(first_point.span)[0])
        last_decade = _decade_of(hi)
        return tuple(range(first_decade, last_decade + 1, 10))
