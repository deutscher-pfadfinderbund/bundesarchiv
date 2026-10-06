"""The cataloging-form controlled vocabulary + the display spellings (Part 4.7, spec §3/§4).

Pure presentation helpers:

- ``MEDIENART_DOKUMENTTYP`` behind ``document_types_for`` / ``is_valid_pair`` — the archivists'
  vocabulary. The legacy lists are pinned verbatim here (a silent edit to a Medienart the legacy
  archive already uses would orphan records); the pair rule itself is proven against a NARROWED
  vocabulary, because every Medienart currently offers the full Dokumenttyp list.
- ``datierung_parts`` / ``human_size`` — how the article page spells a date and the edit form a
  file size.
"""

import pytest

from bundesarchiv.app.web import vocab
from bundesarchiv.domain.access import VisibilityPreview
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.index.query import FileKind

#: The Medienart ``narrowed_vocabulary`` narrows, and the single Dokumenttyp it leaves it.
_NARROWED_MEDIA_TYPE = "Foto(s)"
_NARROWED_DOCUMENT_TYPE = "Lagerheft"


@pytest.fixture
def narrowed_vocabulary(monkeypatch: pytest.MonkeyPatch) -> str:
    """Narrow ONE Medienart to a single Dokumenttyp and return its name.

    The vocabulary is data the archivists own; today every Medienart offers the whole Dokumenttyp
    list, so the pair rule has no pair left to refuse. This supplies the narrowed vocabulary the
    rule exists for, keeping it proven against the day the archivists narrow for real.
    """
    monkeypatch.setitem(
        vocab.MEDIA_TYPE_DOCUMENT_TYPES, _NARROWED_MEDIA_TYPE, (_NARROWED_DOCUMENT_TYPE,)
    )
    return _NARROWED_MEDIA_TYPE


# --- the Medienart -> Dokumenttyp mapping ------------------------------------------

#: The legacy archive's 17 Medienarten, verbatim and in legacy order.
_LEGACY_MEDIA_TYPES = (
    "Audiodatei",
    "Buch",
    "CD / DVD",
    "Dia(s)",
    "Fahne / Wimpel",
    "Filmspule",
    "Foto(s)",
    "Gegenstand",
    "Kassette",
    "Schallplatte",
    "Schrifttum",
    "Sonstiges",
    "Stempel",
    "Tonband",
    "VHS",
    "Videodatei",
    "Wappen und Zeichen",
)

#: The legacy archive's 16 Dokumenttypen, verbatim and in legacy (lookup-table) order.
_LEGACY_DOCUMENT_TYPES = (
    "Adressverzeichnis",
    "Chronik / Dokumentation",
    "Fahrtenbericht",
    "Kalender",
    "Lagerheft",
    "Lebensbericht",
    "Liederbuch",
    "Ordnung",
    "Protokoll",
    "Reden",
    "Schöpferisches (Gedicht, Lieder, ...)",
    "Schriftwechsel",
    "Sonstiges",
    "Zeitschrift",
    "Zeitungsartikel",
    "Urkunde",
)


def test_media_types_are_the_legacy_vocabulary_verbatim() -> None:
    assert vocab.media_types() == _LEGACY_MEDIA_TYPES


def test_document_types_are_the_legacy_vocabulary_verbatim() -> None:
    assert vocab.DOCUMENT_TYPES == _LEGACY_DOCUMENT_TYPES


def test_every_media_type_offers_the_whole_document_type_list() -> None:
    # Narrowing is the archivists' call, not ours (deliverable 1): until they make it, no Medienart
    # hides a Dokumenttyp, so no legacy record can arrive at a pair the form would refuse.
    for media_type in vocab.media_types():
        assert vocab.document_types_for(media_type) == _LEGACY_DOCUMENT_TYPES


def test_document_types_for_unknown_media_type_is_empty() -> None:
    assert vocab.document_types_for("gibt-es-nicht") == ()
    assert vocab.document_types_for("") == ()


def test_is_valid_pair_accepts_a_type_belonging_to_its_media_type() -> None:
    for media_type, types in vocab.MEDIA_TYPE_DOCUMENT_TYPES.items():
        for document_type in types:
            assert vocab.is_valid_pair(media_type, document_type)


def test_is_valid_pair_rejects_a_type_the_media_type_does_not_offer(
    narrowed_vocabulary: str,
) -> None:
    # The pair rule is a real gate, not a vacuous True: against a narrowed Medienart a foreign
    # Dokumenttyp is refused.
    offered = vocab.document_types_for(narrowed_vocabulary)
    foreign = next(t for t in vocab.DOCUMENT_TYPES if t not in offered)
    assert not vocab.is_valid_pair(narrowed_vocabulary, foreign)


def test_is_valid_pair_allows_no_document_type() -> None:
    # "kein Dokumenttyp" (None) is always valid — the field is optional.
    for media_type in vocab.media_types():
        assert vocab.is_valid_pair(media_type, None)


def test_is_valid_pair_rejects_a_document_type_without_a_media_type() -> None:
    # A Dokumenttyp with no Medienart is a mismatched pair (no media type owns it).
    assert not vocab.is_valid_pair(None, "Zeitschrift")


