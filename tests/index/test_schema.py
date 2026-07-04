"""Schema-level guards for the index migrations and the ``ArticleIndex`` generated columns.

Complements ``test_fts_german.py`` (which pins the ``bundesarchiv_german`` config behaviour at
the SQL level): this module exercises the migration/model contract Task 6 adds —

- the migrations apply on a fresh DB (pytest-django's test-DB creation runs them; a smoke assert
  here proves the schema objects landed);
- ``ref_code`` sorts under the ``de_numeric`` ICU collation via the ORM ``Collate`` expression
  (``Ä 3 < B 1 < B 2 < B 10``);
- the database-generated ``general_tsv`` / ``archivist_tsv`` columns populate on an ORM insert,
  applying the German config (a stem is present, weights are set);
- the archivist-partition drift guard tracks the domain floor.

All DB tests use the migrated test database (``django_db``), which is the point: they fail if
the migrations did not create the config, collation, wrapper functions or generated columns.
"""

import pytest
from django.db.models.functions import Collate

from bundesarchiv.domain.access import ARCHIVIST_ONLY_FIELDS
from bundesarchiv.index import models
from bundesarchiv.index.models import ArticleIndex


def _make(ulid: str, **overrides: object) -> ArticleIndex:
    """Create an ``ArticleIndex`` with the required non-null columns defaulted, plus overrides."""
    fields: dict[str, object] = {
        "ulid": ulid,
        "title": "",
        "collection_id": "C1",
        "archivist_only": False,
        "tier": "PUBLIC",
        "config_version": 1,
    }
    fields.update(overrides)
    return ArticleIndex.objects.create(**fields)


# --- Migrations applied on a fresh DB (ADR 0011 objects exist) --------------------------------


@pytest.mark.django_db
def test_search_infrastructure_objects_exist() -> None:
    """The config, ICU collation and wrapper functions from migration 0001 landed on the DB."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_ts_config WHERE cfgname = 'bundesarchiv_german'")
        assert cur.fetchone() is not None, "text search configuration missing"
        cur.execute("SELECT 1 FROM pg_collation WHERE collname = 'de_numeric'")
        assert cur.fetchone() is not None, "de_numeric collation missing"
        cur.execute(
            "SELECT 1 FROM pg_proc WHERE proname IN "
            "('bundesarchiv_general_tsv', 'bundesarchiv_archivist_tsv')"
        )
        assert len(cur.fetchall()) == 2, "tsvector wrapper functions missing"


@pytest.mark.django_db
def test_generated_columns_are_database_generated() -> None:
    """``general_tsv`` / ``archivist_tsv`` are ``GENERATED ALWAYS`` columns, not plain columns."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name, is_generated FROM information_schema.columns "
            "WHERE table_name = 'index_articleindex' AND column_name IN ('general_tsv', 'archivist_tsv') "
            "ORDER BY column_name"
        )
        rows = dict(cur.fetchall())
    assert rows == {"archivist_tsv": "ALWAYS", "general_tsv": "ALWAYS"}


# --- ICU numeric collation via the ORM Collate expression -------------------------------------


@pytest.mark.django_db
def test_ref_code_orders_by_de_numeric_collation() -> None:
    """``Collate('ref_code', 'de_numeric')`` sorts numeric + locale-aware: Ä 3 < B 1 < B 2 < B 10."""
    for i, ref in enumerate(["B 2", "B 10", "B 1", "Ä 3"]):
        _make(f"01ROW{i}", ref_code=ref)
    ordered = list(
        ArticleIndex.objects.annotate(sort_key=Collate("ref_code", "de_numeric"))
        .order_by("sort_key")
        .values_list("ref_code", flat=True)
    )
    assert ordered == ["Ä 3", "B 1", "B 2", "B 10"]


# --- Generated tsvector columns populate on an ORM insert -------------------------------------


@pytest.mark.django_db
def test_general_tsv_populates_with_german_stemming_and_weights() -> None:
    """An ORM insert triggers the generated column; the German config folds and weights apply."""
    row = _make(
        "01GEN",
        title="Bundeslager",
        body="Häuser und Bäume",
        tags=["Fahrten", "Lieder"],
        ref_code="B 12",
    )
    row.refresh_from_db()  # generated columns are computed by the DB, not Python
    tsv = str(row.general_tsv)
    assert tsv, "general_tsv should be non-empty after insert"
    # German stem of "Bundeslager" is "bundeslag", carried at weight A (from the title).
    assert "'bundeslag':1A" in tsv, tsv
    # A tag word appears (weight B); umlaut folding hits the body (Bäume -> baum, weight D/none).
    assert "'fahrt'" in tsv and "'baum'" in tsv, tsv


@pytest.mark.django_db
def test_archivist_tsv_populates_from_archivist_text() -> None:
    """The archivist tsvector is a plain (unweighted) to_tsvector of ``archivist_text``."""
    row = _make("01ARC", archivist_text="Standort Regal 4")
    row.refresh_from_db()
    tsv = str(row.archivist_tsv)
    assert tsv, "archivist_tsv should be non-empty when archivist_text is set"
    assert "standort" in tsv and "regal" in tsv, tsv
    # No weight labels on the archivist vector (weights are A/B/C/D suffixes on lexeme positions).
    assert "A" not in tsv and "B" not in tsv, f"archivist_tsv must be unweighted, got {tsv}"


@pytest.mark.django_db
def test_empty_archivist_text_yields_empty_tsv() -> None:
    """With no archivist text, the archivist tsvector is empty (the default '' path)."""
    row = _make("01EMP")
    row.refresh_from_db()
    assert str(row.archivist_tsv) == ""


# --- Drift guard: index archivist partition tracks the domain floor ---------------------------


def test_archivist_text_sources_match_domain_floor() -> None:
    """The import-time drift guard's set equals the domain floor (the guard would have raised on
    import otherwise; this pins the invariant explicitly so a future edit can't loosen it)."""
    assert models._ARCHIVIST_TEXT_SOURCES == ARCHIVIST_ONLY_FIELDS
    assert frozenset({"physical_location", "custom"}) == models._ARCHIVIST_TEXT_SOURCES
