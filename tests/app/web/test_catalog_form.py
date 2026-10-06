"""The pure cataloging-form parse/validate layer (Part 4.7, spec §3/§4/§5/§8).

``catalog.parse_edit_form`` is a total function over a plain string→list mapping (a Django
``QueryDict`` shape) plus the article's identity/collection: it either yields a fully-built
``Article`` ready for ``save_article`` OR a ``FormErrors`` map keyed by field name with the verbatim
German strings. It is IO-free and request-free so the whole validation contract is unit-testable
with no database and no request cycle — the view stays a thin Conflict-catch shell over it.

The leak-sensitive contract (spec §8, the "" → None boundary) is pinned here: EVERY optional scalar
empties to ``None`` (``ref_code``, ``media_type``, ``document_type``, ``physical_location``,
``creator``, ``subject_place``, ``date``, each ``custom_value[]``); empty custom rows drop; ``body``
stays a ``str``; inheriting Sichtbarkeit yields ``audience=None``; a POST naming no Sichtbarkeit keeps the stored one.
"""

from datetime import UTC, datetime

import pytest

from bundesarchiv.app.web import catalog
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.domain.models import Audience, AudienceTier, Change, Collection


def _post(**overrides: object) -> dict[str, list[str]]:
    """A minimally-valid create/edit POST as a QueryDict-shaped mapping (each value a list)."""
    base: dict[str, list[str]] = {
        "title": ["Wanderfahrt 1962"],
        "collection_id": ["COLL1"],
        "ref_code": [""],
        "media_type": ["Foto(s)"],
        "document_type": [""],
        "tags": [""],
        "date": [""],
        "creator": [""],
        "subject_place": [""],
        "physical_location": [""],
        "body": [""],
        "audience": [""],
        "groups": [""],
        "custom_key": [""],
        "custom_value": [""],
        "expected_version": ["3"],
    }
    for key, value in overrides.items():
        base[key] = value if isinstance(value, list) else [value]  # type: ignore[list-item]
    return base


#: The two Bestände the form offered; the parse layer accepts these and nothing else.
_BESTAND = CollectionChooser(
    lambda: (Collection(ulid="COLL1", name="Eins"), Collection(ulid="COLL2", name="Zwei"))
)


def _parse(post: dict[str, list[str]], *, stored: Audience | None = None) -> catalog.ParseResult:
    return catalog.parse_edit_form(
        post,
        ulid="01ARTICLEULID0000000000000",
        chooser=_BESTAND,
        current_audience=stored,
        added_at=None,
        deleted=None,
    )


# --- happy path + the "" -> None boundary ------------------------------------------


def test_minimal_valid_form_builds_an_article() -> None:
    result = _parse(_post())
    assert result.article is not None
    assert result.errors == {}
    assert result.article.title == "Wanderfahrt 1962"
    assert result.article.collection_id == "COLL1"
    assert result.article.ulid == "01ARTICLEULID0000000000000"


def test_an_edit_keeps_the_papierkorb_mark() -> None:
    mark = Change(at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC), by="bert")
    result = catalog.parse_edit_form(
        _post(),
        ulid="01ARTICLEULID0000000000000",
        chooser=_BESTAND,
        current_audience=None,
        added_at=None,
        deleted=mark,
    )
    assert result.article is not None and result.article.deleted == mark


def test_a_line_break_in_the_titel_becomes_one_space() -> None:
    # the Titel is a textarea; a break would reach the ledger, <title>, the crumbs and the index
    result = _parse(_post(title=" Wander-\r\n\n fahrt\n"))
    assert result.article is not None
    assert result.article.title == "Wander- fahrt"


def test_every_empty_optional_scalar_becomes_none() -> None:
    result = _parse(_post())
    art = result.article
    assert art is not None
    assert art.ref_code is None
    assert art.document_type is None
    assert art.physical_location is None
    assert art.creator is None
    assert art.subject_place is None
    assert art.date is None
    assert art.audience is None  # inherit default


def test_body_stays_a_string_when_empty() -> None:
    art = _parse(_post(body="")).article
    assert art is not None
    assert art.body == ""


