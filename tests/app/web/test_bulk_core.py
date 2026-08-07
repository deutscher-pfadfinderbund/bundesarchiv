"""apply_bulk's two write-time guards (spec §4, Task 9): a pair re-check against the
FRESHLY-LOADED media_type (TOCTOU close) and a catch-all for non-``Conflict`` ``ArchiveError`` on
save (no mid-loop abort). Both bucket the affected ulid as ``conflicted`` and write nothing to it,
while the loop still lands every OTHER distinct ulid in its bucket (spec §4 property).
"""

import pytest

from bundesarchiv.app import articles
from bundesarchiv.app.web import bulk
from bundesarchiv.domain.models import Article
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.repository import ArticleRepository


def _article(**over: object) -> Article:
    base: dict[str, object] = {"ulid": "01A", "title": "T", "collection_id": "C1"}
    base.update(over)
    return Article(**base)  # type: ignore[arg-type]


def _store_with(*articles_: Article) -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    repo = ArticleRepository(store)
    for art in articles_:
        repo.save(art, 0)
    return store


def test_apply_bulk_document_type_rechecks_pair_against_fresh_media_type() -> None:
    # 01A's media_type changed to Fotografie (no "Brief") AFTER the confirm-page load validated
    # "Brief" against the STALE Schriftgut. apply_bulk re-loads fresh at apply time and must
    # re-check the pair itself — a stale-view mismatch is a concurrent-modification loss, bucketed
    # conflicted, nothing written. 01B still has a fitting media_type and must still save.
    store = _store_with(
        _article(ulid="01A", media_type="Fotografie"),
        _article(ulid="01B", media_type="Schriftgut"),
    )
    outcome = bulk.apply_bulk(store, ["01A", "01B"], "document_type", "Brief")
    assert [r.ulid for r in outcome.conflicted] == ["01A"]
    assert outcome.saved == 1
    a = ArticleRepository(store).load("01A").article
    assert a.document_type is None  # nothing written — pair stayed valid
    assert ArticleRepository(store).load("01B").article.document_type == "Brief"


def test_apply_bulk_non_conflict_archive_error_buckets_and_does_not_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-Conflict ArchiveError at save time (e.g. media not stored) must not escape mid-loop —
    # the documented invariant is every distinct ulid lands in a bucket, never a 500. 01A's save
    # is forced to raise plain ArchiveError; 01B must still save.
    store = _store_with(_article(ulid="01A", ref_code="F1"), _article(ulid="01B"))
    real_save = articles.save_article

    def _save_error_first(store_: object, article: Article, version: int) -> object:
        if article.ulid == "01A":
            raise ArchiveError("media not stored before save")
        return real_save(store_, article, version)  # type: ignore[arg-type]

    monkeypatch.setattr(articles, "save_article", _save_error_first)
    outcome = bulk.apply_bulk(store, ["01A", "01B"], "creator", "Y")
    assert outcome.saved == 1  # 01B saved
    assert [r.ulid for r in outcome.conflicted] == ["01A"]
    assert outcome.conflicted[0].ref_code == "F1"
    assert ArticleRepository(store).load("01B").article.creator == "Y"


def test_apply_bulk_property_holds_across_pair_mismatch_and_archive_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # saved + conflicted + missing == distinct auswahl even with both new guards firing at once.
    from bundesarchiv.app import articles as articles_mod

    store = _store_with(
        _article(ulid="01A", media_type="Fotografie"),  # pair mismatch on document_type apply
        _article(ulid="01B", media_type="Schriftgut"),  # saves fine
        _article(ulid="01C", media_type="Schriftgut"),  # forced ArchiveError on save
    )
    real_save = articles_mod.save_article

    def _save_error_for_c(store_: object, article: Article, version: int) -> object:
        if article.ulid == "01C":
            raise ArchiveError("media not stored before save")
        return real_save(store_, article, version)  # type: ignore[arg-type]

    monkeypatch.setattr(articles_mod, "save_article", _save_error_for_c)
    outcome = bulk.apply_bulk(store, ["01A", "01B", "01C", "01GONE"], "document_type", "Brief")
    distinct = len({"01A", "01B", "01C", "01GONE"})
    assert outcome.saved + len(outcome.conflicted) + len(outcome.missing) == distinct
    assert outcome.saved == 1
    assert {r.ulid for r in outcome.conflicted} == {"01A", "01C"}
    assert outcome.missing == ("01GONE",)
