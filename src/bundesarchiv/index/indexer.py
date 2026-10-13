"""Materializes the canonical files into ``ArticleIndex`` rows.

Fail-closed (ADR 0012): an Article that cannot be resolved or decoded gets an archivist-only row,
never a guessed visibility.
"""

import logging
import mimetypes
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from django.db import connection, transaction
from django.db.models import F, Func

from bundesarchiv.domain.access import ARCHIVIST_ONLY_FIELDS
from bundesarchiv.domain.audience import ARCHIVIST_ONLY, effective_audience
from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import Article, Collection, Lifecycle, MediaRef, Ulid
from bundesarchiv.index.models import ArticleIndex, MediaText
from bundesarchiv.index.query import FileKind
from bundesarchiv.index.scope import ScopeColumns, _scope_columns
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import NotFound, UnreadableReadme
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

logger = logging.getLogger(__name__)

# Bump on any change to build_row's output or to the ADR 0011 FTS config, collation or tsvector
# wrappers; rows of another version trigger a rebuild.
CONFIG_VERSION = 8

# Never change it, never reuse it for another lock (ADR 0014).
_INDEX_WRITER_LOCK_KEY = 0x42554E44


#: Long enough to outwait a typical full rebuild; on timeout the retry job reindexes.
SYNC_LOCK_TIMEOUT_MS = 5000


def _take_writer_lock(lock_timeout_ms: int | None = None) -> None:
    """Acquire the transaction-scoped index-writer advisory lock. MUST be called inside every index
    writer's ``transaction.atomic()`` block BEFORE its first canonical read; it releases at commit
    or rollback, so no explicit unlock is ever needed. With ``lock_timeout_ms`` the wait is bounded
    for the rest of the transaction and a timeout raises ``OperationalError``."""
    with connection.cursor() as cursor:
        if lock_timeout_ms is not None:
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", [f"{lock_timeout_ms}ms"])
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_INDEX_WRITER_LOCK_KEY])


# The exact Article fields ``_archivist_text`` folds — its own declaration of what it reads. If the
# domain floor grows a field, or the builder starts reading one outside it, the module fails to
# import: a fail-closed drift trip, never a silent under- or over-index. A raise, not an assert:
# `python -O` must not strip it.
_BUILDER_FIELDS: frozenset[str] = frozenset({"physical_location", "custom"})
if _BUILDER_FIELDS != ARCHIVIST_ONLY_FIELDS:
    raise RuntimeError("archivist_text builder drifted from the domain floor")


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """The outcome of a full ``rebuild``. ``failed_closed`` names the ulids indexed as
    fail-closed archivist-only rows (a resolution error), for the caller/CLI to surface so an
    Archivist can repair the source. ``unreadable_articles`` and ``unreadable_collections`` name
    the records whose README does not decode (owner 2026-10-01): such an Article is indexed
    archivist-only, such a Collection is treated as absent."""

    indexed: int
    failed_closed: tuple[str, ...]
    unreadable_articles: tuple[str, ...]
    unreadable_collections: tuple[str, ...]


def _archivist_text(article: Article) -> str:
    """Custom keys are structure, not prose: only their values are indexed."""
    custom_values = [value for _key, value in article.custom]
    return " ".join([article.physical_location or "", *custom_values]).strip()


def build_row(article: Article, chain: ResolvedChain, *, cap_year: int) -> dict[str, object]:
    ancestors = [c.ulid for c in chain.collections]
    scope = _scope_columns(effective_audience(article, chain))
    return _content_columns(article, ancestors=ancestors, cap_year=cap_year) | _scope_dict(scope)


def _body_text(article: Article) -> str:
    """Captions are member-visible (ADR 0015), so they ride the body weight, not
    ``archivist_text``."""
    captions = [m.caption for m in article.media if m.caption]
    return " ".join([article.body, *captions]).strip()


# The stdlib's built-in table only, never the host's mime.types: a rebuild on any machine yields the
# same kinds.
_MIME_TABLE = mimetypes.MimeTypes()
_KIND_BY_MAJOR = {"image": FileKind.IMAGE, "video": FileKind.VIDEO, "audio": FileKind.AUDIO}


def mime_type(ref: MediaRef) -> str:
    """One file's MIME type: as recorded, else the one its name's extension implies; ``""`` when
    neither says."""
    return (ref.media_type or _MIME_TABLE.guess_file_type(ref.filename)[0] or "").lower()


