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

#: The Medienart ``narrowed_vocabulary`` narrows, and the single Dokumenttyp it leaves it.
_NARROWED_MEDIENART = "Foto(s)"
_NARROWED_DOKUMENTTYP = "Lagerheft"


@pytest.fixture
def narrowed_vocabulary(monkeypatch: pytest.MonkeyPatch) -> str:
    """Narrow ONE Medienart to a single Dokumenttyp and return its name.

    The vocabulary is data the archivists own; today every Medienart offers the whole Dokumenttyp
    list, so the pair rule has no pair left to refuse. This supplies the narrowed vocabulary the
    rule exists for, keeping it proven against the day the archivists narrow for real.
    """
    monkeypatch.setitem(vocab.MEDIENART_DOKUMENTTYP, _NARROWED_MEDIENART, (_NARROWED_DOKUMENTTYP,))
    return _NARROWED_MEDIENART


# --- the Medienart -> Dokumenttyp mapping ------------------------------------------

#: The legacy archive's 17 Medienarten, verbatim and in legacy order.
_LEGACY_MEDIENARTEN = (
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
_LEGACY_DOKUMENTTYPEN = (
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


def test_medienarten_are_the_legacy_vocabulary_verbatim() -> None:
    assert vocab.media_types() == _LEGACY_MEDIENARTEN


def test_dokumenttypen_are_the_legacy_vocabulary_verbatim() -> None:
    assert vocab.DOKUMENTTYPEN == _LEGACY_DOKUMENTTYPEN


def test_every_medienart_offers_the_whole_document_type_list() -> None:
    # Narrowing is the archivists' call, not ours (deliverable 1): until they make it, no Medienart
    # hides a Dokumenttyp, so no legacy record can arrive at a pair the form would refuse.
    for media_type in vocab.media_types():
        assert vocab.document_types_for(media_type) == _LEGACY_DOKUMENTTYPEN


def test_document_types_for_unknown_media_type_is_empty() -> None:
    assert vocab.document_types_for("gibt-es-nicht") == ()
    assert vocab.document_types_for("") == ()


def test_is_valid_pair_accepts_a_type_belonging_to_its_media_type() -> None:
    for media_type, types in vocab.MEDIENART_DOKUMENTTYP.items():
        for document_type in types:
            assert vocab.is_valid_pair(media_type, document_type)


def test_is_valid_pair_rejects_a_type_the_medienart_does_not_offer(
    narrowed_vocabulary: str,
) -> None:
    # The pair rule is a real gate, not a vacuous True: against a narrowed Medienart a foreign
    # Dokumenttyp is refused.
    offered = vocab.document_types_for(narrowed_vocabulary)
    foreign = next(t for t in vocab.DOKUMENTTYPEN if t not in offered)
    assert not vocab.is_valid_pair(narrowed_vocabulary, foreign)


def test_is_valid_pair_allows_no_document_type() -> None:
    # "kein Dokumenttyp" (None) is always valid — the field is optional.
    for media_type in vocab.media_types():
        assert vocab.is_valid_pair(media_type, None)


def test_is_valid_pair_rejects_a_document_type_without_a_media_type() -> None:
    # A Dokumenttyp with no Medienart is a mismatched pair (no media type owns it).
    assert not vocab.is_valid_pair(None, "Zeitschrift")


def test_grouped_options_are_one_group_while_every_medienart_shares_one_list() -> None:
    # 17 identical optgroups would be noise in the no-JS baseline; one group carries the same choices.
    groups = vocab.grouped_document_type_options()
    assert len(groups) == 1
    label, options = groups[0]
    assert label == vocab.ALLE_MEDIENARTEN
    assert options == tuple((t, t) for t in _LEGACY_DOKUMENTTYPEN)


def test_grouped_options_are_per_medienart_once_one_is_narrowed(narrowed_vocabulary: str) -> None:
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
        ("1962-07", (("1962-07", "1962-07"),)),
        ("1962-07-15", (("1962-07-15", "1962-07-15"),)),
        ("1963~", (("1963~", "1963"),)),  # the qualifier stays in the text, not in the datetime
        ("1958-07%", (("1958-07%", "1958-07"),)),
        ("1984-11-26/1995-03-14", (("1984-11-26", "1984-11-26"), ("1995-03-14", "1995-03-14"))),
        ("197X", (("197X", ""),)),  # a decade is no HTML date
        ("1962-21", (("1962-21", ""),)),  # nor is a season
        ("1965/..", (("1965", "1965"), ("..", ""))),  # an open end has none
    ],
)
def test_datierung_parts_carry_a_datetime_only_where_html_has_one(
    edtf: str, expected: tuple[tuple[str, str], ...]
) -> None:
    assert tuple((p.text, p.datetime) for p in vocab.datierung_parts(EdtfDate(edtf))) == expected


def test_datierung_parts_of_no_date_are_empty() -> None:
    assert vocab.datierung_parts(None) == ()


@pytest.mark.parametrize(
    ("byte_size", "expected"),
    [(None, ""), (512, "512 B"), (1536, "1,5 KB"), (1288490189, "1,2 GB")],
)
def test_human_size_is_german(byte_size: int | None, expected: str) -> None:
    assert vocab.human_size(byte_size) == expected


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
    result = VisibilityPreview(public, members, groups, frozenset())
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
    result = VisibilityPreview(public, members, groups, frozenset())
    assert vocab.publish_statement(result) == expected
