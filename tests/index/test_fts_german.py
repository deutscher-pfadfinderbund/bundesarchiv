"""Pinned executable spec for the German full-text search configuration (ADR 0011).

Regression guard for the ``bundesarchiv_german`` text-search configuration. Encodes the
decisions measured in [ADR 0011](../../docs/adr/0011-german-fts-config.md):

- v1 ships **without compound decomposition** — a bare word does not match a compound that
  contains it (``Lager`` alone does not match ``Bundeslager``).
- **Prefix matching** (``:*`` on the last token) is the mitigation — it recovers the
  compound-head recall (``Lieder`` matches ``Liederheft``).
- The config is **umlaut-insensitive**: ``unaccent`` folds accents before ``german_stem``,
  so ``Baume`` finds ``Bäume`` and ``Meissner`` finds ``Meißner``.
- ``german_stem`` conflates singular/plural (``Blatt`` ~ ``Blätter``).

(The ``de_numeric`` ref_code collation is proven where the user meets it: ``test_search``.)

Task 6 created the configuration in migration ``0001_search_infrastructure``; these run
forever against the live container as the behaviour lock.
"""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.db.backends.utils import CursorWrapper

_CONFIG = "bundesarchiv_german"


@pytest.fixture
def cursor(_pg_guard: None, db: None) -> Iterator[CursorWrapper]:
    """A live cursor on the test database (guarded like every DB fixture, tests/conftest.py)."""
    from django.db import connection

    with connection.cursor() as cur:
        yield cur


def _lexemes(cursor: CursorWrapper, text: str) -> list[str]:
    """Sorted lexemes ``to_tsvector`` produces for ``text`` under the config."""
    cursor.execute(
        "SELECT array_agg(lexeme ORDER BY lexeme) FROM unnest(to_tsvector(%s, %s)) AS lexeme",
        (_CONFIG, text),
    )
    row = cursor.fetchone()
    return list(row[0]) if row is not None and row[0] is not None else []


def _matches(cursor: CursorWrapper, doc: str, query: str) -> bool:
    """True if ``doc`` matches ``query`` (websearch form) under the config."""
    cursor.execute(
        "SELECT to_tsvector(%s, %s) @@ websearch_to_tsquery(%s, %s)",
        (_CONFIG, doc, _CONFIG, query),
    )
    row = cursor.fetchone()
    return bool(row[0]) if row is not None else False


def _matches_prefix(cursor: CursorWrapper, doc: str, query: str) -> bool:
    """True if ``doc`` matches ``query`` with a ``:*`` prefix on the last token.

    Mirrors the Part 4 UX pattern: build the websearch query, append ``:*`` to the trailing
    lexeme, reparse (ADR 0011 §6).
    """
    cursor.execute(
        "SELECT to_tsvector(%s, %s) @@ (websearch_to_tsquery(%s, %s)::text || ':*')::tsquery",
        (_CONFIG, doc, _CONFIG, query),
    )
    row = cursor.fetchone()
    return bool(row[0]) if row is not None else False


# --- Compound splitting: v1 does NOT decompose (ADR 0011 §1, Decision) ------------------

COMPOUNDS_NOT_SPLIT = [
    "Fahrtenbericht",
    "Bundeslager",
]


@pytest.mark.django_db
@pytest.mark.parametrize("word", COMPOUNDS_NOT_SPLIT)
def test_compounds_are_not_decomposed(cursor: CursorWrapper, word: str) -> None:
    """A compound produces a single lexeme — no decomposition in v1."""
    lexemes = _lexemes(cursor, word)
    assert len(lexemes) == 1, f"{word!r} should not be split, got {lexemes}"


@pytest.mark.django_db
def test_bare_head_does_not_match_compound_without_prefix(cursor: CursorWrapper) -> None:
    """Without prefix matching, a bare word does not match a compound containing it."""
    assert not _matches(cursor, "Bundeslager 1981", "Lager")
    assert not _matches(cursor, "Liederheft", "Lieder")


# --- Prefix matching mitigation (ADR 0011 §6): :* recovers compound-head recall ---------


@pytest.mark.django_db
def test_prefix_matches_compound_head(cursor: CursorWrapper) -> None:
    """With a ``:*`` prefix, a head word matches the compound that starts with it."""
    assert _matches_prefix(cursor, "Liederheft", "Lieder")
    assert _matches_prefix(cursor, "Bundeslager 1981", "Bundeslager")


# --- Umlaut folding (ADR 0011 §3): unaccent + german_stem is umlaut-insensitive ---------

UMLAUT_PAIRS = [
    ("Bäume", "Baume"),
    ("Meißner", "Meissner"),  # the ß case
]


@pytest.mark.django_db
@pytest.mark.parametrize(("umlaut", "plain"), UMLAUT_PAIRS)
def test_umlaut_less_typing_matches_umlaut_document(
    cursor: CursorWrapper, umlaut: str, plain: str
) -> None:
    """A member typing without umlauts still finds the umlauted document, both directions."""
    assert _matches(cursor, umlaut, plain), f"{plain!r} should find {umlaut!r}"
    assert _matches(cursor, plain, umlaut), f"{umlaut!r} should find {plain!r}"


# --- Stemming (ADR 0011 §3): german_stem conflates singular/plural ----------------------

SINGULAR_PLURAL = [
    ("Blatt", "Blätter"),
    ("Lied", "Lieder"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("singular", "plural"), SINGULAR_PLURAL)
def test_singular_matches_plural(cursor: CursorWrapper, singular: str, plural: str) -> None:
    """A singular query finds the plural in a title."""
    assert _matches(cursor, plural, singular), f"{singular!r} should find {plural!r}"
