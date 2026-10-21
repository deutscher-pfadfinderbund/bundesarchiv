"""apply_bulk's two write-time guards: the pair re-checked against the freshly loaded Medienart,
and a non-Conflict ArchiveError on save."""

from dataclasses import replace
from typing import Any

import pytest

from bundesarchiv.app import articles
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import bulk
from bundesarchiv.domain.models import ULID, Article
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import ArchiveError

ID_01A = ULID("01A")
ID_01B = ULID("01B")


def _article(**over: Any) -> Article:
    base = Article(ulid=ID_01A, title="T", collection_id=ULID("C1"))
    return replace(base, **over)


def _archive_with(*articles_: Article) -> Archive:
    archive = Archive.of(InMemoryObjectStore())
    for art in articles_:
        archive.articles.save(art, 0, changed_by="tester")
    return archive


def test_apply_bulk_document_type_rechecks_pair_against_fresh_media_type() -> None:
    # 01A's Medienart was cleared after the confirm page validated against it.
    archive = _archive_with(
        _article(ulid="01A", media_type=None),
        _article(ulid="01B", media_type="Schrifttum"),
    )
    outcome = bulk.apply_bulk(
        archive, [ID_01A, ID_01B], "document_type", "Schriftwechsel", changed_by="tester"
    )
    assert [r.ulid for r in outcome.conflicted] == ["01A"]
    assert outcome.saved == 1
    a = archive.articles.load(ID_01A).article
    assert a.document_type is None  # nothing written — pair stayed valid
    assert archive.articles.load(ID_01B).article.document_type == "Schriftwechsel"


def test_apply_bulk_non_conflict_archive_error_buckets_and_does_not_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _archive_with(_article(ulid="01A", ref_code="F1"), _article(ulid="01B"))
    real_save = articles.save_article

    def _save_error_first(
        archive_: Archive, article: Article, version: int, *, changed_by: str
    ) -> object:
        if article.ulid == "01A":
            raise ArchiveError("media not stored before save")
        return real_save(archive_, article, version, changed_by=changed_by)

    monkeypatch.setattr(articles, "save_article", _save_error_first)
    outcome = bulk.apply_bulk(archive, [ID_01A, ID_01B], "creator", "Y", changed_by="tester")
    assert outcome.saved == 1  # 01B saved
    assert [r.ulid for r in outcome.conflicted] == ["01A"]
    assert outcome.conflicted[0].ref_code == "F1"
    assert archive.articles.load(ID_01B).article.creator == "Y"


def test_apply_bulk_property_holds_across_pair_mismatch_and_archive_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # saved + conflicted + missing == distinct selection even with both new guards firing at once.
    from bundesarchiv.app import articles as articles_mod

    archive = _archive_with(
        _article(ulid="01A", media_type=None),  # pair mismatch on document_type apply
        _article(ulid="01B", media_type="Schrifttum"),  # saves fine
        _article(ulid="01C", media_type="Schrifttum"),  # forced ArchiveError on save
    )
    real_save = articles_mod.save_article

    def _save_error_for_c(
        archive_: Archive, article: Article, version: int, *, changed_by: str
    ) -> object:
        if article.ulid == "01C":
            raise ArchiveError("media not stored before save")
        return real_save(archive_, article, version, changed_by=changed_by)

    monkeypatch.setattr(articles_mod, "save_article", _save_error_for_c)
    outcome = bulk.apply_bulk(
        archive,
        [ID_01A, ID_01B, ULID("01C"), ULID("01GONE")],
        "document_type",
        "Schriftwechsel",
        changed_by="tester",
    )
    distinct = len({"01A", "01B", "01C", "01GONE"})
    assert outcome.saved + len(outcome.conflicted) + len(outcome.missing) == distinct
    assert outcome.saved == 1
    assert {r.ulid for r in outcome.conflicted} == {"01A", "01C"}
    assert outcome.missing == ("01GONE",)
