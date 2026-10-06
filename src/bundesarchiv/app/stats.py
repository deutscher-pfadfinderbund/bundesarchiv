"""Archive statistics for the operator's dashboard: what the hourly reconcile logs after a rebuild.

Counts are archive-wide, never scoped to a viewer and never per user. Canonical truth gives the
Articles, files and bytes; the index gives the audience levels; Procrastinate's table the queue.
"""

import logging
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.db.models import Count
from procrastinate.contrib.django.models import ProcrastinateJob

from bundesarchiv.app import thumbnails
from bundesarchiv.index.indexer import mime_type
from bundesarchiv.index.models import ArticleIndex
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

logger = logging.getLogger(__name__)

_LEVELS = {"PUBLIC": "audience_public", "MEMBERS": "audience_members", "GROUPS": "audience_groups"}


def log_archive_stats(store: ObjectStore, *, index_rows_before: int | None = None) -> None:
    """One ``archive stats`` record, then one ``archive media type`` record per MIME type.
    ``articles`` counts the undecodable ones too; ``media_without_thumbnail`` counts distinct files
    of a kind that has a renderer; ``index_drift`` is the index rows BEFORE the reconcile's rebuild
    (``index_rows_before``; else the current rows) minus canonical Articles: what the rebuild repaired."""
    scan = ArticleRepository(store).scan()
    articles = scan.readable
    refs = [ref for article in articles for ref in article.media]
    per_type = Counter(mime_type(ref) or "unknown" for ref in refs)
    bytes_per_type = Counter[str]()
    for ref in refs:
        bytes_per_type[mime_type(ref) or "unknown"] += ref.byte_size or 0
    root = Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
    rendered = {ref.content_hash for ref in refs if thumbnails.renders(ref)}
    levels = dict(ArticleIndex.objects.values_list("tier").annotate(n=Count("ulid")))
    rows = sum(levels.values())
    jobs = dict(ProcrastinateJob.objects.values_list("status").annotate(n=Count("id")))
    total = len(articles) + len(scan.unreadable)
    fields: dict[str, object] = {
        "articles": total,
        "collections": len(CollectionRepository(store).scan().readable),
        "media_files": len(refs),
        "media_bytes": sum(bytes_per_type.values()),
        "in_trash": sum(a.deleted is not None for a in articles),
        "articles_without_media": sum(not a.media for a in articles),
        **{name: levels.get(tier, 0) for tier, name in _LEVELS.items()},
        "audience_archivist_only": levels.get(None, 0),
        "articles_without_date": sum(a.date is None for a in articles),
        "articles_without_description": sum(not a.body.strip() for a in articles),
        "articles_without_tags": sum(not a.tags for a in articles),
        "media_without_thumbnail": sum(
            not thumbnails.thumbnail_path(root, h).exists() for h in rendered
        ),
        "index_rows": rows,
        "index_drift": (rows if index_rows_before is None else index_rows_before) - total,
        "jobs_todo": jobs.get("todo", 0),
        "jobs_doing": jobs.get("doing", 0),
        "jobs_failed": jobs.get("failed", 0),
    }
    logger.info("archive stats", extra=fields)
    for media_type, count in sorted(per_type.items()):
        extra = {"media_type": media_type, "files": count, "bytes": bytes_per_type[media_type]}
        logger.info("archive media type", extra=extra)