def file_kind(ref: MediaRef) -> FileKind:
    """The kind of one file by its ``mime_type``; anything unrecognised is ``OTHER``."""
    mime = mime_type(ref)
    if mime == "application/pdf":
        return FileKind.PDF
    return _KIND_BY_MAJOR.get(mime.partition("/")[0], FileKind.OTHER)


def _file_counts(article: Article) -> dict[str, int]:
    """The ``file_counts`` column: how many of the Article's files are of each kind."""
    return dict(Counter(file_kind(ref).value for ref in article.media))


def _content_columns(article: Article, *, ancestors: list[str], cap_year: int) -> dict[str, object]:
    earliest, latest, decades = _date_columns(article, cap_year=cap_year)
    return {
        "ulid": article.ulid,
        "title": article.title,
        "body": _body_text(article),
        "creator": article.creator,
        "subject_place": article.subject_place,
        "ref_code": article.ref_code,
        "media_type": article.media_type,
        "document_type": article.document_type,
        "tags": list(article.tags),
        "archivist_text": _archivist_text(article),
        "is_draft": article.lifecycle is Lifecycle.DRAFT,
        "is_template": article.template,
        "added_at": article.added_at,
        "deleted_at": article.deleted.at if article.deleted else None,
        "deleted_by": article.deleted.by if article.deleted else None,
        "file_counts": _file_counts(article),
        "media_hashes": [ref.content_hash for ref in article.media],
        "date_edtf": article.date.value if article.date is not None else None,
        "date_earliest": earliest,
        "date_latest": latest,
        "decades": list(decades),
        "collection_id": article.collection_id,
        "collection_ancestors": ancestors,
        "config_version": CONFIG_VERSION,
    }


def _scope_dict(scope: ScopeColumns) -> dict[str, object]:
    return {
        "archivist_only": scope.archivist_only,
        "tier": scope.tier,
        "groups": list(scope.groups),
    }


def _date_columns(article: Article, *, cap_year: int) -> tuple[object, object, tuple[int, ...]]:
    """(date_earliest, date_latest, decades) from the Article's EDTF date, or nulls/empty when
    it has none. ``date_latest`` is ``None`` for an open-ended interval (the EdtfDate bounds)."""
    if article.date is None:
        return None, None, ()
    earliest, latest = article.date.bounds()
    return earliest, latest, article.date.decades(cap_year=cap_year)


def _fail_closed_row(article: Article, *, cap_year: int) -> dict[str, object]:
    """Still indexed, so an Archivist can find and repair the source (ADR 0012)."""
    content = _content_columns(article, ancestors=[], cap_year=cap_year)
    return content | _scope_dict(_scope_columns(ARCHIVIST_ONLY))


def _row_for(
    article: Article, lookup: dict[Ulid, Collection], *, cap_year: int
) -> tuple[dict[str, object], bool]:
    """The row, and whether it failed closed (ADR 0012)."""
    try:
        chain = resolve_chain(article.collection_id, lookup)
        return build_row(article, chain, cap_year=cap_year), False
    except DomainError:
        return _fail_closed_row(article, cap_year=cap_year), True


def _unreadable_row(ulid: Ulid, *, cap_year: int) -> dict[str, object]:
    """The row of an Article whose README does not decode (owner 2026-10-01): archivist-only, with
    the ulid, all that is known, as its title. Built from a stand-in so every column is written,
    and an upsert keeps nothing of the old row."""
    stand_in = Article(ulid=ulid, title=ulid, collection_id="", lifecycle=Lifecycle.PUBLISHED)
    return _fail_closed_row(stand_in, cap_year=cap_year)


def _collection_lookup(store: ObjectStore) -> tuple[dict[Ulid, Collection], tuple[Ulid, ...]]:
    """Every saved Collection by ulid, the lookup ``resolve_chain`` takes, and the ulids of those
    left out because their README does not decode."""
    scan = CollectionRepository(store).scan()
    return {c.ulid: c for c in scan.readable}, scan.unreadable


