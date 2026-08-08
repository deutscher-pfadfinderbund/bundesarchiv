"""README codec — Article ⇄ front-matter bytes, tested directly (no store, no repo)."""

import pytest

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Lifecycle, MediaRef
from bundesarchiv.persistence import readme
from bundesarchiv.persistence.errors import ArchiveError


def _article(**overrides: object) -> Article:
    defaults: dict[str, object] = {
        "ulid": "01J0",
        "title": "Zeltlager 1955",
        "collection_id": "coll-fotos",
        "body": "Ein Foto.\n\n## Details\n\n---\n\nSchwarz-weiß.",
        "lifecycle": Lifecycle.PUBLISHED,
        "audience": Audience(AudienceTier.GROUPS, ("bundesfuehrung",)),
        "ref_code": "Foto-1955/007",
        "tags": ("zeltlager", "1955"),
        "media": (MediaRef("photo.jpg", "a" * 64, "image/jpeg", 1234),),
    }
    defaults.update(overrides)
    return Article(**defaults)  # type: ignore[arg-type]


def test_encode_decode_round_trips_every_field() -> None:
    article = _article()
    article2, version = readme.decode("01J0", readme.encode(article, 3))
    assert article2 == article  # incl. German body with a --- rule, audience, media
    assert version == 3


def test_custom_metadata_round_trips() -> None:
    article = _article(custom=(("herkunft", "Familie Müller"), ("zustand", "gut")))
    decoded, _ = readme.decode("01J0", readme.encode(article, 1))
    assert decoded.custom == (("herkunft", "Familie Müller"), ("zustand", "gut"))


def test_empty_custom_is_omitted_from_the_wire() -> None:
    text = readme.encode(_article(custom=()), 1)
    assert "custom:" not in text
    assert readme.decode("01J0", text)[0].custom == ()


def test_inherit_audience_omits_the_key_and_round_trips_as_none() -> None:
    # `audience=None` means "inherit" (ADR 0001): nothing is written on the wire,
    # and an absent key decodes back to None, not to an explicit default.
    article = _article(audience=None)
    text = readme.encode(article, 1)
    assert "audience:" not in text
    decoded, _ = readme.decode("01J0", text)
    assert decoded.audience is None
    assert decoded == article


def test_absent_audience_key_decodes_to_inherit() -> None:
    # A README that never had an audience key (e.g. older / hand-written) is inherit,
    # not an explicit Members rung — explicit Members must stay distinguishable.
    decoded, _ = readme.decode(
        "x", "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\n---\nbody"
    )
    assert decoded.audience is None


def test_empty_audience_mapping_decodes_to_inherit() -> None:
    # A content-less `audience: {}` names no rung, so it is inherit (None) — same as an
    # absent key — not a surprising explicit Members rung that would block a wider ancestor.
    decoded, _ = readme.decode(
        "x",
        "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\naudience: {}\n---\nbody",
    )
    assert decoded.audience is None


@pytest.mark.parametrize(
    "body", ["", "\n", "\n\nopens blank", "no trailing newline", "ends with a fence\n---"]
)
def test_body_round_trips_exactly(body: str) -> None:
    decoded, _ = readme.decode("x", readme.encode(_article(body=body), 1))
    assert decoded.body == body


def test_read_version_reads_without_rebuilding_the_article() -> None:
    # The cheap path: just the version, no Article reconstruction.
    assert readme.read_version("01J0", readme.encode(_article(), 7)) == 7


def test_encode_starts_with_marker_then_fence() -> None:
    text = readme.encode(_article(), 1)
    assert text.startswith("<!-- Managed by bundesarchiv")
    assert "\n---\n" in text


