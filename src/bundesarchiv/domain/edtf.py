"""EDTF Level 0/1 value object for archival dates.

**Dependency decision — ``edtf`` (PyPI) rejected, verified 2026-07-04:**
The package exists as ``edtf`` 5.0.1 on PyPI (``python-edtf`` is only the GitHub repo
name). It is maintained and imports/parses fine on Python 3.14. It fails the
``mypy --strict`` typability criterion: the wheel ships a ``py.typed`` marker, but the
entry point ``parse_edtf`` is wrapped in an untyped decorator and has no return
annotation, so it — and everything reached through it — type-checks as ``Any``
(confirmed via ``reveal_type`` under mypy --strict). Adopting it would make this
module's typed boundary vacuous unless we hand-wrote stubs for its pyparsing-based
parser, which is more work than hand-rolling the small Level 0/1 subset below.

**Supported subset** (anything else raises ValueError):
- Level 0: ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD``
- Level 1: uncertainty/approximation qualifiers ``?`` ``~`` ``%`` (suffix, display-only —
  do not change bounds); unspecified digits ``197X`` / ``19XX``; intervals ``A/B``,
  ``A/..`` (open upper), ``../B`` (open lower); seasons ``YYYY-21..24``.
"""

import calendar
import datetime
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Regex patterns — order of application matters in _parse_single
# ---------------------------------------------------------------------------

# Qualifier suffix: ?, ~, %  (display-level uncertainty; does not affect bounds)
_Q = r"[?~%]?"

# YYYY-MM-DD  (most specific first)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})" + _Q + r"$")

# Seasons YYYY-21..24  (must precede YEARMONTH so 2001-22 is not parsed as month 22)
_SEASON_RE = re.compile(r"^(\d{4})-(2[1-4])$")

# YYYY-MM  (only months 01-12; season codes already caught above)
_YEARMONTH_RE = re.compile(r"^(\d{4})-(\d{2})" + _Q + r"$")

# Unspecified digits: 197X or 19XX — at least one digit must be X
_UNSPEC_RE = re.compile(r"^(\d{2})(?:(\d)(X)|X(X))" + _Q + r"$")

# Plain YYYY (with optional qualifier)
_YEAR_RE = re.compile(r"^(\d{4})" + _Q + r"$")

# Open-end sentinel in intervals
_OPEN = ".."

