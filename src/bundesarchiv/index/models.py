"""The derived search-index row — a private, disposable Postgres materialization.

``ArticleIndex`` is one flattened, denormalized row per Article, built by the indexer
(Task 7) from the files-canonical core and queried viewer-scoped by ``search`` (Task 8).
It is NOT the source of truth: the whole table can be dropped and rebuilt from the README
files at any time (ADR 0003, 0004). Nothing here is exported from ``bundesarchiv.index`` —
the model is an implementation detail of the adapter.

The two ``tsvector`` columns are database-generated (``GENERATED ALWAYS ... STORED``) so
Postgres, not Python, keeps them in lockstep with the source columns on every write. The
``bundesarchiv_german`` text-search configuration they use is pinned in
[ADR 0011](../../docs/adr/0011-german-fts-config.md).

ORM-vs-RunSQL outcome (brief decision point). The generated columns cannot be pure-ORM
``GeneratedField``s over the inline ADR expression: Postgres requires a generated column's
expression to be ``IMMUTABLE``, but the ADR expression relies on ``array_to_string(tags,' ')``
(and, transitively, the ``unaccent``-based config), both only ``STABLE``. Django can render the
expression but Postgres rejects it ("generation expression is not immutable"). The resolution —
still ORM-first for the column itself — is to move the verbatim ADR expression into two
``IMMUTABLE`` SQL wrapper functions (``bundesarchiv_general_tsv`` / ``bundesarchiv_archivist_tsv``,
created by RunSQL in migration ``0001_search_infrastructure``) and declare each ``GeneratedField``
as a single call to its wrapper. So: the FTS config, ICU collation and the two wrapper functions
are RunSQL DDL in 0001; the table, its scalar/array columns, the two generated ``tsvector``
columns (each a one-line wrapper call) and all indexes are ORM in ``0002_articleindex``. Marking
the wrappers ``IMMUTABLE`` is safe because the index is derived and disposable — if the config or
``unaccent`` rules ever change, the config_version bumps and the index is rebuilt (ADR 0003).
"""

from typing import ClassVar

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import F, Func
from django.db.models.indexes import Index

from bundesarchiv.domain.access import ARCHIVIST_ONLY_FIELDS

# The archivist-only text sources this index folds into ``archivist_text`` (indexer, Task 7).
# ``media`` carries no indexable text, so it is not here; the guard below forces this partition
# to track the domain floor. If ARCHIVIST_ONLY_FIELDS ever grows a new text-bearing field, this
# assert fails at import until the indexer (and this set) are updated — a fail-closed drift trip,
# not a silent under-index. Lives next to the ``archivist_text`` column, its natural home; Task 7
# imports the constant from here.
_ARCHIVIST_TEXT_SOURCES: frozenset[str] = frozenset({"physical_location", "custom"})
assert _ARCHIVIST_TEXT_SOURCES == ARCHIVIST_ONLY_FIELDS, (
    "index archivist partition drifted from domain floor"
)

# The source columns each wrapper reads, in call order. These MUST match the argument order of
# the SQL functions created in migration 0001 — the migration and this model are one contract.
_GENERAL_TSV_ARGS = (
    "title",
    "ref_code",
    "tags",
    "creator",
    "subject_place",
    "media_type",
    "document_type",
    "body",
)
_ARCHIVIST_TSV_ARGS = ("archivist_text",)


def _wrapper(function: str, *field_names: str) -> Func:
    """A call to one of the ``IMMUTABLE`` tsvector wrapper functions from migration 0001.

    The weighted ADR-0011 expression lives inside the SQL function (see the module docstring on
    why it can't be inlined into the generated column); the ORM side is just the call, which keeps
    the ``GeneratedField`` serialization in the migration tiny and refactor-stable.
    """
    return Func(
        *(F(name) for name in field_names),
        function=function,
        output_field=SearchVectorField(),
    )


class ArticleIndex(models.Model):
    """One denormalized, disposable search row per Article (ADR 0003/0004). Private to the
    ``bundesarchiv.index`` adapter — not part of its public interface."""

    ulid = models.TextField(primary_key=True)
    title = models.TextField()
    body = models.TextField(blank=True, default="")
    creator = models.TextField(null=True)
    subject_place = models.TextField(null=True)
    ref_code = models.TextField(null=True)
    media_type = models.TextField(null=True)
    document_type = models.TextField(null=True)
    tags = ArrayField(models.TextField(), default=list)
    # physical_location + custom values, folded by the indexer (Task 7). The drift guard above
    # pins these sources to the domain's ARCHIVIST_ONLY_FIELDS floor.
    archivist_text = models.TextField(blank=True, default="")
    date_edtf = models.TextField(null=True)
    date_earliest = models.DateField(null=True)
    date_latest = models.DateField(null=True)  # None = open end
    decades = ArrayField(models.IntegerField(), default=list)
    collection_id = models.TextField()
    # leaf→root, including the Article's own collection
    collection_ancestors = ArrayField(models.TextField(), default=list)
    archivist_only = models.BooleanField()
    tier = models.TextField(null=True)  # "PUBLIC" | "MEMBERS" | "GROUPS"; None iff archivist_only
    groups = ArrayField(models.TextField(), default=list)
    # bump when the FTS config changes (indexer.CONFIG_VERSION) to trigger a rebuild
    config_version = models.IntegerField()

    general_tsv = models.GeneratedField(
        expression=_wrapper("bundesarchiv_general_tsv", *_GENERAL_TSV_ARGS),
        output_field=SearchVectorField(),
        db_persist=True,
    )
    archivist_tsv = models.GeneratedField(
        expression=_wrapper("bundesarchiv_archivist_tsv", *_ARCHIVIST_TSV_ARGS),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    class Meta:
        # GIN on both tsvectors (FTS); btree on the two most-filtered facets (ADR 0011 / brief).
        indexes: ClassVar[list[Index]] = [
            GinIndex(fields=["general_tsv"], name="index_general_tsv_gin"),
            GinIndex(fields=["archivist_tsv"], name="index_archivist_tsv_gin"),
            Index(fields=["collection_id"], name="index_collection_id_btree"),
            Index(fields=["date_earliest"], name="index_date_earliest_btree"),
        ]
