from dataclasses import replace
from typing import Any

import pytest
from tests._articles import make_article

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import bulk
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.domain.models import ULID, Article, Collection
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import Conflict

ID_01A = ULID("01A")
ID_01B = ULID("01B")

# --- the field allowlist (spec §0.7, §6.3) -----------------------------------------


def test_allowlisted_fields_are_the_nine() -> None:
    assert set(bulk.ALLOWED_FIELDS) == {
        "physical_location",
        "creator",
        "subject_place",
        "media_type",
        "document_type",
        "Quelle",
        "collection_id",
        "Querverweis",
        "Besitzer",
    }


@pytest.mark.parametrize("field", ["lifecycle", "audience", "ulid", "__class__", "title"])
def test_forbidden_field_is_rejected(field: str) -> None:
    assert not bulk.is_allowed_field(field)


def test_allowed_field_accepted() -> None:
    assert bulk.is_allowed_field("physical_location")
    assert bulk.is_allowed_field("Quelle")  # a custom-bag key is allowed


# --- applying one field to one article (pure) --------------------------------------


_NO_BESTAND = CollectionChooser(lambda: ())


def _article(**over: Any) -> Article:
    return replace(make_article("01A", collection_id="C1", title="T"), **over)


def test_apply_scalar_empty_to_none() -> None:
    art = bulk.apply_field(
        _article(physical_location="Regal 4"), "physical_location", "", chooser=_NO_BESTAND
    )
    assert art.physical_location is None


def test_apply_custom_empty_removes_key() -> None:
    art = bulk.apply_field(_article(custom=(("Quelle", "alt"),)), "Quelle", "", chooser=_NO_BESTAND)
    assert "Quelle" not in dict(art.custom)


def test_apply_custom_preserves_other_keys() -> None:
    art = bulk.apply_field(
        _article(custom=(("Besitzer", "X"),)), "Quelle", "neu", chooser=_NO_BESTAND
    )
    got = dict(art.custom)
    assert got == {"Besitzer": "X", "Quelle": "neu"}


def test_apply_media_type_keeps_valid_document_type() -> None:
    art = _article(media_type="Foto(s)", document_type="Zeitschrift")
    out = bulk.apply_field(art, "media_type", "Foto(s)", chooser=_NO_BESTAND)
    assert out.document_type == "Zeitschrift"  # still valid → kept


# --- confirm-page display of the new value (spec §2 D) -----------------------------


def _chooser(*collections: Collection) -> CollectionChooser:
    return CollectionChooser(lambda: collections)


def test_field_display_value_collection_uses_name() -> None:
    # the confirm page shows the collection NAME, not the ulid (spec §2 D)
    label = bulk.field_display(
        "collection_id", "C1", _chooser(Collection(ulid=ULID("C1"), name="Fotos"))
    )
    assert label == "Fotos"


def test_field_display_value_emptied() -> None:
    assert bulk.field_display("creator", "", _chooser()) == "(geleert)"


def test_field_display_scalar() -> None:
    assert bulk.field_display("creator", "K. Meyer", _chooser()) == "K. Meyer"


# --- dependent-pair validation for Dokumenttyp-alone (spec §3) ---------------------


def test_document_type_alone_all_valid() -> None:
    types = [_article(media_type="Foto(s)"), _article(media_type="Schrifttum")]
    assert bulk.document_type_fits_all("Zeitschrift", types) is True


def test_document_type_alone_one_mismatch_rejects_all() -> None:
    types = [_article(media_type="Foto(s)"), _article(media_type=None)]
    # no Dokumenttyp belongs to a missing Medienart → the whole apply must be rejected
    assert bulk.document_type_fits_all("Zeitschrift", types) is False


# --- apply_bulk: the CAS loop + buckets against a real in-memory store (spec §4) ----
# The service seams (index + queue) are stubbed DB-free by tests/app/web/conftest.py; the canonical
# write + CAS path is REAL (in-memory ObjectStore).


def _archive_with(*articles_: Article) -> Archive:
    archive = Archive.of(InMemoryObjectStore())
    for art in articles_:
        archive.articles.save(art, 0, changed_by="tester")
    return archive


def test_apply_bulk_all_saved() -> None:
    archive = _archive_with(_article(ulid="01A"), _article(ulid="01B"))
    outcome = bulk.apply_bulk(archive, [ID_01A, ID_01B], "creator", "K. Meyer", changed_by="tester")
    assert outcome.saved == 2
    assert outcome.conflicted == ()
    assert outcome.missing == ()
    # the write actually landed
    assert archive.articles.load(ID_01A).article.creator == "K. Meyer"


def test_apply_bulk_missing_ulid_buckets() -> None:
    archive = _archive_with(_article(ulid="01A"))
    outcome = bulk.apply_bulk(
        archive, [ID_01A, ULID("01GONE")], "creator", "X", changed_by="tester"
    )
    assert outcome.saved == 1
    assert outcome.missing == ("01GONE",)


def test_apply_bulk_conflict_buckets_and_does_not_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    from bundesarchiv.app import articles

    archive = _archive_with(_article(ulid="01A", ref_code="F1"), _article(ulid="01B"))
    real_save = articles.save_article

    def _save_conflict_first(
        archive_: Archive, article: Article, version: int, *, changed_by: str
    ) -> object:
        if article.ulid == "01A":
            raise Conflict("raced")
        return real_save(archive_, article, version, changed_by=changed_by)

    monkeypatch.setattr(articles, "save_article", _save_conflict_first)
    outcome = bulk.apply_bulk(archive, [ID_01A, ID_01B], "creator", "Y", changed_by="tester")
    assert outcome.saved == 1  # 01B saved
    assert [r.ulid for r in outcome.conflicted] == ["01A"]
    assert outcome.conflicted[0].ref_code == "F1"  # the .c-sig mark rides the row
    assert archive.articles.load(ID_01B).article.creator == "Y"  # 01B not aborted


def test_apply_bulk_property_every_ulid_in_exactly_one_bucket() -> None:
    # saved + conflicted + missing == distinct selection (spec §4 property). Duplicates collapse.
    archive = _archive_with(_article(ulid="01A"), _article(ulid="01B"))
    outcome = bulk.apply_bulk(
        archive,
        [ID_01A, ID_01B, ID_01A, ULID("01GONE")],
        "subject_place",
        "Kassel",
        changed_by="tester",
    )
    distinct = len({"01A", "01B", "01GONE"})
    assert outcome.saved + len(outcome.conflicted) + len(outcome.missing) == distinct


def test_apply_bulk_media_type_reports_doctype_cleared() -> None:
    archive = _archive_with(_article(ulid="01A", media_type="Schrifttum", document_type="Brief"))
    outcome = bulk.apply_bulk(archive, [ID_01A], "media_type", "Foto(s)", changed_by="tester")
    assert outcome.saved == 1
    assert [r.ulid for r in outcome.doctype_cleared] == ["01A"]
    stored = archive.articles.load(ID_01A).article
    assert stored.media_type == "Foto(s)"
    assert stored.document_type is None