def test_decode_without_marker_still_parses() -> None:
    decoded, version = readme.decode(
        "x", "---\nulid: x\nversion: 2\ntitle: t\ncollection_id: c\nlifecycle: draft\n---\nbody"
    )
    assert decoded.title == "t"
    assert version == 2


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("no fence at all", "no front-matter fence"),
        ("---\nulid: x\nno closing fence\nbody", "unterminated"),
        ("---\ntags: [unclosed\n---\nbody", "malformed YAML"),
        ("---\njust a string\n---\nbody", "non-mapping"),
        ("---\ntitle: t\n---\nbody", "missing required field (ulid/version)"),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: bogus\n---\n",
            "bad enum",
        ),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\ntags: scalar\n---\n",
            "scalar tags",
        ),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\naudience: notadict\n---\n",
            "non-mapping audience",
        ),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\naudience:\n  tier: groups\n  groups: []\n---\n",
            "GROUPS tier with no groups (Audience invariant -> ArchiveError at the seam)",
        ),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\naudience:\n  tier: public\n  groups:\n  - geheim\n---\n",
            "PUBLIC tier with a named group (Audience invariant -> ArchiveError at the seam)",
        ),
        (
            "---\nulid: x\nversion: 1.5\ntitle: t\ncollection_id: c\nlifecycle: draft\n---\n",
            "non-integer version (must not silently truncate)",
        ),
        (
            "---\nulid: x\nversion: true\ntitle: t\ncollection_id: c\nlifecycle: draft\n---\n",
            "boolean version (bool is not an int version)",
        ),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\nref_code:\n  - a\n  - b\n---\n",
            "non-scalar ref_code (must not build a type-violating Article)",
        ),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\nmedia: notalist\n---\n",
            "non-list media",
        ),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\nmedia:\n  - filename: a.jpg\n    content_hash: abc\n    byte_size: not-a-number\n---\n",
            "media entry with a non-integer byte_size",
        ),
        (
            "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\ncustom: notamap\n---\n",
            "non-mapping custom",
        ),
    ],
)
def test_decode_rejects_corrupt_readme_as_archive_error(text: str, why: str) -> None:
    with pytest.raises(ArchiveError):
        readme.decode("x", text)


def test_read_version_rejects_corrupt_as_archive_error() -> None:
    with pytest.raises(ArchiveError):
        readme.read_version("x", "---\ntags: [unclosed\n---\n")


def test_read_version_rejects_a_non_integer_version() -> None:
    # Valid YAML, corrupt version routed specifically through read_version's own catch.
    text = "---\nulid: x\nversion: 1.5\ntitle: t\ncollection_id: c\nlifecycle: draft\n---\nbody"
    with pytest.raises(ArchiveError):
        readme.read_version("x", text)


def test_deeply_nested_front_matter_surfaces_as_archive_error() -> None:
    # Deeply-nested flow collections blow the stack inside yaml.safe_load (RecursionError, not a
    # YAMLError subclass) — the codec must still contain it, from both decode and read_version.
    nested = "---\nkey: " + "{" * 600 + "\n---\nbody"
    with pytest.raises(ArchiveError):
        readme.decode("x", nested)
    with pytest.raises(ArchiveError):
        readme.read_version("x", nested)


# --- date / creator / subject_place -----------------------------------------------------------


def test_date_creator_subject_place_round_trip() -> None:
    article = _article(
        date=EdtfDate("1955-07"),
        creator="Max Mustermann",
        subject_place="Köln",
    )
    decoded, _ = readme.decode("01J0", readme.encode(article, 1))
    assert decoded.date == EdtfDate("1955-07")
    assert decoded.creator == "Max Mustermann"
    assert decoded.subject_place == "Köln"
    assert decoded == article


def test_absent_date_creator_subject_place_decode_to_none() -> None:
    # A README that omits the three keys must produce None (not a default, not a KeyError).
    text = "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\n---\nbody"
    decoded, _ = readme.decode("x", text)
    assert decoded.date is None
    assert decoded.creator is None
    assert decoded.subject_place is None


def test_none_date_creator_subject_place_omitted_from_wire() -> None:
    article = _article(date=None, creator=None, subject_place=None)
    text = readme.encode(article, 1)
    assert "date:" not in text
    assert "creator:" not in text
    assert "subject_place:" not in text


def test_invalid_edtf_date_on_wire_raises_archive_error() -> None:
    text = (
        "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\n"
        "lifecycle: draft\ndate: not-a-date\n---\nbody"
    )
    with pytest.raises(ArchiveError):
        readme.decode("x", text)


# --- media captions (ADR 0015) ----------------------------------------------------------------


def test_media_caption_round_trips() -> None:
    # A caption on a media entry survives encode/decode intact (ADR 0015 front-matter field).
    article = _article(
        media=(
            MediaRef("seite-a.mp3", "9" * 64, "audio/mpeg", 48213977, caption="Seite A — Bericht"),
            MediaRef("huelle.jpg", "c" * 64, "image/jpeg", 2011458),  # uncaptioned
        )
    )
    decoded, _ = readme.decode("01J0", readme.encode(article, 1))
    assert decoded.media[0].caption == "Seite A — Bericht"
    assert decoded.media[1].caption is None
    assert decoded == article


