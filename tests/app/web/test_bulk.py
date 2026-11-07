"""``bulk.FIELDS``: each field's validation, application and display as table tests, then
``apply_bulk``'s CAS loop and buckets."""

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

_CHOOSER = CollectionChooser(lambda: (Collection(ulid=ULID("C1"), name="Fotos"),))


def _article(**over: Any) -> Article:
    return replace(make_article("01A", collection_id="C1", title="T"), **over)


# --- the table (spec §0.7, §1, §6.3) -----------------------------------------------


def test_the_table_holds_the_nine_fields() -> None:
    assert set(bulk.BY_TARGET) == {
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


@pytest.mark.parametrize("key", ["Quelle", "Querverweis", "Besitzer"])
def test_a_custom_bag_field_is_labelled_by_its_key(key: str) -> None:
    assert bulk.BY_TARGET[key].label == key


# --- validate: the refusal of a value against the selection (spec §2 C, §3) ---------

_FOTO = _article(media_type="Foto(s)")
_NO_MEDIA = _article(media_type=None)


@pytest.mark.parametrize(
    ("target", "value", "selected", "refuses"),
    [
        ("creator", "", [_FOTO], False),
        ("Quelle", "x", [_FOTO], False),
        ("media_type", "Foto(s)", [_NO_MEDIA], False),
        ("media_type", " Foto(s) ", [_NO_MEDIA], False),
        ("media_type", "", [_FOTO], True),
        ("media_type", "Quatsch", [_FOTO], True),
        ("collection_id", "C1", [_FOTO], False),
        ("collection_id", "", [_FOTO], True),
        ("collection_id", "NOPE", [_FOTO], True),
        ("document_type", "Zeitschrift", [_FOTO, _article(media_type="Schrifttum")], False),
        # no Dokumenttyp belongs to a missing Medienart: one misfit refuses the whole apply
        ("document_type", "Zeitschrift", [_FOTO, _NO_MEDIA], True),
        ("document_type", " Zeitschrift ", [_NO_MEDIA], True),
        ("document_type", "", [_NO_MEDIA], False),
    ],
)
def test_validate(target: str, value: str, selected: list[Article], refuses: bool) -> None:
    refusal = bulk.BY_TARGET[target].validate(value, selected, _CHOOSER)
    assert (refusal is not None) is refuses


def test_a_refused_dokumenttyp_is_named_in_its_refusal() -> None:
    refusal = bulk.BY_TARGET["document_type"].validate(" Zeitschrift ", [_NO_MEDIA], _CHOOSER)
    assert refusal is not None
    assert "Zeitschrift" in refusal


# --- apply: one value onto one Article (pure) --------------------------------------


@pytest.mark.parametrize(
    ("target", "before", "value", "after"),
    [
        ("physical_location", {}, " Regal 4 ", {"physical_location": "Regal 4"}),
        ("physical_location", {"physical_location": "Regal 4"}, "", {"physical_location": None}),
        ("creator", {"creator": "Alt"}, "K. Meyer", {"creator": "K. Meyer"}),
        ("subject_place", {"subject_place": "Kassel"}, "  ", {"subject_place": None}),
        (
            "Quelle",
            {"custom": (("Besitzer", "X"),)},
            "neu",
            {"custom": (("Besitzer", "X"), ("Quelle", "neu"))},
        ),
        ("Quelle", {"custom": (("Quelle", "alt"),)}, "", {"custom": ()}),
        ("Besitzer", {}, " „ä“ ", {"custom": (("Besitzer", "„ä“"),)}),
        ("collection_id", {}, " C1 ", {"collection_id": "C1"}),
        (
            "document_type",
            {"media_type": "Foto(s)"},
            "Zeitschrift",
            {"document_type": "Zeitschrift"},
        ),
        ("document_type", {"document_type": "Zeitschrift"}, "", {"document_type": None}),
        # a Dokumenttyp the new Medienart still admits is kept, one it does not is cleared (spec §3)
        (
            "media_type",
            {"media_type": "Schrifttum", "document_type": "Zeitschrift"},
            "Foto(s)",
            {"media_type": "Foto(s)", "document_type": "Zeitschrift"},
        ),
        (
            "media_type",
            {"media_type": "Schrifttum", "document_type": "Brief"},
            "Foto(s)",
            {"media_type": "Foto(s)", "document_type": None},
        ),
    ],
)
def test_apply(target: str, before: dict[str, Any], value: str, after: dict[str, Any]) -> None:
    article = _article(collection_id=ULID("C0"), **before)
    assert bulk.BY_TARGET[target].apply(article, value, _CHOOSER) == replace(article, **after)


@pytest.mark.parametrize(
    ("target", "before", "value", "clears"),
    [
        ("media_type", {"media_type": "Schrifttum", "document_type": "Brief"}, "Foto(s)", True),
        (
            "media_type",
            {"media_type": "Schrifttum", "document_type": "Zeitschrift"},
            "Foto(s)",
            False,
        ),
        ("media_type", {"media_type": "Schrifttum"}, "Foto(s)", False),
        ("document_type", {"media_type": "Foto(s)", "document_type": "Zeitschrift"}, "", False),
        ("creator", {"document_type": "Brief"}, "X", False),
    ],
)
def test_clears_document_type(
    target: str, before: dict[str, Any], value: str, clears: bool
) -> None:
    assert bulk.BY_TARGET[target].clears_document_type(_article(**before), value) is clears


# --- display: what the check and result pages show (spec §2 D) ---------------------


@pytest.mark.parametrize(
    ("target", "value", "shown"),
    [
        ("collection_id", "C1", "Fotos"),
        ("collection_id", "GONE", "GONE"),
        ("creator", "K. Meyer", "K. Meyer"),
    ],
)
def test_the_new_value_shown(target: str, value: str, shown: str) -> None:
    assert bulk.BY_TARGET[target].shown_new(value, _CHOOSER) == shown


@pytest.mark.parametrize("target", ["creator", "Quelle"])
def test_a_blank_new_value_is_shown_as_emptied_not_verbatim(target: str) -> None:
    field = bulk.BY_TARGET[target]
    assert field.shown_new(" ", _CHOOSER) == field.shown_new("", _CHOOSER) not in {"", " "}


@pytest.mark.parametrize(
    ("target", "before", "shown"),
    [
        ("collection_id", {}, "Fotos"),
        ("creator", {"creator": "Alt-Autor"}, "Alt-Autor"),
        ("creator", {}, ""),
        ("Quelle", {"custom": (("Quelle", "Alt-Quelle"),)}, "Alt-Quelle"),
        ("Besitzer", {"custom": (("Quelle", "Alt-Quelle"),)}, ""),
        ("media_type", {"media_type": "Foto(s)"}, "Foto(s)"),
    ],
)
def test_the_value_it_replaces_shown(target: str, before: dict[str, Any], shown: str) -> None:
    assert bulk.BY_TARGET[target].shown_current(_article(**before), _CHOOSER) == shown


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
    outcome = bulk.apply_bulk(
        archive, [ID_01A, ID_01B], bulk.BY_TARGET["creator"], "K. Meyer", changed_by="tester"
    )
    assert outcome.saved == 2
    assert outcome.conflicted == ()
    assert outcome.missing == ()
    # the write actually landed
    assert archive.articles.load(ID_01A).article.creator == "K. Meyer"


def test_apply_bulk_missing_ulid_buckets() -> None:
    archive = _archive_with(_article(ulid="01A"))
    outcome = bulk.apply_bulk(
        archive, [ID_01A, ULID("01GONE")], bulk.BY_TARGET["creator"], "X", changed_by="tester"
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
    outcome = bulk.apply_bulk(
        archive, [ID_01A, ID_01B], bulk.BY_TARGET["creator"], "Y", changed_by="tester"
    )
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
        bulk.BY_TARGET["subject_place"],
        "Kassel",
        changed_by="tester",
    )
    distinct = len({"01A", "01B", "01GONE"})
    assert outcome.saved + len(outcome.conflicted) + len(outcome.missing) == distinct


def test_apply_bulk_media_type_reports_doctype_cleared() -> None:
    archive = _archive_with(_article(ulid="01A", media_type="Schrifttum", document_type="Brief"))
    outcome = bulk.apply_bulk(
        archive, [ID_01A], bulk.BY_TARGET["media_type"], "Foto(s)", changed_by="tester"
    )
    assert outcome.saved == 1
    assert [r.ulid for r in outcome.doctype_cleared] == ["01A"]
    stored = archive.articles.load(ID_01A).article
    assert stored.media_type == "Foto(s)"
    assert stored.document_type is None
