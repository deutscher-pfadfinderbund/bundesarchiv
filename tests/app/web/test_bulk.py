"""The pure bulk-edit layer (Sammelbearbeitung, spec §0/§1/§3/§4).

``bulk`` is IO-free where it can be (the field allowlist, the per-article field application, the
dependent-pair validation) and wraps the ONE bulk Conflict catch (``apply_bulk``) around the real
``save_article`` service. The leak-sensitive contract (spec §6) is pinned here: an unknown ``feld``
mutates nothing; a Dokumenttyp that mismatches any article's current Medienart rejects the WHOLE
apply (all-or-nothing, fail-closed); every distinct auswahl ulid lands in exactly one outcome
bucket (property); a Conflict is bucketed, never retried, never aborts the loop.
"""

import pytest

from bundesarchiv.app.web import bulk
from bundesarchiv.domain.models import Article
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import Conflict
from bundesarchiv.persistence.repository import ArticleRepository

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


@pytest.mark.parametrize(
    "feld", ["lifecycle", "audience", "ulid", "__class__", "title", "sichtbarkeit"]
)
def test_forbidden_field_is_rejected(feld: str) -> None:
    assert not bulk.is_allowed_field(feld)


def test_allowed_field_accepted() -> None:
    assert bulk.is_allowed_field("physical_location")
    assert bulk.is_allowed_field("Quelle")  # a custom-bag key is allowed


# --- applying one field to one article (pure) --------------------------------------


def _article(**over: object) -> Article:
    base: dict[str, object] = {"ulid": "01A", "title": "T", "collection_id": "C1"}
    base.update(over)
    return Article(**base)  # type: ignore[arg-type]


def test_apply_scalar_empty_to_none() -> None:
    art = bulk.apply_field(_article(physical_location="Regal 4"), "physical_location", "")
    assert art.physical_location is None


def test_apply_scalar_value() -> None:
    art = bulk.apply_field(_article(), "creator", "K. Meyer")
    assert art.creator == "K. Meyer"


def test_apply_custom_upsert() -> None:
    art = bulk.apply_field(_article(), "Quelle", "Nachlass Meyer")
    assert dict(art.custom)["Quelle"] == "Nachlass Meyer"


def test_apply_custom_empty_removes_key() -> None:
    art = bulk.apply_field(_article(custom=(("Quelle", "alt"),)), "Quelle", "")
    assert "Quelle" not in dict(art.custom)


def test_apply_custom_preserves_other_keys() -> None:
    art = bulk.apply_field(_article(custom=(("Besitzer", "X"),)), "Quelle", "neu")
    got = dict(art.custom)
    assert got == {"Besitzer": "X", "Quelle": "neu"}


def test_apply_media_type_clears_orphaned_document_type() -> None:
    # Fotografie has no "Brief"; setting Medienart to Fotografie when doc_type is a Schriftgut type
    # clears the now-invalid document_type (spec §3).
    art = _article(media_type="Schriftgut", document_type="Brief")
    out = bulk.apply_field(art, "media_type", "Fotografie")
    assert out.media_type == "Fotografie"
    assert out.document_type is None


def test_apply_media_type_keeps_valid_document_type() -> None:
    art = _article(media_type="Fotografie", document_type="Porträt")
    out = bulk.apply_field(art, "media_type", "Fotografie")
    assert out.document_type == "Porträt"  # still valid → kept


# --- confirm-page display of the new value (spec §2 D) -----------------------------


def test_field_display_value_collection_uses_name() -> None:
    # the confirm page shows the collection NAME, not the ulid (spec §2 D)
    label = bulk.field_display("collection_id", "C1", {"C1": "Fotos"})
    assert label == "Fotos"


def test_field_display_value_emptied() -> None:
    assert bulk.field_display("creator", "", {}) == "(geleert)"


def test_field_display_scalar() -> None:
    assert bulk.field_display("creator", "K. Meyer", {}) == "K. Meyer"