def test_present_optionals_round_trip() -> None:
    art = _parse(
        _post(
            ref_code="F12/3-b",
            document_type="Zeitschrift",
            creator="Kurt Meyer",
            subject_place="Kassel",
            physical_location="Regal 4",
            body="Eine **Beschreibung**.",
        )
    ).article
    assert art is not None
    assert art.ref_code == "F12/3-b"
    assert art.document_type == "Zeitschrift"
    assert art.creator == "Kurt Meyer"
    assert art.subject_place == "Kassel"
    assert art.physical_location == "Regal 4"
    assert art.body == "Eine **Beschreibung**."


def test_whitespace_only_optional_scalar_becomes_none() -> None:
    art = _parse(_post(ref_code="   ")).article
    assert art is not None
    assert art.ref_code is None


def test_tags_split_on_lines_only() -> None:
    # Legacy Schlagworte carry commas ("Dritte, umgearbeitete Auflage, 1924"); a browser submits a
    # textarea's line breaks as CRLF.
    raw = "Dritte, umgearbeitete Auflage, 1924\r\n  100 % Wolle \r\n\r\n\u00c4rmelwappen\n"
    art = _parse(_post(tags=raw)).article
    assert art is not None
    assert art.tags == ("Dritte, umgearbeitete Auflage, 1924", "100 % Wolle", "\u00c4rmelwappen")


# --- required-field validation (verbatim strings) ----------------------------------


def test_missing_title_is_a_field_error() -> None:
    result = _parse(_post(title=""))
    assert result.article is None
    assert result.errors["title"] == "Titel ist erforderlich."


def test_missing_collection_is_a_field_error() -> None:
    result = _parse(_post(collection_id=""))
    assert result.errors["collection_id"] == "Bitte einen Bestand wählen."


def test_collection_not_in_options_is_rejected() -> None:
    result = _parse(_post(collection_id="NOT-A-COLL"))
    assert result.errors["collection_id"] == "Bitte einen Bestand wählen."


def test_missing_media_type_is_a_field_error() -> None:
    result = _parse(_post(media_type=""))
    assert result.errors["media_type"] == "Medienart ist erforderlich."


def test_media_type_not_in_vocabulary_is_a_field_error() -> None:
    # A value outside vocab.media_types() can only arrive via select tampering (no <option> for
    # it) — rejected exactly like empty, same string, and no article is built from it.
    result = _parse(_post(media_type="Quatsch"))
    assert result.article is None
    assert result.errors["media_type"] == "Medienart ist erforderlich."


# --- dependent-vocab pairing -------------------------------------------------------


def test_document_type_not_belonging_to_media_type_is_rejected() -> None:
    result = _parse(_post(media_type="Foto(s)", document_type="Brief"))
    assert result.errors["document_type"] == "Dieser Dokumenttyp gehört nicht zu „Foto(s)“."


def test_document_type_belonging_to_media_type_is_accepted() -> None:
    result = _parse(_post(media_type="Foto(s)", document_type="Zeitschrift"))
    assert result.errors == {}


def test_document_type_without_media_type_asks_for_media_type_first() -> None:
    # Missing media_type + a chosen document_type must not interpolate None into the
    # pair-mismatch string — it gets its own, more helpful message instead.
    result = _parse(_post(media_type="", document_type="Urkunde"))
    assert result.errors["document_type"] == "Bitte zuerst eine Medienart wählen."
    assert "None" not in " ".join(result.errors.values())


def test_document_type_with_invalid_media_type_asks_for_media_type_first() -> None:
    result = _parse(_post(media_type="Quatsch", document_type="Urkunde"))
    assert result.errors["document_type"] == "Bitte zuerst eine Medienart wählen."
    assert "None" not in " ".join(result.errors.values())


# --- EDTF ---------------------------------------------------------------------------


def test_invalid_edtf_is_a_field_error() -> None:
    result = _parse(_post(date="nonsense"))
    assert "date" in result.errors
    assert result.errors["date"].startswith("Datierung:")


def test_valid_edtf_round_trips() -> None:
    art = _parse(_post(date="1962")).article
    assert art is not None
    assert art.date is not None
    assert art.date.value == "1962"


# --- Sichtbarkeit + the GROUPS-iff invariant ---------------------------------------


def test_inherit_visibility_yields_none_audience() -> None:
    art = _parse(_post(audience="")).article
    assert art is not None
    assert art.audience is None


def test_public_visibility() -> None:
    art = _parse(_post(audience="public")).article
    assert art is not None
    assert art.audience is not None
    assert art.audience.tier is AudienceTier.PUBLIC


