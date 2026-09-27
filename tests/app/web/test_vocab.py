"""The cataloging-form controlled vocabulary + the human-German date (Part 4.7, spec §3/§4).

Two pure presentation helpers the form controller reads:

- ``MEDIENART_DOKUMENTTYP`` behind ``document_types_for`` / ``is_valid_pair`` — the archivists'
  vocabulary. The legacy lists are pinned verbatim here (a silent edit to a Medienart the legacy
  archive already uses would orphan records); the pair rule itself is proven against a NARROWED
  vocabulary, because every Medienart currently offers the full Dokumenttyp list.
- ``edtf_to_german`` — the human-German date the detail page prints. It is never an error
  surface: validation errors ride the field.
"""

import pytest

from bundesarchiv.app.web import vocab
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


# --- EDTF -> German ----------------------------------------------------------------


def test_edtf_german_plain_year() -> None:
    assert vocab.edtf_to_german(EdtfDate("1962")) == "1962"


def test_edtf_german_decade() -> None:
    assert vocab.edtf_to_german(EdtfDate("197X")) == "1970er"


def test_edtf_german_approximate() -> None:
    assert vocab.edtf_to_german(EdtfDate("1970~")) == "um 1970"


def test_edtf_german_uncertain() -> None:
    assert vocab.edtf_to_german(EdtfDate("1970?")) == "1970 (unsicher)"


def test_edtf_german_interval() -> None:
    assert vocab.edtf_to_german(EdtfDate("1984/1995")) == "1984 bis 1995"


def test_edtf_german_none_is_empty() -> None:
    assert vocab.edtf_to_german(None) == ""


# --- the full §5 detail-page table (Part 4.6) --------------------------------------
# The 4.6 spec §5 table is the contract for the detail-page date presentation. The strings are
# PROVISIONAL pending owner sign-off (4.7 Q2 / 4.6 §11 Q1); this pins exactly what the helper
# produces so a phrasing change is a deliberate one-file edit here + in vocab.py. The two rows the
# controller signed off EXTENDING (month name, century phrasing) are marked below.
_EDTF_TABLE_46 = [
    ("1958", "1958"),  # plain year
    ("1958-07", "Juli 1958"),  # month name — EXTENSION (controller sign-off, §5)
    ("197X", "1970er"),  # decade
    ("19XX", "1900\N{EN DASH}1999"),  # century phrasing — EXTENSION (controller sign-off, §5)
    ("1970~", "um 1970"),  # approximate
    ("1970?", "1970 (unsicher)"),  # uncertain
    ("1970%", "1970 (unsicher, etwa)"),  # uncertain + approximate
    ("1965/1969", "1965 bis 1969"),  # closed interval
    ("1962-21", "Frühjahr 1962"),  # season
    ("1965/..", "1965/.."),  # open interval echoes verbatim
    ("../1969", "../1969"),  # open interval echoes verbatim
]


@pytest.mark.parametrize(("edtf", "expected"), _EDTF_TABLE_46)
def test_edtf_german_detail_table(edtf: str, expected: str) -> None:
    assert vocab.edtf_to_german(EdtfDate(edtf)) == expected


def test_edtf_german_approximate_month_composes() -> None:
    # a qualifier over a YYYY-MM composes with the month name (um + Juli 1958)
    assert vocab.edtf_to_german(EdtfDate("1958-07~")) == "um Juli 1958"
