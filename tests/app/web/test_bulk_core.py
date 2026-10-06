"""apply_bulk's two write-time guards (spec §4, Task 9): a pair re-check against the
FRESHLY-LOADED media_type (TOCTOU close) and a catch-all for non-``Conflict`` ``ArchiveError`` on
save (no mid-loop abort). Both bucket the affected ulid as ``conflicted`` and write nothing to it,
while the loop still lands every OTHER distinct ulid in its bucket (spec §4 property).
"""

import pytest

from bundesarchiv.app import articles
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import bulk
from bundesarchiv.domain.models import Article
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import ArchiveError


def _article(**over: object) -> Article:
    base: dict[str, object] = {"ulid": "01A", "title": "T", "collection_id": "C1"}
    base.update(over)
    return Article(**base)  # type: ignore[arg-type]


def _archive_with(*articles_: Article) -> Archive:
    archive = Archive.of(InMemoryObjectStore())
    for art in articles_:
        archive.articles.save(art, 0, changed_by="tester")
    return archive


def test_apply_bulk_document_type_rechecks_pair_against_fresh_media_type() -> None:
    # 01A's Medienart was CLEARED after the confirm-page load validated the Dokumenttyp against
    # the stale one, and no Dokumenttyp belongs to a missing Medienart. apply_bulk re-loads fresh and must
    # re-check the pair itself — a stale-view mismatch is a concurrent-modification loss, bucketed
    # conflicted, nothing written. 01B still has a fitting media_type and must still save.
    archive = _archive_with(
        _article(ulid="01A", media_type=None),
        _article(ulid="01B", media_type="Schrifttum"),
    )
    outcome = bulk.apply_bulk(
        archive, ["01A", "01B"], "document_type", "Schriftwechsel", changed_by="tester"
    )
    assert [r.ulid for r in outcome.conflicted] == ["01A"]
    assert outcome.saved == 1
    a = archive.articles.load("01A").article
    assert a.document_type is None  # nothing written — pair stayed valid
    assert archive.articles.load("01B").article.document_type == "Schriftwechsel"


def test_apply_bulk_non_conflict_archive_error_buckets_and_does_not_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-Conflict ArchiveError at save time (e.g. media not stored) must not escape mid-loop —
    # the documented invariant is every distinct ulid lands in a bucket, never a 500. 01A's save
    # is forced to raise plain ArchiveError; 01B must still save.
    archive = _archive_with(_article(ulid="01A", ref_code="F1"), _article(ulid="01B"))
    real_save = articles.save_article

    def _save_error_first(
        archive_: object, article: Article, version: int, *, changed_by: str
    ) -> object:
        if article.ulid == "01A":
            raise ArchiveError("media not stored before save")
        return real_save(archive_, article, version, changed_by=changed_by)  # type: ignore[arg-type]

    monkeypatch.setattr(articles, "save_article", _save_error_first)
    outcome = bulk.apply_bulk(archive, ["01A", "01B"], "creator", "Y", changed_by="tester")
    assert outcome.saved == 1  # 01B saved
    assert [r.ulid for r in outcome.conflicted] == ["01A"]
    assert outcome.conflicted[0].ref_code == "F1"
    assert archive.articles.load("01B").article.creator == "Y"


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
        archive_: object, article: Article, version: int, *, changed_by: str
    ) -> object:
        if article.ulid == "01C":
            raise ArchiveError("media not stored before save")
        return real_save(archive_, article, version, changed_by=changed_by)  # type: ignore[arg-type]

    monkeypatch.setattr(articles_mod, "save_article", _save_error_for_c)
    outcome = bulk.apply_bulk(
        archive,
        ["01A", "01B", "01C", "01GONE"],
        "document_type",
        "Schriftwechsel",
        changed_by="tester",
    )
    distinct = len({"01A", "01B", "01C", "01GONE"})
    assert outcome.saved + len(outcome.conflicted) + len(outcome.missing) == distinct
    assert outcome.saved == 1
    assert {r.ulid for r in outcome.conflicted} == {"01A", "01C"}
    assert outcome.missing == ("01GONE",)
