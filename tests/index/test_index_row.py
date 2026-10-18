from django.db.models import GeneratedField

from bundesarchiv.index import query
from bundesarchiv.index.indexer import IndexRow
from bundesarchiv.index.models import ArticleIndex


def test_the_index_row_names_every_column_the_database_does_not_fill() -> None:
    """An upsert keeps the old value of a column the row leaves out, so a column the indexer
    forgets would keep an older, more open scope (ADR 0012)."""
    written = {
        field.name
        for field in ArticleIndex._meta.concrete_fields
        if not isinstance(field, GeneratedField)
    }
    assert IndexRow.__required_keys__ == written


def test_a_hit_row_reads_only_columns_the_index_has() -> None:
    """``search`` reads ``.values()`` by these names; a misspelt one would fail only against
    Postgres."""
    columns = {field.name for field in ArticleIndex._meta.concrete_fields}
    assert set(query._HitRow.__annotations__) <= columns
