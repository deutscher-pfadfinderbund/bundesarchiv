"""The cataloging-form controlled vocabulary + EDTF echo (Part 4.7, spec §3/§4/§5).

Two pure presentation helpers the form controller reads:

- ``MEDIENART_DOKUMENTTYP`` behind ``document_types_for`` / ``is_valid_pair`` — the fixed-in-code
  Medienart→Dokumenttyp mapping (owner Q1 v1 assumption). One accessor so the dependent-select
  render, the server-side pair re-validation, and the (later) HTMX endpoint all read one source.
- ``edtf_to_german`` — the human-German echo rendered server-side after submit (spec §5). Anything
  the EDTF value object rejects yields an empty echo (no echo while the value is unparseable), so
  the echo is never an error surface — validation errors ride the field, not the echo.
"""

from bundesarchiv.app.web import vocab
from bundesarchiv.domain.edtf import EdtfDate

# --- the Medienart -> Dokumenttyp mapping ------------------------------------------


def test_media_types_is_the_vocab_top_level() -> None:
    # Every Medienart the select offers is a key of the mapping (one source, no drift).
    assert set(vocab.media_types()) == set(vocab.MEDIENART_DOKUMENTTYP)


def test_document_types_for_a_known_media_type() -> None:
    for media_type in vocab.media_types():
        types = vocab.document_types_for(media_type)
        assert types == vocab.MEDIENART_DOKUMENTTYP[media_type]


def test_document_types_for_unknown_media_type_is_empty() -> None:
    assert vocab.document_types_for("gibt-es-nicht") == ()
    assert vocab.document_types_for("") == ()


def test_is_valid_pair_accepts_a_type_belonging_to_its_media_type() -> None:
    for media_type, types in vocab.MEDIENART_DOKUMENTTYP.items():
        for document_type in types:
            assert vocab.is_valid_pair(media_type, document_type)


def test_is_valid_pair_rejects_a_type_from_a_different_media_type() -> None:
    populated = [m for m, ts in vocab.MEDIENART_DOKUMENTTYP.items() if ts]
    assert len(populated) >= 2, "need two populated media types to cross them"
    a, b = populated[0], populated[1]
    foreign = vocab.MEDIENART_DOKUMENTTYP[b][0]
    assert foreign not in vocab.MEDIENART_DOKUMENTTYP[a]
    assert not vocab.is_valid_pair(a, foreign)


def test_is_valid_pair_allows_no_document_type() -> None:
    # "kein Dokumenttyp" (None) is always valid — the field is optional.
    for media_type in vocab.media_types():
        assert vocab.is_valid_pair(media_type, None)


def test_is_valid_pair_rejects_a_document_type_without_a_media_type() -> None:
    # A Dokumenttyp with no Medienart is a mismatched pair (no media type owns it).
    assert not vocab.is_valid_pair(None, "Brief")


def test_grouped_options_are_optgroup_shaped() -> None:
    # select_grouped needs (media_type_label, ((value, caption), ...)) tuples for <optgroup>s.
    grouped = vocab.grouped_document_type_options()
    labels = [label for label, _ in grouped]
    assert labels == list(vocab.media_types())
    for label, options in grouped:
        assert options == tuple((t, t) for t in vocab.MEDIENART_DOKUMENTTYP[label])


# --- EDTF -> German echo -----------------------------------------------------------


def test_edtf_echo_plain_year() -> None:
    assert vocab.edtf_to_german(EdtfDate("1962")) == "1962"


def test_edtf_echo_decade() -> None:
    assert vocab.edtf_to_german(EdtfDate("197X")) == "1970er"


def test_edtf_echo_approximate() -> None:
    assert vocab.edtf_to_german(EdtfDate("1970~")) == "um 1970"


def test_edtf_echo_uncertain() -> None:
    assert vocab.edtf_to_german(EdtfDate("1970?")) == "1970 (unsicher)"


def test_edtf_echo_interval() -> None:
    assert vocab.edtf_to_german(EdtfDate("1984/1995")) == "1984 bis 1995"


def test_edtf_echo_none_is_empty() -> None:
    assert vocab.edtf_to_german(None) == ""
