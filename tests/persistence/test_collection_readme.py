"""Collection README codec — Collection ⇄ front-matter bytes, tested directly (no store, no repo)."""

import pytest

from bundesarchiv.domain.models import Audience, AudienceTier, Collection
from bundesarchiv.persistence import collection_readme
from bundesarchiv.persistence.errors import ArchiveError


def _collection(**overrides: object) -> Collection:
    defaults: dict[str, object] = {
        "ulid": "01J0",
        "name": "Fotos",
        "parent_id": "PARENT01",
        "audience": Audience(AudienceTier.GROUPS, ("bundesfuehrung",)),
    }
    defaults.update(overrides)
    return Collection(**defaults)  # type: ignore[arg-type]


def test_encode_decode_round_trips_all_fields() -> None:
    collection = _collection()
    decoded = collection_readme.decode_collection(
        collection_readme.encode_collection(collection), ulid="01J0"
    )
    assert decoded == collection


def test_encode_decode_without_parent_id() -> None:
    collection = _collection(parent_id=None)
    text = collection_readme.encode_collection(collection)
    assert "parent_id:" not in text
    decoded = collection_readme.decode_collection(text, ulid="01J0")
    assert decoded == collection
    assert decoded.parent_id is None


def test_encode_decode_without_audience() -> None:
    collection = _collection(audience=None)
    text = collection_readme.encode_collection(collection)
    assert "audience:" not in text
    decoded = collection_readme.decode_collection(text, ulid="01J0")
    assert decoded == collection
    assert decoded.audience is None


def test_encode_decode_minimal() -> None:
    collection = Collection(ulid="01J0", name="Root")
    decoded = collection_readme.decode_collection(
        collection_readme.encode_collection(collection), ulid="01J0"
    )
    assert decoded == collection
    assert decoded.parent_id is None
    assert decoded.audience is None


def test_encode_starts_with_marker_then_fence() -> None:
    text = collection_readme.encode_collection(_collection())
    assert text.startswith("<!-- Managed by bundesarchiv")
    assert "\n---\n" in text


def test_absent_parent_id_decodes_to_none() -> None:
    decoded = collection_readme.decode_collection("---\nulid: 01J0\nname: Root\n---\n", ulid="01J0")
    assert decoded.parent_id is None


def test_absent_audience_key_decodes_to_inherit() -> None:
    decoded = collection_readme.decode_collection("---\nulid: 01J0\nname: Root\n---\n", ulid="01J0")
    assert decoded.audience is None


def test_empty_audience_mapping_decodes_to_inherit() -> None:
    decoded = collection_readme.decode_collection(
        "---\nulid: 01J0\nname: Root\naudience: {}\n---\n", ulid="01J0"
    )
    assert decoded.audience is None


def test_decode_without_marker_still_parses() -> None:
    decoded = collection_readme.decode_collection("---\nulid: 01J0\nname: Root\n---\n", ulid="01J0")
    assert decoded.name == "Root"


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