def test_grouped_options_are_one_group_while_every_media_type_shares_one_list() -> None:
    # 17 identical optgroups would be noise in the no-JS baseline; one group carries the same choices.
    groups = vocab.grouped_document_type_options()
    assert len(groups) == 1
    label, options = groups[0]
    assert label == vocab.ALL_MEDIA_TYPES
    assert options == tuple((t, t) for t in _LEGACY_DOCUMENT_TYPES)


def test_grouped_options_are_per_media_type_once_one_is_narrowed(narrowed_vocabulary: str) -> None:
    groups = vocab.grouped_document_type_options()
    assert len(groups) == len(vocab.media_types())
    assert dict(groups)[narrowed_vocabulary] == tuple(
        (t, t) for t in vocab.document_types_for(narrowed_vocabulary)
    )


# --- the origin line's date and a file's size --------------------------------------


@pytest.mark.parametrize(
    ("edtf", "expected"),
    [
        ("1962", (("1962", "1962"),)),
        ("1962-07", (("Juli 1962", "1962-07"),)),
        ("1962-07-05", (("5. Juli 1962", "1962-07-05"),)),
        ("1963~", (("um 1963", "1963"),)),  # the qualifier in words, not in the datetime
        ("1963?", (("1963?", "1963"),)),
        ("1958-07%", (("um Juli 1958?", "1958-07"),)),
        (
            "1984-11-26/1995-03-14",
            (("26. November 1984", "1984-11-26"), ("14. März 1995", "1995-03-14")),
        ),
        ("197X", (("1970er", ""),)),  # a decade is no HTML date
        ("19XX", (("1900\N{EN DASH}1999", ""),)),
        ("1962-22", (("Sommer 1962", ""),)),  # nor is a season
        ("1965/..", (("1965", "1965"), ("…", ""))),  # an open end has none
    ],
)
def test_date_parts_speak_german_and_carry_a_datetime_only_where_html_has_one(
    edtf: str, expected: tuple[tuple[str, str], ...]
) -> None:
    assert tuple((p.text, p.datetime) for p in vocab.date_parts(EdtfDate(edtf))) == expected


def test_date_parts_of_no_date_are_empty() -> None:
    assert vocab.date_parts(None) == ()


@pytest.mark.parametrize(
    ("byte_size", "expected"),
    [(None, ""), (512, "512 B"), (1536, "1,5 KB"), (1288490189, "1,2 GB")],
)
def test_human_size_is_german(byte_size: int | None, expected: str) -> None:
    assert vocab.human_size(byte_size) == expected


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ((), ""),
        (((FileKind.IMAGE, 1),), "Foto"),
        (((FileKind.IMAGE, 2),), "2 Fotos"),
        (((FileKind.PDF, 1),), "PDF"),
        (((FileKind.IMAGE, 1), (FileKind.PDF, 1)), "Foto, PDF"),
        (((FileKind.IMAGE, 3), (FileKind.PDF, 2), (FileKind.OTHER, 1)), "3 Fotos, 2 PDF, Datei"),
    ],
)
def test_file_summary_names_what_a_record_has(
    counts: tuple[tuple[FileKind, int], ...], expected: str
) -> None:
    assert vocab.file_summary(counts) == expected


@pytest.mark.parametrize(
    ("number", "expected"), [(0, "0"), (999, "999"), (2506, "2.506"), (1234567, "1.234.567")]
)
def test_count_groups_thousands_with_a_dot(number: int, expected: str) -> None:
    assert vocab.count(number) == expected


# --- the exposure statement ---------------------------------------------------------


@pytest.mark.parametrize(
    ("public", "members", "groups", "expected"),
    [
        (True, True, (), "Öffentlich"),
        (False, True, (), "Alle Mitglieder"),
        (False, False, ("vorstand", "kasse"), "Gruppe: vorstand, kasse"),
        (False, False, (), "Niemand (kein Bestand-Zugriff)"),
    ],
)
def test_exposure_label_names_the_widest_rung(
    public: bool, members: bool, groups: tuple[str, ...], expected: str
) -> None:
    result = VisibilityPreview(public, members, groups)
    assert vocab.exposure_label(result) == expected


@pytest.mark.parametrize(
    ("public", "members", "groups", "expected"),
    [
        (True, True, (), "Nach dem Veröffentlichen ist dieser Artikel öffentlich."),
        (False, True, (), "Nach dem Veröffentlichen sehen alle Mitglieder diesen Artikel."),
        (
            False,
            False,
            ("vorstand",),
            "Nach dem Veröffentlichen sehen nur Mitglieder der Gruppe vorstand diesen Artikel.",
        ),
        (
            False,
            False,
            ("vorstand", "kasse"),
            (
                "Nach dem Veröffentlichen sehen nur Mitglieder der Gruppen vorstand, kasse diesen "
                "Artikel."
            ),
        ),
        (
            False,
            False,
            (),
            "Nach dem Veröffentlichen sieht niemand außer dem Archiv diesen Artikel.",
        ),
    ],
)
def test_publish_statement_says_who_will_see_the_record(
    public: bool, members: bool, groups: tuple[str, ...], expected: str
) -> None:
    result = VisibilityPreview(public, members, groups)
    assert vocab.publish_statement(result) == expected
