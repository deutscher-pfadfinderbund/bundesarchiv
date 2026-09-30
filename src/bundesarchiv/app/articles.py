"""Article write services — the canonical-then-index shell (ADR 0013 + 0014).

Each service: write canonical through ``ArticleRepository`` (CAS — a stale ``expected_version``
raises ``Conflict``, which propagates so the view can re-render the diff), THEN synchronously
update the index for that one Article. If the synchronous index update raises, the canonical write
has ALREADY stood, so we must NOT re-raise: we enqueue a reference reindex job (retry net, ADR
0014) and return ``index_updated=False`` so the view warns that the visibility change is not yet
effective. Any other exception (e.g. ``Conflict`` from the repo) propagates untouched — the index
step is only reached after a successful canonical write.

``index_article`` and ``enqueue_reindex_article`` are imported as module-level names so the service
seam is monkeypatchable in tests (a genuine boundary): the index adapter and the worker queue.

Two entry points into that shell, and ADR 0013's split is which one you call. ``save_article`` takes
an Article plus the version the caller is betting on and lets ``Conflict`` propagate — the form path,
where losing means showing the archivist the winner. ``update_article`` takes a transform, owns the
load-mutate-save cycle, and retries onto the winner — the internal-mutation path, safe only because
the transform re-applies to whatever it is handed.
"""

import contextlib
from collections.abc import Callable

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import (
    Conflicted,
    CreateResult,
    Missing,
    SaveResult,
    Updated,
    UpdateOutcome,
)
from bundesarchiv.app.tasks import (
    enqueue_generate_thumbnail,
    enqueue_mirror_delete_article,
    enqueue_mirror_push,
    enqueue_reindex_article,
)
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
from bundesarchiv.index.indexer import SYNC_LOCK_TIMEOUT_MS, index_article
from bundesarchiv.persistence.errors import ArchiveError, Conflict

#: Filename extensions of the corpus image types we thumbnail (JPEG/PNG/TIFF), used when a MediaRef
#: carries no ``media_type``. Best-effort: the ``generate_thumbnail`` job itself no-ops on any blob
#: that isn't a decodable image, so a false positive here just enqueues a job that does nothing.
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"})


def save_article(
    archive: Archive, article: Article, expected_version: Version, *, changed_by: str
) -> SaveResult:
    """Save ``article`` (CAS at ``expected_version``) then synchronously reindex it. A stale
    version raises ``Conflict`` before anything is indexed. On index failure the canonical write
    stands, a retry job is enqueued, and ``index_updated=False`` is returned (ADR 0014)."""
    new_version = archive.articles.save(article, expected_version, changed_by=changed_by)
    index_updated = _sync_index(archive, article.ulid)
    _enqueue_thumbnails(article)
    _enqueue_mirror(enqueue_mirror_push, article.ulid)
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
    Article is absent — at the start, or hard-deleted underneath a retry.

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
    index_updated = _sync_index(archive, article.ulid)
    _enqueue_thumbnails(article)
    _enqueue_mirror(enqueue_mirror_push, article.ulid)
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


def hard_delete_article(archive: Archive, ulid: Ulid, expected_version: Version) -> SaveResult:
    """Delete the Article from canonical for good (ADR 0020) — a stale ``expected_version`` raises
    ``Conflict`` before anything is deleted — then synchronously reindex —
    ``index_article`` sees the ulid gone from canonical and DELETES its index row — and enqueue the
    delete on the system of record. On index failure the delete stands, a retry job (which will
    also drop the row) is enqueued, and ``index_updated=False`` is returned. Version is 0 (the
    Article no longer exists)."""
    archive.articles.hard_delete(ulid, expected_version)
    index_updated = _sync_index(archive, ulid)
    _enqueue_mirror(enqueue_mirror_delete_article, ulid)
    return SaveResult(version=0, index_updated=index_updated)


def _enqueue_thumbnails(article: Article) -> None:
    """Enqueue a thumbnail job for each image media reference on ``article`` (Part 4.3). Best-effort
    and out-of-band: the thumbnail is a prunable derived cache, so a failure to enqueue never affects
    the canonical write. Content-hash-keyed and idempotent, so re-saving an Article that keeps its
    media just re-enqueues harmlessly (write-once files → identical thumbnails)."""
    with contextlib.suppress(Exception):
        for ref in article.media:
            if _is_image(ref):
                enqueue_generate_thumbnail(article.ulid, ref.content_hash)


def _is_image(ref: MediaRef) -> bool:
    """Best-effort image detection for thumbnail enqueue: an ``image/*`` media_type, or (when
    media_type is absent) a known corpus image extension on the filename. The job no-ops on any blob
    that isn't a decodable image, so this only needs to avoid enqueuing obvious non-images."""
    if ref.media_type is not None:
        return ref.media_type.lower().startswith("image/")
    return any(ref.filename.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS)


def _enqueue_mirror(enqueue: Callable[[Ulid], None], ulid: Ulid) -> None:
    """Enqueue the push or the delete of the Article on the system of record (ADR 0020), AFTER the
    canonical write. Any failure is swallowed: the write stood, and the daily reconcile pushes what
    a lost push would have and reports what a lost delete left there. A no-op when no system of
    record is configured (the enqueue wrapper checks)."""
    with contextlib.suppress(Exception):
        enqueue(ulid)


def _sync_index(archive: Archive, ulid: Ulid) -> bool:
    """Synchronously reindex ``ulid``; on ANY failure enqueue a reference retry job and report
    False (never re-raise — the canonical write already stood, ADR 0014). Returns True on success.
    """
    try:
        index_article(archive.store, ulid, lock_timeout_ms=SYNC_LOCK_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — the canonical write stood; the sync index is best-effort, retry via queue
        _enqueue_reindex(ulid)
        return False
    return True


def _enqueue_reindex(ulid: Ulid) -> None:
    """Enqueue a reindex retry, swallowing failure (ADR 0014 fail-open): the periodic full rebuild
    heals the lag."""
    with contextlib.suppress(Exception):
        enqueue_reindex_article(ulid)
