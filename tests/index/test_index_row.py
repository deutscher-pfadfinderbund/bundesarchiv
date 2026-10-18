from django.db.models import GeneratedField

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