# Season code → (month_start, day_start, month_end, day_end)
# Winter (24) ends in Feb of the *following* year — handled specially in _parse_season.
_SEASON_BOUNDS: dict[str, tuple[int, int, int, int]] = {
    "21": (3, 1, 5, 31),  # spring
    "22": (6, 1, 8, 31),  # summer
    "23": (9, 1, 11, 30),  # autumn
    "24": (12, 1, 2, 28),  # winter (Feb end adjusted for leap year at runtime)
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _parse_single(s: str) -> tuple[datetime.date, datetime.date]:
    """Parse one EDTF token (no ``/``). Returns (earliest, latest).

    Checks patterns from most-specific to least-specific so no branch shadows another.
    Raises ValueError on any unrecognised or invalid form.
    """
    # 1. YYYY-MM-DD
    m = _DATE_RE.match(s)
    if m:
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError as err:
            raise ValueError(f"invalid EDTF date: {s!r}") from err
        return d, d

    # 2. Seasons YYYY-21..24  (before YYYY-MM so codes 21-24 are not rejected as bad months)
    ms = _SEASON_RE.match(s)
    if ms:
        return _parse_season(int(ms.group(1)), ms.group(2))

    # 3. YYYY-MM
    m2 = _YEARMONTH_RE.match(s)
    if m2:
        year, mm = int(m2.group(1)), int(m2.group(2))
        if not (1 <= mm <= 12):
            raise ValueError(f"invalid EDTF month: {s!r}")
        lo = datetime.date(year, mm, 1)
        hi = datetime.date(year, mm, _last_day(year, mm))
        return lo, hi

    # 4. Unspecified digits: 197X or 19XX
    mu = _UNSPEC_RE.match(s)
    if mu:
        century_tens = mu.group(1)  # e.g. "19"
        if mu.group(2) is not None:
            # pattern (\d)(X) matched — decade digit known, year digit is X: 197X
            decade_digit = mu.group(2)
            base = int(century_tens) * 100 + int(decade_digit) * 10
            return datetime.date(base, 1, 1), datetime.date(base + 9, 12, 31)
        # pattern X(X) matched — both unknown: 19XX
        base = int(century_tens) * 100
        return datetime.date(base, 1, 1), datetime.date(base + 99, 12, 31)

    # 5. Plain YYYY
    my = _YEAR_RE.match(s)
    if my:
        year = int(my.group(1))
        return datetime.date(year, 1, 1), datetime.date(year, 12, 31)

    raise ValueError(f"unrecognised EDTF value: {s!r}")


def _parse_season(year: int, code: str) -> tuple[datetime.date, datetime.date]:
    sm, sd, em, ed = _SEASON_BOUNDS[code]
    lo = datetime.date(year, sm, sd)
    if code == "24":
        end_year = year + 1
        hi = datetime.date(end_year, 2, _last_day(end_year, 2))
    else:
        hi = datetime.date(year, em, ed)
    return lo, hi


def _decade_of(d: datetime.date) -> int:
    return (d.year // 10) * 10


# ---------------------------------------------------------------------------
# Public value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EdtfDate:
    """Validated EDTF Level 0/1 date. Raises ValueError on invalid input.

    Qualifiers (``?`` ``~`` ``%``) are stored verbatim but do not affect ``bounds()``;
    they carry display-level uncertainty only.
    """

    value: str

    def __post_init__(self) -> None:
        # Validate eagerly so an EdtfDate in hand is always well-formed.
        _validate(self.value)

    def bounds(self) -> tuple[datetime.date, datetime.date | None]:
        """Return ``(earliest, latest)`` for this date expression.

        For open upper ends (``A/..``) ``latest`` is ``None``.
        For open lower ends (``../B``) ``earliest`` is the start of B's range
        (the only anchor available — caller should treat as unbounded-below).
        """
        return _bounds(self.value)

    def decades(self, *, cap_year: int) -> tuple[int, ...]:
        """Decade-start years spanned by this date, capped at ``cap_year``.

        ``cap_year`` is exclusive: a decade starting *at or after* ``cap_year`` is
        omitted. For open upper ends the range runs from the earliest decade up to
        (but not including) ``cap_year``'s decade.
        """
        lo, hi = self.bounds()
        if hi is None:
            hi = datetime.date(cap_year - 1, 12, 31)
        first_decade = _decade_of(lo)
        last_decade = _decade_of(hi)
        return tuple(range(first_decade, last_decade + 1, 10))


# ---------------------------------------------------------------------------
# Validation + bounds (module-private; EdtfDate is the public surface)
# ---------------------------------------------------------------------------


def _validate(value: str) -> None:
    """Raise ValueError if *value* is not a supported EDTF expression."""
    if not value:
        raise ValueError("EDTF value must not be empty")
    _bounds(value)  # parsing already raises on bad input


def _bounds(value: str) -> tuple[datetime.date, datetime.date | None]:
    """Parse *value* into ``(earliest, latest | None)``. Raises ValueError on bad input."""
    if "/" not in value:
        return _parse_single(value)

    parts = value.split("/", 1)
    left, right = parts[0], parts[1]

    # Both sides empty is nonsensical
    if not left and not right:
        raise ValueError(f"invalid EDTF interval (both ends empty): {value!r}")

    # Open upper end: "A/.."
    if right == _OPEN:
        if not left:
            raise ValueError(f"invalid EDTF interval: {value!r}")
        lo, _ = _parse_single(left)
        return lo, None

    # Empty right side (e.g. "1970/") is not the open-end notation — reject
    if not right:
        raise ValueError(f"invalid EDTF interval (missing end, use '..' for open): {value!r}")

    # Open lower end: "../B"
    if left == _OPEN or not left:
        lo_anchor, hi = _parse_single(right)
        return lo_anchor, hi

    # Closed interval: "A/B" — earliest must not exceed latest (bounds feed SQL
    # date-range columns downstream; an inverted range would silently match nothing)
    lo, _ = _parse_single(left)
    _, hi = _parse_single(right)
    if lo > hi:
        raise ValueError(f"invalid EDTF interval (start after end): {value!r}")
    return lo, hi