def test_absent_media_caption_decodes_to_none() -> None:
    # A media entry with no caption key decodes to caption=None (old READMEs have no caption keys).
    text = (
        "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\n"
        "media:\n- filename: a.jpg\n  content_hash: abc\n---\nbody"
    )
    decoded, _ = readme.decode("x", text)
    assert decoded.media[0].caption is None


def test_uncaptioned_media_omits_caption_key_from_wire() -> None:
    # No caption line for an uncaptioned entry (ADR 0015: empty optional fields omitted on write).
    text = readme.encode(_article(media=(MediaRef("a.jpg", "a" * 64),)), 1)
    assert "caption:" not in text


def test_non_scalar_media_caption_rejected_as_archive_error() -> None:
    text = (
        "---\nulid: x\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\n"
        "media:\n- filename: a.jpg\n  content_hash: abc\n  caption:\n  - a\n  - b\n---\nbody"
    )
    with pytest.raises(ArchiveError):
        readme.decode("x", text)


# --- omit-empty front-matter fields (ADR 0015 write rule) -------------------------------------


def test_empty_optional_fields_omitted_from_wire() -> None:
    # A minimal Article: no ref_code / media_type / document_type / physical_location, empty tags,
    # no media. NONE of these emit a `: null` line or an empty collection (ADR 0015).
    text = readme.encode(
        Article(ulid="x", title="t", collection_id="c", lifecycle=Lifecycle.DRAFT), 1
    )
    assert ": null" not in text
    assert "null" not in text  # no bare null value anywhere in the front matter
    for absent_key in ("ref_code:", "media_type:", "document_type:", "physical_location:"):
        assert absent_key not in text, f"{absent_key} should be omitted when empty"
    assert "tags:" not in text  # empty tuple -> no key (not `tags: []`)
    assert "media:" not in text  # empty tuple -> no key (not `media: []`)


def test_set_optional_fields_still_emitted() -> None:
    # The omit-empty rule drops only EMPTY fields; a set field still appears on the wire.
    text = readme.encode(
        _article(ref_code="B2", media_type="Foto", document_type="Fotografie", tags=("a",)), 1
    )
    assert "ref_code: B2" in text
    assert "media_type: Foto" in text
    assert "document_type: Fotografie" in text
    assert "tags:" in text


def test_media_entry_omits_empty_media_type_and_byte_size() -> None:
    # A media entry with only filename + content_hash writes neither `media_type: null` nor
    # `byte_size: null` (ADR 0015), and still round-trips to None for both.
    text = readme.encode(_article(media=(MediaRef("a.jpg", "a" * 64),)), 1)
    assert "media_type:" not in text
    assert "byte_size:" not in text
    decoded, _ = readme.decode("01J0", text)
    assert decoded.media[0].media_type is None
    assert decoded.media[0].byte_size is None


def test_old_style_readme_with_explicit_nulls_loads_identically() -> None:
    # The compat contract (ADR 0015): a README in the OLD style — explicit `: null` lines, an empty
    # `tags: []`, a media entry carrying `media_type: null` / `byte_size: null` and NO caption key —
    # must decode to exactly the same Article as the new omit-empty style. This is what makes every
    # existing README parse with zero migration.
    old_style = (
        "<!-- Managed by bundesarchiv — do not edit by hand. -->\n"
        "---\n"
        "ulid: 01J0\n"
        "version: 1\n"
        "title: Zeltlager 1955\n"
        "collection_id: c\n"
        "lifecycle: published\n"
        "ref_code: null\n"
        "media_type: null\n"
        "document_type: null\n"
        "tags: []\n"
        "physical_location: null\n"
        "media:\n"
        "- filename: photo.jpg\n"
        "  content_hash: abc\n"
        "  media_type: null\n"
        "  byte_size: null\n"
        "---\n"
        "Ein Foto."
    )
    new_style = readme.encode(
        Article(
            ulid="01J0",
            title="Zeltlager 1955",
            collection_id="c",
            body="Ein Foto.",
            lifecycle=Lifecycle.PUBLISHED,
            media=(MediaRef("photo.jpg", "abc"),),
        ),
        1,
    )
    old_article, old_version = readme.decode("01J0", old_style)
    new_article, new_version = readme.decode("01J0", new_style)
    assert old_article == new_article  # explicit-null old style ≡ omit-empty new style
    assert old_version == new_version == 1
