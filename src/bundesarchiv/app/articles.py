"""Article write services — the canonical-then-index shell (ADR 0013 + 0014).

Each service: write canonical through ``ArticleRepository`` (CAS — a stale ``expected_version``
raises ``Conflict``, which propagates so the view can re-render the diff), THEN hand what it wrote
to ``after_write.run`` — index sync, retry fallback, mirror job, never raising — and return its
``index_updated`` so the view can warn that the visibility change is not yet effective (ADR 0014).
Only the thumbnail jobs stay here: only Article content has files to render.

Two entry points into that shell, and ADR 0013's split is which one you call. ``save_article`` takes
an Article plus the version the caller is betting on and lets ``Conflict`` propagate — the form path,
where losing means showing the archivist the winner. ``update_article`` takes a transform, owns the
load-mutate-save cycle, and retries onto the winner — the internal-mutation path, safe only because
the transform re-applies to whatever it is handed.
"""

import contextlib
from collections.abc import Callable
from dataclasses import replace

from bundesarchiv.app import after_write, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import (
    Conflicted,
    CreateResult,
    Missing,
    SaveResult,
    Updated,
    UpdateOutcome,
)
from bundesarchiv.app.tasks import enqueue_generate_thumbnail
from bundesarchiv.domain import identity
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    Lifecycle,
    MediaRef,
    Ulid,
    Version,
)
from bundesarchiv.persistence.errors import ArchiveError, Conflict


def save_article(
    archive: Archive, article: Article, expected_version: Version, *, changed_by: str
) -> SaveResult:
    """Save ``article`` (CAS at ``expected_version``) then synchronously reindex it. A stale
    version raises ``Conflict`` before anything is indexed. On index failure the canonical write
    stands, a retry job is enqueued, and ``index_updated=False`` is returned (ADR 0014)."""
    new_version = archive.articles.save(article, expected_version, changed_by=changed_by)
    index_updated = after_write.run(archive, after_write.SavedArticle(article.ulid))
    _enqueue_thumbnails(article)
    return SaveResult(version=new_version, index_updated=index_updated)


def update_article(
    archive: Archive,
    ulid: Ulid,
    mutate: Callable[[Article], Article],
    *,
    changed_by: str,
    retries: int = 3,
) -> UpdateOutcome:
    """Load the Article, apply ``mutate``, and ``save_article`` at the version just loaded, re-loading
    and re-applying on ``Conflict`` up to ``retries`` times (``retries + 1`` attempts). Returns
    ``Updated`` with the saved Article, ``Conflicted`` if every attempt lost, ``Missing`` if the
    Article is absent or in the Papierkorb (ADR 0022: restore it first) — at the start, or
    underneath a retry.

    FORBIDDEN for form saves (ADR 0013): a form carries values the archivist typed against a
    now-stale Article, so a retry would silently overwrite the concurrent edit — the one unforgivable
    archive failure. ``mutate`` must be a pure, idempotent transform of whatever it is handed,
    because a retry re-applies it to the WINNER's Article; it must not add media (``add_media`` first,
    then let the transform reference the ref). Exceptions ``mutate`` raises propagate untouched: it
    may refuse a mutation the freshly-loaded state no longer admits.
    """
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
    collection_id: Ulid,
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
    """Mint a NEW Article (ULID minted by the domain factory, ADR 0006), save it at version 0,
    then synchronously index it. Mirrors ``domain.create_article``'s fields, adding the persistence
    + index wiring the view needs. Returns the new ulid so the view can redirect to it."""
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
    _enqueue_thumbnails(article)
    return CreateResult(ulid=article.ulid, version=new_version, index_updated=index_updated)


def copy_article(archive: Archive, ulid: Ulid, *, changed_by: str) -> CreateResult:
    """Copy an existing Article's METADATA into a fresh DRAFT (spec §7 Kopieren). The copy goes
    through ``create_article`` (so it mints a new ULID and indexes like any new article), carrying
    every metadata field forward EXCEPT: the Signatur (``ref_code`` cleared — a Signatur is unique to
    one record), the media (NONE copied — series items differ; the archivist attaches fresh), and the
    lifecycle (always a new DRAFT, never inheriting the source's published state). Creates, never
    destroys — the source is untouched. Returns the new ulid so the view can 302 to its edit form."""
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


def hard_delete_article(archive: Archive, ulid: Ulid, expected_version: Version) -> SaveResult:
    """Delete the Article from canonical for good (ADR 0020) — a stale ``expected_version`` raises
    ``Conflict`` before anything is deleted — then synchronously reindex —
    ``index_article`` sees the ulid gone from canonical and DELETES its index row — and enqueue the
    delete on the system of record. On index failure the delete stands, a retry job (which will
    also drop the row) is enqueued, and ``index_updated=False`` is returned. Version is 0 (the
    Article no longer exists)."""
    archive.articles.hard_delete(ulid, expected_version)
    index_updated = after_write.run(archive, after_write.RemovedArticle(ulid))
    return SaveResult(version=0, index_updated=index_updated)


def _enqueue_thumbnails(article: Article) -> None:
    """Enqueue a thumbnail job for each media reference on ``article`` whose kind has a renderer
    (Part 4.3). Best-effort and out-of-band: the thumbnail is a prunable derived cache, so a failure
    to enqueue never affects the canonical write. Content-hash-keyed and idempotent, so re-saving an
    Article that keeps its media just re-enqueues harmlessly (write-once files → identical
    thumbnails)."""
    with contextlib.suppress(Exception):
        for ref in article.media:
            if thumbnails.renders(ref):
                enqueue_generate_thumbnail(article.ulid, ref.content_hash)
