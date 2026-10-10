"""The page text of media files (ADR 0023) and its ``IMMUTABLE`` tsvector wrapper.

The wrapper exists for the reason 0001's do: a generated column's expression must be
``IMMUTABLE``, but the ``unaccent``-based config is only ``STABLE``. Safe for the same reason too:
on a config change the config-version guard recomputes ``MediaText.tsv``
(``app.reindex.ensure_index_current``).
"""

import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations, models

# Schema-qualified config, as in 0001: lexization is search_path-independent for the column's life.
_CREATE_FUNCTION = """
CREATE FUNCTION bundesarchiv_text_tsv(page_text text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT to_tsvector('public.bundesarchiv_german'::regconfig, coalesce(page_text, ''))
$$;
"""
_DROP_FUNCTION = "DROP FUNCTION IF EXISTS bundesarchiv_text_tsv(text);"


class Migration(migrations.Migration):
    dependencies = [
        ("index", "0008_articleindex_is_template"),
    ]

    operations = [
        migrations.RunSQL(sql=_CREATE_FUNCTION, reverse_sql=_DROP_FUNCTION),
        migrations.CreateModel(
            name="MediaText",
            fields=[
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "content_hash",
                        "page",
                        blank=True,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("content_hash", models.TextField()),
                ("page", models.IntegerField()),
                ("text", models.TextField()),
                (
                    "tsv",
                    models.GeneratedField(
                        db_persist=True,
                        expression=models.Func(
                            models.F("text"),
                            function="bundesarchiv_text_tsv",
                            output_field=django.contrib.postgres.search.SearchVectorField(),
                        ),
                        output_field=django.contrib.postgres.search.SearchVectorField(),
                    ),
                ),
            ],
            options={
                "indexes": [
                    django.contrib.postgres.indexes.GinIndex(
                        fields=["tsv"], name="index_media_text_tsv_gin"
                    )
                ],
            },
        ),
    ]
