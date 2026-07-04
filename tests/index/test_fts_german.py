"""Pinned executable spec for the German full-text search configuration (ADR 0011).

Regression guard for the ``bundesarchiv_german`` text-search configuration and the
``de_numeric`` ICU collation. Encodes the decisions measured in
[ADR 0011](../../docs/adr/0011-german-fts-config.md):

- v1 ships **without compound decomposition** — a bare word does not match a compound that
  contains it (``Lager`` alone does not match ``Bundeslager``).
- **Prefix matching** (``:*`` on the last token) is the mitigation — it recovers the
  compound-head recall (``Lieder`` matches ``Liederheft``).
- The config is **umlaut-insensitive**: ``unaccent`` folds accents before ``german_stem``,
  so ``Baume`` finds ``Bäume`` and ``Meissner`` finds ``Meißner``.
- ``german_stem`` conflates singular/plural (``Blatt`` ~ ``Blätter``).
- The ``de_numeric`` collation sorts ``ref_code`` numeric + locale-aware
  (``Ä 3 < B 1 < B 2 < B 10``).

Task 6 created the configuration in migration ``0001_search_infrastructure``; these run
forever against the live container as the behaviour lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.db.backends.utils import CursorWrapper

_CONFIG = "bundesarchiv_german"
_COLLATION = "de_numeric"


@pytest.fixture
def cursor(pg_connection: object) -> Iterator[CursorWrapper]:
    """A live cursor on the test database (see ``tests/index/conftest.py``)."""
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
    "Liederheft",
    "Jugendbewegung",
    "Waldläuferschule",
    "Speerjungenlager",
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
    ("Häuser", "Hauser"),
    ("Führer", "Fuhrer"),
    ("Mädchen", "Madchen"),
    ("Meißner", "Meissner"),
    ("Blätter", "Blatter"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("umlaut", "plain"), UMLAUT_PAIRS)
def test_umlaut_less_typing_matches_umlaut_document(
    cursor: CursorWrapper, umlaut: str, plain: str
) -> None:
    """A member typing without umlauts still finds the umlauted document, both directions."""
    assert _matches(cursor, umlaut, plain), f"{plain!r} should find {umlaut!r}"
    assert _matches(cursor, plain, umlaut), f"{umlaut!r} should find {plain!r}"


@pytest.mark.django_db
def test_umlaut_and_plain_share_one_lexeme(cursor: CursorWrapper) -> None:
    """Umlaut and umlaut-less spellings reduce to the same lexeme."""
    assert _lexemes(cursor, "Bäume") == _lexemes(cursor, "Baume")
    assert _lexemes(cursor, "Meißner") == _lexemes(cursor, "Meissner")


# --- Stemming (ADR 0011 §3): german_stem conflates singular/plural ----------------------

SINGULAR_PLURAL = [
    ("Blatt", "Blätter"),
    ("Bund", "Bünde"),
    ("Buch", "Bücher"),
    ("Heft", "Hefte"),
    ("Lied", "Lieder"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("singular", "plural"), SINGULAR_PLURAL)
def test_singular_matches_plural(cursor: CursorWrapper, singular: str, plural: str) -> None:
    """A singular query finds the plural in a title."""
    assert _matches(cursor, plural, singular), f"{singular!r} should find {plural!r}"


# --- ICU numeric collation (ADR 0011 §5): ref_code sorts numeric + locale-aware ---------


@pytest.mark.django_db
def test_ref_code_numeric_collation_order(cursor: CursorWrapper) -> None:
    """``de_numeric`` sorts ``Ä 3 < B 1 < B 2 < B 10`` (locale-aware + numeric)."""
    # Collation names cannot be parameterised; _COLLATION is a module constant.
    cursor.execute(
        "SELECT ref_code FROM (VALUES ('B 2'), ('B 10'), ('B 1'), (%s)) AS t(ref_code) "
        f"ORDER BY ref_code COLLATE {_COLLATION}",
        ("Ä 3",),
    )
    ordered = [row[0] for row in cursor.fetchall()]
    assert ordered == ["Ä 3", "B 1", "B 2", "B 10"]
