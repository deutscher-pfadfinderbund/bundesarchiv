"""``catalog.parse_edit_form``. The "" → None boundary (spec §8) is leak-sensitive."""

from datetime import UTC, datetime

import pytest

from bundesarchiv.app.web import catalog, vocab
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.domain.models import ULID, Article, Audience, AudienceTier, Change, Collection


def _post(**overrides: str | list[str]) -> dict[str, list[str]]:
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
        "files_audience": [""],
        "files_groups": [""],
        "custom_key": [""],
        "custom_value": [""],
        "expected_version": ["3"],
    }
    for key, value in overrides.items():
        base[key] = value if isinstance(value, list) else [value]
    return base


#: The two Collections the form offered; the parse layer accepts these and nothing else.
_COLLECTION = CollectionChooser(
    lambda: (
        Collection(ulid=ULID("COLL1"), name="Eins"),
        Collection(ulid=ULID("COLL2"), name="Zwei"),
    )
)


def _parse(
    post: dict[str, list[str]],
    *,
    stored: Audience | None = None,
    stored_files: Audience | None = None,
) -> catalog.ParseResult:
    return catalog.parse_edit_form(
        post,
        ulid=ULID("01ARTICLEULID0000000000000"),
        chooser=_COLLECTION,
        current_audience=stored,
        current_files_audience=stored_files,
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


def test_an_edit_keeps_the_trash_mark() -> None:
    mark = Change(at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC), by="bert")
    result = catalog.parse_edit_form(
        _post(),
        ulid=ULID("01ARTICLEULID0000000000000"),
        chooser=_COLLECTION,
        current_audience=None,
        current_files_audience=None,
        added_at=None,
        deleted=mark,
    )
    assert result.article is not None and result.article.deleted == mark


def test_a_line_break_in_the_title_becomes_one_space() -> None:
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
    assert art.files_audience is None


def test_body_stays_a_string_when_empty() -> None:
    art = _parse(_post(body="")).article
    assert art is not None
    assert art.body == ""


# --- the two Sichtbarkeit pairs: the record's and the files' (ADR 0027) ---------------

#: Each pair's select is named after the Article attribute it sets.
_PAIRS = pytest.mark.parametrize(
    "pair", [catalog.RECORD_AUDIENCE, catalog.FILES_AUDIENCE], ids=["record", "files"]
)


def _rung(art: Article | None, pair: catalog.AudienceFields) -> Audience | None:
    assert art is not None
    rung: Audience | None = getattr(art, pair.choice)
    return rung


@_PAIRS
@pytest.mark.parametrize("tier", [AudienceTier.PUBLIC, AudienceTier.MEMBERS])
def test_a_named_rung_is_stored(pair: catalog.AudienceFields, tier: AudienceTier) -> None:
    # naming groups on a rung that takes none must not smuggle a GROUPS audience (illegal per the model)
    post = _post(**{pair.choice: vocab.audience_value(Audience(tier)), pair.groups: "vorstand"})
    assert _rung(_parse(post).article, pair) == Audience(tier)


@_PAIRS
def test_the_groups_rung_stores_one_group_per_line(pair: catalog.AudienceFields) -> None:
    # one group per line, as the Schlagworte: a group name may carry a comma
    post = _post(**{pair.choice: "groups", pair.groups: "Gau Wartburg, Nord\r\n kasse "})
    assert _rung(_parse(post).article, pair) == Audience(
        AudienceTier.GROUPS, ("Gau Wartburg, Nord", "kasse")
    )


#: The stored audience the contract below edits: the narrowest rung, so any change widens it.
_STORED = Audience(AudienceTier.GROUPS, groups=("vorstand",))


def _without(post: dict[str, list[str]], *keys: str) -> dict[str, list[str]]:
    return {k: v for k, v in post.items() if k not in keys}


_NO_RUNG = {
    "absent": lambda pair: _without(
        _post(), pair.choice, pair.groups
    ),  # a form from before a rename
    "groups-only": lambda pair: _without(_post(**{pair.groups: "alle"}), pair.choice),
    "unknown": lambda pair: _post(**{pair.choice: "bogus"}),
    "case": lambda pair: _post(**{pair.choice: "Public"}),
    "whitespace": lambda pair: _post(**{pair.choice: " public"}),
    "unknown-first": lambda pair: _post(**{pair.choice: ["bogus", "public"]}),
    "control": lambda pair: _post(**{pair.choice: "public\x00"}),
    "overlong": lambda pair: _post(**{pair.choice: "public" * 10_000}),
}


@_PAIRS
@pytest.mark.parametrize("shape", _NO_RUNG)
def test_a_post_naming_no_rung_keeps_the_stored_audience(
    pair: catalog.AudienceFields, shape: str
) -> None:
    # inheriting would widen a GROUPS rung to the Collection's, or the files to the record's
    post = _NO_RUNG[shape](pair)
    assert _rung(_parse(post, stored=_STORED, stored_files=_STORED).article, pair) == _STORED


def test_each_pair_keeps_its_own_stored_rung() -> None:
    files = Audience(AudienceTier.GROUPS, ("kasse",))
    post = _without(_post(), "audience", "groups", "files_audience", "files_groups")
    art = _parse(post, stored=_STORED, stored_files=files).article
    assert art is not None
    assert (art.audience, art.files_audience) == (_STORED, files)


@_PAIRS
@pytest.mark.parametrize(
    "groups", [None, "", " \n ", "\t", "\n\n"], ids=["absent", "empty", "blank", "tab", "breaks"]
)
def test_the_groups_rung_naming_no_group_saves_nothing(
    pair: catalog.AudienceFields, groups: str | None
) -> None:
    post = _post(**{pair.choice: "groups", pair.groups: groups or ""})
    if groups is None:
        post = _without(post, pair.groups)
    result = _parse(post, stored=_STORED, stored_files=_STORED)
    assert result.article is None
    assert set(result.errors) == {pair.groups}


@_PAIRS
def test_the_explicit_inherit_choice_drops_the_stored_audience(
    pair: catalog.AudienceFields,
) -> None:
    post = _post(**{pair.choice: "", pair.groups: "vorstand"})
    assert _rung(_parse(post, stored=_STORED, stored_files=_STORED).article, pair) is None


# --- custom bag ------------------------------------------------------------------


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


@pytest.mark.parametrize(
    "keys",
    [["Fotograf", "Auflage", "Fotograf"], ["Fotograf ", "Auflage", " Fotograf"]],
    ids=["same", "same-after-trim"],
)
def test_a_repeated_custom_name_saves_nothing(keys: list[str]) -> None:
    result = _parse(_post(custom_key=keys, custom_value=["Meyer", "500", "Schulze"]))
    assert result.article is None
    assert "Fotograf" in result.errors["custom"]


def test_a_repeated_name_on_an_incomplete_row_is_no_repeat() -> None:
    art = _parse(_post(custom_key=["Fotograf", "Fotograf"], custom_value=["", "Meyer"])).article
    assert art is not None
    assert dict(art.custom) == {"Fotograf": "Meyer"}


# --- expected_version rides the form ------------------------------------------------


def test_expected_version_is_parsed() -> None:
    result = _parse(_post(expected_version="7"))
    assert result.expected_version == 7


def test_missing_expected_version_defaults_to_zero() -> None:
    post = _post()
    del post["expected_version"]
    result = _parse(post)
    assert result.expected_version == 0
