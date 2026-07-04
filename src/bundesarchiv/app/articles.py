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
"""

from bundesarchiv.app.result import CreateResult, SaveResult
from bundesarchiv.app.tasks import enqueue_reindex_article
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
from bundesarchiv.index.indexer import index_article
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository


def save_article(store: ObjectStore, article: Article, expected_version: Version) -> SaveResult:
    """Save ``article`` (CAS at ``expected_version``) then synchronously reindex it. A stale
    version raises ``Conflict`` before anything is indexed. On index failure the canonical write
    stands, a retry job is enqueued, and ``index_updated=False`` is returned (ADR 0014)."""
    new_version = ArticleRepository(store).save(article, expected_version)
    index_updated = _sync_index(store, article.ulid)
    return SaveResult(version=new_version, index_updated=index_updated)


def create_article(
    store: ObjectStore,
    *,
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
    new_version = ArticleRepository(store).save(article, 0)  # 0 = never saved -> first save is v1
    index_updated = _sync_index(store, article.ulid)
    return CreateResult(ulid=article.ulid, version=new_version, index_updated=index_updated)


def hard_delete_article(store: ObjectStore, ulid: Ulid) -> SaveResult:
    """Hard-delete the Article from canonical (recoverable trash, ADR 0005), then synchronously
    reindex — ``index_article`` sees the ulid gone from canonical and DELETES its index row. On
    index failure the delete stands, a retry job (which will also drop the row) is enqueued, and
    ``index_updated=False`` is returned. Version is 0 (the Article no longer exists)."""
    ArticleRepository(store).hard_delete(ulid)
    index_updated = _sync_index(store, ulid)
    return SaveResult(version=0, index_updated=index_updated)


def _sync_index(store: ObjectStore, ulid: Ulid) -> bool:
    """Synchronously reindex ``ulid``; on ANY failure enqueue a reference retry job and report
    False (never re-raise — the canonical write already stood, ADR 0014). Returns True on success.
    """
    try:
        index_article(store, ulid)
    except Exception:  # the canonical write stood; the sync index is best-effort, retry via queue
        enqueue_reindex_article(ulid)
        return False
    return True
