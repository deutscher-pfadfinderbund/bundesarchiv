"""Derived, disposable search rows, never the source of truth (ADR 0003, ADR 0004).

Each tsvector is a generated column over an ``IMMUTABLE`` SQL wrapper (migrations 0001, 0009): the
ADR 0011 expression is only ``STABLE``.
"""

import re
from typing import ClassVar

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import F, Func
from django.db.models.indexes import Index

from bundesarchiv.domain.history import Act, Difference, VersionEntry
from bundesarchiv.domain.models import ULID, Change

#: What Postgres refuses in a text column: NUL, and a lone surrogate (it has no UTF-8 form).
UNSTORABLE = re.compile("[\x00\ud800-\udfff]")

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
    return Func(
        *(F(name) for name in field_names),
        function=function,
        output_field=SearchVectorField(),
    )


class ArticleIndex(models.Model):
    ulid = models.TextField(primary_key=True)
    title = models.TextField()
    body = models.TextField(blank=True, default="")
    creator = models.TextField(null=True)
    subject_place = models.TextField(null=True)
    ref_code = models.TextField(null=True)
    media_type = models.TextField(null=True)
    document_type = models.TextField(null=True)
    tags = ArrayField(models.TextField(), default=list)
    # The archivist-only fields' text, folded by the indexer; its drift check pins the sources to
    # the domain's ARCHIVIST_ONLY_FIELDS floor.
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
    # Chrome, never scope: archivist_only also covers rows that are not drafts.
    is_draft = models.BooleanField(default=False)
    is_template = models.BooleanField(default=False)  # a Vorlage
    added_at = models.DateTimeField(null=True)  # None = unknown
    # The Papierkorb mark (ADR 0022); a marked row is also archivist_only.
    deleted_at = models.DateTimeField(null=True)
    deleted_by = models.TextField(null=True)
    # {FileKind value: count} of the Article's media, zero kinds absent; {} = no files.
    file_counts = models.JSONField(default=dict)
    # The content hash of each file, in media order: how a row reaches its files' ``MediaText``.
    media_hashes = ArrayField(models.TextField(), default=list)
    # indexer.CONFIG_VERSION at write time
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
        indexes: ClassVar[list[Index]] = [
            GinIndex(fields=["general_tsv"], name="index_general_tsv_gin"),
            GinIndex(fields=["archivist_tsv"], name="index_archivist_tsv_gin"),
            Index(fields=["date_earliest"], name="index_date_earliest_btree"),
            Index(fields=["added_at"], name="index_added_at_btree"),
        ]


class MediaText(models.Model):
    """The text of one page of a media file, by the file's content hash; pages count from 1, and
    page 0 with empty text marks a file read with nothing usable. It carries no audience
    (ADR 0023)."""

    pk = models.CompositePrimaryKey("content_hash", "page")
    content_hash = models.TextField()
    page = models.IntegerField()
    text = models.TextField()
    tsv = models.GeneratedField(
        expression=_wrapper("bundesarchiv_text_tsv", "text"),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    class Meta:
        indexes: ClassVar[list[Index]] = [GinIndex(fields=["tsv"], name="index_media_text_tsv_gin")]


class ArticleVersion(models.Model):
    """One version of an Article as its ``VersionEntry``, derived from the files. A rebuild keeps
    the rows unless the config is stale. The row of a version below the Article's current one never
    changes: history files are create-only. ``changed_at`` and ``changed_by`` are both set or both
    absent (a version without a readable change record); ``difference`` is NULL when what the
    version changed is unknown."""

    pk = models.CompositePrimaryKey("ulid", "version")
    ulid = models.TextField()
    version = models.IntegerField()
    changed_at = models.DateTimeField(null=True)
    changed_by = models.TextField(null=True)
    difference = models.JSONField(null=True)

    @classmethod
    def of(cls, ulid: ULID, entry: VersionEntry) -> ArticleVersion:
        change, difference = entry.change, entry.difference
        return cls(
            ulid=ulid,
            version=entry.version,
            changed_at=change.at if change else None,
            changed_by=change.by if change else None,
            difference=None
            if difference is None
            else {
                "fields": sorted(difference.fields),
                "custom": sorted(_storable(key) for key in difference.custom),
                "added": [[_storable(text) for text in file] for file in difference.added],
                "removed": [[_storable(text) for text in file] for file in difference.removed],
                "acts": sorted(act.value for act in difference.acts),
            },
        )

    def entry(self) -> VersionEntry:
        at, by, stored = self.changed_at, self.changed_by, self.difference
        return VersionEntry(
            self.version,
            None if at is None or by is None else Change(at, by),
            None
            if stored is None
            else Difference(
                fields=frozenset(stored["fields"]),
                custom=frozenset(stored["custom"]),
                added=tuple((content_hash, name) for content_hash, name in stored["added"]),
                removed=tuple((content_hash, name) for content_hash, name in stored["removed"]),
                acts=frozenset(Act(act) for act in stored["acts"]),
            ),
        )


def _storable(text: str) -> str:
    return UNSTORABLE.sub("", text)
