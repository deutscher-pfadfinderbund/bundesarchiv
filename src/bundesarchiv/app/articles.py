"""Article write services (ordering law: app/CLAUDE.md; entry-point split: ADR 0013)."""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import assert_never

from bundesarchiv.app import after_write, media_text, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import (
    Conflicted,
    CreateResult,
    Missing,
    SaveResult,
    Updated,
    UpdateOutcome,
)
from bundesarchiv.app.tasks import enqueue_extract_media_text, enqueue_generate_thumbnail
from bundesarchiv.domain import identity
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    ULID,
    Article,
    Audience,
    Lifecycle,
    MediaRef,
    Version,
)
from bundesarchiv.persistence.errors import ArchiveError, Conflict


def save_article(
    archive: Archive, article: Article, expected_version: Version, *, changed_by: str
) -> SaveResult:
    """The form path (ADR 0013): a stale ``expected_version`` raises ``Conflict``."""
    new_version = archive.articles.save(article, expected_version, changed_by=changed_by)
    index_updated = after_write.run(archive, after_write.SavedArticle(article.ulid))
    _enqueue_derived(article)
    return SaveResult(version=new_version, index_updated=index_updated)


def update_article(
    archive: Archive,
    ulid: ULID,
    mutate: Callable[[Article], Article],
    *,
    changed_by: str,
    retries: int = 3,
) -> UpdateOutcome:
    """Never for form saves (ADR 0013). ``mutate`` must be pure, since a retry re-applies it to
    the winner: store new media with ``add_media`` before the call."""
    for _ in range(retries + 1):
        try:
            stored = archive.articles.load(ulid)
        except ArchiveError:
            return Missing()
        if stored.article.deleted is not None:
            return Missing()
        mutated = mutate(stored.article)
        try:
            result = save_article(archive, mutated, stored.version, changed_by=changed_by)
        except Conflict:
            continue
        return Updated(article=mutated, version=result.version, index_updated=result.index_updated)
    return Conflicted()


def create_article(
    archive: Archive,
    *,
    changed_by: str,
    title: str,
    collection_id: ULID,
    body: str = "",
    lifecycle: Lifecycle = Lifecycle.DRAFT,
    audience: Audience | None = None,
    ref_code: str | None = None,
    media_type: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    physical_location: str | None = None,
    media: tuple[MediaRef, ...] = (),
    date: EdtfDate | None = None,
    creator: str | None = None,
    subject_place: str | None = None,
    custom: tuple[tuple[str, str], ...] = (),
) -> CreateResult:
    article = identity.create_article(
        title=title,
        collection_id=collection_id,
        body=body,
        lifecycle=lifecycle,
        audience=audience,
        ref_code=ref_code,
        media_type=media_type,
        document_type=document_type,
        tags=tags,
        physical_location=physical_location,
        media=media,
        date=date,
        creator=creator,
        subject_place=subject_place,
        custom=custom,
    )
    new_version = archive.articles.save(article, 0, changed_by=changed_by)  # 0 = never saved
    index_updated = after_write.run(archive, after_write.SavedArticle(article.ulid))
    _enqueue_derived(article)
    return CreateResult(ulid=article.ulid, version=new_version, index_updated=index_updated)


def copy_article(archive: Archive, ulid: ULID, *, changed_by: str) -> CreateResult:
    source = archive.articles.load(ulid).article
    return create_article(
        archive,
        changed_by=changed_by,
        title=source.title,
        collection_id=source.collection_id,
        body=source.body,
        lifecycle=Lifecycle.DRAFT,  # a copy always starts as a draft (never inherits published)
        audience=source.audience,
        ref_code=None,  # Signatur cleared — unique per record (spec §7)
        media_type=source.media_type,
        document_type=source.document_type,
        tags=source.tags,
        physical_location=source.physical_location,
        media=(),  # NO media copied (spec §7)
        date=source.date,
        creator=source.creator,
        subject_place=source.subject_place,
        custom=source.custom,
    )


def delete_article(
    archive: Archive, article: Article, expected_version: Version, *, changed_by: str
) -> SaveResult:
    """Put ``article``, as stored at ``expected_version``, in the Papierkorb (ADR 0022): a save whose
    change record is the mark, reindexed and pushed like ``save_article``. A stale version raises
    ``Conflict`` before anything is written or indexed."""
    new_version = archive.articles.mark_deleted(article, expected_version, changed_by=changed_by)
    index_updated = after_write.run(archive, after_write.SavedArticle(article.ulid))
    return SaveResult(version=new_version, index_updated=index_updated)


def restore_article(
    archive: Archive, article: Article, expected_version: Version, *, changed_by: str
) -> SaveResult:
    """Take ``article``, as stored at ``expected_version``, out of the Papierkorb (ADR 0022): a
    ``save_article`` without the mark."""
    return save_article(
        archive, replace(article, deleted=None), expected_version, changed_by=changed_by
    )


def hard_delete_article(archive: Archive, ulid: ULID, expected_version: Version) -> SaveResult:
    """Delete ``ulid`` from canonical for good (ADR 0020); a stale ``expected_version`` raises
    ``Conflict``."""
    archive.articles.hard_delete(ulid, expected_version)
    index_updated = after_write.run(archive, after_write.RemovedArticle(ulid))
    return SaveResult(version=0, index_updated=index_updated)


@dataclass(frozen=True, slots=True)
class Thumbnail:
    """Render the file ``content_hash`` of Article ``ulid``."""

    ulid: ULID
    content_hash: str


@dataclass(frozen=True, slots=True)
class PageText:
    """Read the page text of Article ``ulid``'s files (ADR 0023)."""

    ulid: ULID


type DerivedJob = Thumbnail | PageText


def derived_jobs(article: Article) -> tuple[DerivedJob, ...]:
    """The jobs that derive files from ``article``'s media: a ``Thumbnail`` per file whose kind has
    a renderer, and one ``PageText`` when any file ``media_text.reads``."""
    tiles = tuple(
        Thumbnail(article.ulid, ref.content_hash)
        for ref in article.media
        if thumbnails.renders(ref)
    )
    text = (PageText(article.ulid),) if any(map(media_text.reads, article.media)) else ()
    return tiles + text


def _enqueue_derived(article: Article) -> None:
    """Enqueue ``derived_jobs(article)``, each on its own: a failed enqueue never touches the
    canonical write or skips another job. Every job is idempotent, so re-saving is harmless."""
    for job in derived_jobs(article):
        with contextlib.suppress(Exception):
            match job:
                case Thumbnail(ulid, content_hash):
                    enqueue_generate_thumbnail(ulid, content_hash)
                case PageText(ulid):
                    enqueue_extract_media_text(ulid)
                case _:
                    assert_never(job)