# --- dependent-pair validation for Dokumenttyp-alone (spec §3) ---------------------


def test_document_type_alone_all_valid() -> None:
    arts = [_article(media_type="Fotografie"), _article(media_type="Fotografie")]
    assert bulk.document_type_fits_all("Porträt", arts) is True


def test_document_type_alone_one_mismatch_rejects_all() -> None:
    arts = [_article(media_type="Fotografie"), _article(media_type="Schriftgut")]
    # Porträt fits Fotografie but not Schriftgut → whole apply must be rejected
    assert bulk.document_type_fits_all("Porträt", arts) is False


# --- apply_bulk: the CAS loop + buckets against a real in-memory store (spec §4) ----
# The service seams (index + queue) are stubbed DB-free by tests/app/web/conftest.py; the canonical
# write + CAS path is REAL (in-memory ObjectStore).


def _store_with(*articles_: Article) -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    repo = ArticleRepository(store)
    for art in articles_:
        repo.save(art, 0)
    return store


def test_apply_bulk_all_saved() -> None:
    store = _store_with(_article(ulid="01A"), _article(ulid="01B"))
    outcome = bulk.apply_bulk(store, ["01A", "01B"], "creator", "K. Meyer")
    assert outcome.saved == 2
    assert outcome.conflicted == ()
    assert outcome.missing == ()
    # the write actually landed
    assert ArticleRepository(store).load("01A").article.creator == "K. Meyer"


def test_apply_bulk_missing_ulid_buckets() -> None:
    store = _store_with(_article(ulid="01A"))
    outcome = bulk.apply_bulk(store, ["01A", "01GONE"], "creator", "X")
    assert outcome.saved == 1
    assert outcome.missing == ("01GONE",)


def test_apply_bulk_conflict_buckets_and_does_not_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force a Conflict on the FIRST ulid and prove the SECOND still saves (partial durability, spec
    # §8). save_article is patched to conflict for 01A, else delegate to the real service.
    from bundesarchiv.app import articles

    store = _store_with(_article(ulid="01A", ref_code="F1"), _article(ulid="01B"))
    real_save = articles.save_article

    def _save_conflict_first(store_: object, article: Article, version: int) -> object:
        if article.ulid == "01A":
            raise Conflict("raced")
        return real_save(store_, article, version)  # type: ignore[arg-type]

    monkeypatch.setattr(articles, "save_article", _save_conflict_first)
    outcome = bulk.apply_bulk(store, ["01A", "01B"], "creator", "Y")
    assert outcome.saved == 1  # 01B saved
    assert [r.ulid for r in outcome.conflicted] == ["01A"]
    assert outcome.conflicted[0].ref_code == "F1"  # the .c-sig mark rides the row
    assert ArticleRepository(store).load("01B").article.creator == "Y"  # 01B not aborted


def test_apply_bulk_property_every_ulid_in_exactly_one_bucket() -> None:
    # saved + conflicted + missing == distinct auswahl (spec §4 property). Duplicates collapse.
    store = _store_with(_article(ulid="01A"), _article(ulid="01B"))
    outcome = bulk.apply_bulk(store, ["01A", "01B", "01A", "01GONE"], "subject_place", "Kassel")
    distinct = len({"01A", "01B", "01GONE"})
    assert outcome.saved + len(outcome.conflicted) + len(outcome.missing) == distinct


def test_apply_bulk_media_type_reports_doctype_cleared() -> None:
    store = _store_with(_article(ulid="01A", media_type="Schriftgut", document_type="Brief"))
    outcome = bulk.apply_bulk(store, ["01A"], "media_type", "Fotografie")
    assert outcome.saved == 1
    assert [r.ulid for r in outcome.doctype_cleared] == ["01A"]
    stored = ArticleRepository(store).load("01A").article
    assert stored.media_type == "Fotografie"
    assert stored.document_type is None