def rebuild(store: ObjectStore) -> RebuildReport:
    """Rebuild the index from the canonical files in one transaction. On return ``ArticleIndex``
    holds one row per Article, ``MediaText`` holds only text some row names (ADR 0023), and every
    page vector matches the current config. An Article that cannot be indexed (a ``DomainError``, a
    README that does not decode) gets an archivist-only row, reported in the ``RebuildReport``.

    Holds the shared index-writer lock throughout (ADR 0014 v2); searches see the old rows until
    it commits.
    """
    articles = ArticleRepository(store)
    cap_year = _current_year()

    with transaction.atomic():
        _take_writer_lock()
        lookup, unreadable_collections = _collection_lookup(store)
        scan = articles.scan()
        built = [(a.ulid, *_row_for(a, lookup, cap_year=cap_year)) for a in scan.readable]
        rows = [row for _, row, _ in built]
        rows += [_unreadable_row(ulid, cap_year=cap_year) for ulid in scan.unreadable]
        # No row at all leaves nothing to tell which config the kept page vectors were built under.
        stale = config_stale() or not ArticleIndex.objects.exists()
        ArticleIndex.objects.all().delete()
        ArticleIndex.objects.bulk_create(ArticleIndex(**row) for row in rows)
        named = ArticleIndex.objects.annotate(_hash=Func(F("media_hashes"), function="unnest"))
        MediaText.objects.exclude(content_hash__in=named.values("_hash")).delete()
        if stale:
            # Postgres recomputes a stored generated column
            MediaText.objects.update(text=F("text"))

    for ulid in (*unreadable_collections, *scan.unreadable):
        logger.warning("the README of %s does not decode", ulid)
    failed = tuple(ulid for ulid, _, failed_closed in built if failed_closed)
    return RebuildReport(len(rows), failed, scan.unreadable, unreadable_collections)


def config_stale() -> bool:
    """Whether a row of the index was written under another ``CONFIG_VERSION``."""
    return ArticleIndex.objects.exclude(config_version=CONFIG_VERSION).exists()


def index_article(store: ObjectStore, ulid: Ulid, *, lock_timeout_ms: int | None = None) -> None:
    """A ``lock_timeout_ms`` timeout raises ``OperationalError`` with nothing written."""
    articles = ArticleRepository(store)
    cap_year = _current_year()

    with transaction.atomic():
        _take_writer_lock(lock_timeout_ms)
        try:
            article = articles.load(ulid).article
        except NotFound:
            ArticleIndex.objects.filter(ulid=ulid).delete()
            return
        except UnreadableReadme:
            row = _unreadable_row(ulid, cap_year=cap_year)
        else:
            lookup, _ = _collection_lookup(store)
            row, _failed = _row_for(article, lookup, cap_year=cap_year)
        ArticleIndex.objects.update_or_create(ulid=ulid, defaults=row)


def index_subtree(
    store: ObjectStore, collection_ulid: Ulid, *, lock_timeout_ms: int | None = None
) -> None:
    """An Article whose README does not decode is left to ``rebuild``."""
    articles = ArticleRepository(store)
    cap_year = _current_year()

    with transaction.atomic():
        _take_writer_lock(lock_timeout_ms)
        lookup, _ = _collection_lookup(store)
        for article in articles.scan().readable:
            if _in_subtree(article, collection_ulid, lookup):
                row, _failed = _row_for(article, lookup, cap_year=cap_year)
                ArticleIndex.objects.update_or_create(ulid=article.ulid, defaults=row)


def _in_subtree(article: Article, collection_ulid: Ulid, lookup: dict[Ulid, Collection]) -> bool:
    try:
        chain = resolve_chain(article.collection_id, lookup)
    except DomainError:
        return article.collection_id == collection_ulid
    return any(c.ulid == collection_ulid for c in chain.collections)


#: A page's text is cut here, so its tsvector stays under Postgres' 1 MB cap whatever the page holds
#: (the densest legacy page holds 13,753 characters).
_MAX_PAGE_CHARS = 100_000

#: What Postgres refuses in a text column: NUL, and a lone surrogate (it has no UTF-8 form).
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


def store_media_text(content_hash: str, pages: Sequence[str]) -> None:
    """Store the page texts of the file with ``content_hash``, page 1 first; no pages stores the
    page-0 marker. Rows already stored win: the same hash is the same file, so the same text.
    Stores every page or none."""
    MediaText.objects.bulk_create(
        (
            MediaText(
                content_hash=content_hash,
                page=number,
                text=_UNSTORABLE.sub("", text)[:_MAX_PAGE_CHARS],
            )
            for number, text in enumerate(pages or ("",), 1 if pages else 0)
        ),
        ignore_conflicts=True,
    )


def hashes_with_text(hashes: Iterable[str]) -> frozenset[str]:
    """Which of ``hashes`` already have page rows, so their files count as read."""
    return frozenset(
        MediaText.objects.filter(content_hash__in=list(hashes))
        .values_list("content_hash", flat=True)
        .distinct()
    )


def _current_year() -> int:
    import datetime

    return datetime.date.today().year  # noqa: DTZ011 — decade bucketing wants the LOCAL year
