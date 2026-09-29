"""Collection README codec — Collection ⇄ front-matter bytes, tested directly (no store, no repo)."""

from datetime import UTC, datetime

import pytest

from bundesarchiv.domain.models import Audience, AudienceTier, Change, Collection
from bundesarchiv.persistence import collection_readme
from bundesarchiv.persistence.errors import ArchiveError

_CHANGE = Change(datetime(2026, 9, 25, 10, 30, tzinfo=UTC), "anna")


def _collection(**overrides: object) -> Collection:
    defaults: dict[str, object] = {
        "ulid": "01J0",
        "name": "Fotos",
        "parent_id": "PARENT01",
        "audience": Audience(AudienceTier.GROUPS, ("bundesfuehrung",)),
    }
    defaults.update(overrides)
    return Collection(**defaults)  # type: ignore[arg-type]


def test_encode_decode_round_trips_all_fields_and_version() -> None:
    collection = _collection()
    decoded, version, _ = collection_readme.decode_collection(
        collection_readme.encode_collection(collection, 3, _CHANGE), ulid="01J0"
    )
    assert decoded == collection
    assert version == 3


def test_encode_decode_without_parent_id() -> None:
    collection = _collection(parent_id=None)
    text = collection_readme.encode_collection(collection, 1, _CHANGE)
    assert "parent_id:" not in text
    decoded, _version, _ = collection_readme.decode_collection(text, ulid="01J0")
    assert decoded == collection
    assert decoded.parent_id is None


def test_encode_decode_without_audience() -> None:
    collection = _collection(audience=None)
    text = collection_readme.encode_collection(collection, 1, _CHANGE)
    assert "audience:" not in text
    decoded, _version, _ = collection_readme.decode_collection(text, ulid="01J0")
    assert decoded == collection
    assert decoded.audience is None


def test_encode_decode_minimal() -> None:
    collection = Collection(ulid="01J0", name="Root")
    decoded, version, _ = collection_readme.decode_collection(
        collection_readme.encode_collection(collection, 1, _CHANGE), ulid="01J0"
    )
    assert decoded == collection
    assert version == 1
    assert decoded.parent_id is None
    assert decoded.audience is None


def test_encode_carries_the_version_in_front_matter() -> None:
    text = collection_readme.encode_collection(_collection(), 7, _CHANGE)
    assert "version: 7" in text


def test_encode_starts_with_marker_then_fence() -> None:
    text = collection_readme.encode_collection(_collection(), 1, _CHANGE)
    assert text.startswith("<!-- Managed by bundesarchiv")
    assert "\n---\n" in text


def test_empty_audience_mapping_decodes_to_inherit() -> None:
    decoded, _version, _ = collection_readme.decode_collection(
        "---\nulid: 01J0\nname: Root\naudience: {}\n---\n", ulid="01J0"
    )
    assert decoded.audience is None


def test_decode_without_marker_still_parses() -> None:
    decoded, _version, _ = collection_readme.decode_collection(
        "---\nulid: 01J0\nname: Root\n---\n", ulid="01J0"
    )
    assert decoded.name == "Root"


def test_decode_rejects_a_corrupt_version() -> None:
    # A present-but-malformed version (float, string, negative) is corruption, not a
    # backfill case — it must surface as ArchiveError, never coerce.
    with pytest.raises(ArchiveError):
        collection_readme.decode_collection(
            "---\nulid: 01J0\nname: Root\nversion: -1\n---\n", ulid="01J0"
        )


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("no fence at all", "no front-matter fence"),
        ("---\nulid: x\nno closing fence\nbody", "unterminated"),
        ("---\ntags: [unclosed\n---\nbody", "malformed YAML"),
        ("---\njust a string\n---\nbody", "non-mapping"),
        ("---\nulid: x\n---\n", "missing required name field"),
        (
            "---\nulid: x\nname: Root\naudience: notadict\n---\n",
            "non-mapping audience",
        ),
        (
            "---\nulid: x\nname: Root\naudience:\n  tier: groups\n  groups: []\n---\n",
            "GROUPS tier with no groups (Audience invariant -> ArchiveError at the seam)",
        ),
        (
            "---\nulid: x\nname: Root\naudience:\n  tier: public\n  groups:\n  - geheim\n---\n",
            "PUBLIC tier with a named group (Audience invariant -> ArchiveError at the seam)",
        ),
    ],
)
def test_decode_rejects_corrupt_readme_as_archive_error(text: str, why: str) -> None:
    with pytest.raises(ArchiveError):
        collection_readme.decode_collection(text, ulid="x")


def test_the_change_record_round_trips() -> None:
    text = collection_readme.encode_collection(_collection(), 2, _CHANGE)
    assert collection_readme.decode_collection(text, ulid="01J0")[2] == _CHANGE


def test_a_corrupt_change_record_surfaces_as_archive_error() -> None:
    text = "---\nulid: 01J0\nname: Fotos\nchanged_at: gestern\nchanged_by: anna\n---\n"
    with pytest.raises(ArchiveError):
        collection_readme.decode_collection(text, ulid="01J0")