def test_members_visibility() -> None:
    art = _parse(_post(audience="members")).article
    assert art is not None
    assert art.audience is not None
    assert art.audience.tier is AudienceTier.MEMBERS


def test_groups_visibility_with_groups() -> None:
    # one group per line, as the Schlagworte: a group name may carry a comma
    art = _parse(_post(audience="groups", groups="Gau Wartburg, Nord\r\n kasse ")).article
    assert art is not None
    assert art.audience is not None
    assert art.audience.tier is AudienceTier.GROUPS
    assert art.audience.groups == ("Gau Wartburg, Nord", "kasse")


def test_groups_visibility_without_groups_is_a_field_error() -> None:
    result = _parse(_post(audience="groups", groups=""))
    assert result.errors["groups"] == "Bitte mindestens eine Gruppe angeben."


def test_gruppen_ignored_when_not_groups_tier() -> None:
    # Naming groups on a MEMBERS rung must not smuggle a GROUPS audience (illegal per the model).
    art = _parse(_post(audience="members", groups="vorstand")).article
    assert art is not None
    assert art.audience is not None
    assert art.audience.tier is AudienceTier.MEMBERS
    assert art.audience.groups == ()


#: The stored audience the contract below edits: the narrowest rung, so any change widens it.
_STORED = Audience(AudienceTier.GROUPS, groups=("vorstand",))


def _without(post: dict[str, list[str]], *keys: str) -> dict[str, list[str]]:
    return {k: v for k, v in post.items() if k not in keys}


@pytest.mark.parametrize(
    "post",
    [
        _without(_post(), "audience", "groups"),  # a form from before a rename
        _without(_post(groups="alle"), "audience"),  # groups without a rung
        _post(audience="bogus"),
        _post(audience="Public"),
        _post(audience=" public"),
        _post(audience=["bogus", "public"]),  # only the first value counts
    ],
    ids=["absent", "groups-only", "unknown", "case", "whitespace", "unknown-first"],
)
def test_a_post_naming_no_rung_keeps_the_stored_audience(post: dict[str, list[str]]) -> None:
    # inheriting would widen a GROUPS record to its Bestand's rung, public included
    art = _parse(post, stored=_STORED).article
    assert art is not None
    assert art.audience == _STORED


@pytest.mark.parametrize(
    "post",
    [_without(_post(audience="groups"), "groups"), _post(audience="groups", groups=" \n ")],
    ids=["groups-absent", "groups-blank"],
)
def test_the_groups_rung_naming_no_group_saves_nothing(post: dict[str, list[str]]) -> None:
    result = _parse(post, stored=_STORED)
    assert result.article is None
    assert "groups" in result.errors


def test_the_explicit_inherit_choice_drops_the_stored_audience() -> None:
    art = _parse(_post(audience=""), stored=_STORED).article
    assert art is not None
    assert art.audience is None


# --- custom bag (Gruppe 7) ---------------------------------------------------------


def test_custom_rows_round_trip() -> None:
    art = _parse(_post(custom_key=["Fotograf", "Auflage"], custom_value=["Meyer", "500"])).article
    assert art is not None
    assert dict(art.custom) == {"Fotograf": "Meyer", "Auflage": "500"}


def test_empty_custom_rows_are_dropped() -> None:
    art = _parse(_post(custom_key=["Fotograf", "", ""], custom_value=["Meyer", "", ""])).article
    assert art is not None
    assert dict(art.custom) == {"Fotograf": "Meyer"}


def test_custom_value_empties_are_dropped_with_their_key() -> None:
    # A key with an empty value is an incomplete row → dropped (not stored as key→"").
    art = _parse(_post(custom_key=["Fotograf"], custom_value=[""])).article
    assert art is not None
    assert art.custom == ()


def test_reserved_custom_key_is_a_field_error() -> None:
    result = _parse(_post(custom_key=["title"], custom_value=["x"]))
    assert result.errors["custom"] == "Bezeichnung ist reserviert."


# --- expected_version rides the form ------------------------------------------------


def test_expected_version_is_parsed() -> None:
    result = _parse(_post(expected_version="7"))
    assert result.expected_version == 7


def test_missing_expected_version_defaults_to_zero() -> None:
    post = _post()
    del post["expected_version"]
    result = _parse(post)
    assert result.expected_version == 0
