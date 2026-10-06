"""The archive statistics record the reconcile logs: its fields on a tiny corpus."""

import io

import pytest

from bundesarchiv.app import stats
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository


@pytest.mark.django_db
def test_the_stats_record_and_one_record_per_media_type(
    caplog: pytest.LogCaptureFixture, tmp_path: pytest.TempPathFactory, settings: object
) -> None:
    settings.BUNDESARCHIV_THUMBNAIL_ROOT = str(tmp_path)  # type: ignore[attr-defined]
    store = InMemoryObjectStore()
    CollectionRepository(store).save(
        Collection("PUB", "Offen", audience=Audience(AudienceTier.PUBLIC)), 0, changed_by="t"
    )
    articles = ArticleRepository(store)
    pdf = articles.add_media("01A", "a.pdf", io.BytesIO(b"%PDF 1"))
    pdf2 = articles.add_media("01A", "b.pdf", io.BytesIO(b"%PDF 22"))
    articles.save(
        Article(
            "01A",
            "Mit",
            "PUB",
            lifecycle=Lifecycle.PUBLISHED,
            body="Text",
            tags=("x",),
            media=(pdf, pdf2),
        ),
        0,
        changed_by="t",
    )
    articles.save(Article("01B", "Ohne", "PUB"), 0, changed_by="t")  # a draft, no media
    indexer.rebuild(store)

    with caplog.at_level("INFO", logger=stats.__name__):
        stats.log_archive_stats(store)

    summary, by_type = (vars(r) for r in caplog.records)
    assert (
        summary.items()
        >= {
            "articles": 2,
            "collections": 1,
            "media_files": 2,
            "media_bytes": 13,
            "in_trash": 0,
            "articles_without_media": 1,
            "audience_public": 1,
            "audience_archivist_only": 1,
            "articles_without_date": 2,
            "articles_without_description": 1,
            "articles_without_tags": 1,
            "media_without_thumbnail": 2,
            "index_rows": 2,
            "index_drift": 0,
            "jobs_failed": 0,
        }.items()
    )
    assert (by_type["media_type"], by_type["files"], by_type["bytes"]) == ("application/pdf", 2, 13)
    assert len(caplog.records) == 2
