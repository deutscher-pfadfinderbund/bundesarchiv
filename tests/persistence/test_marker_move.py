"""The README marker move (ADR 0019, amended 2026-10-16): only the marker line changes, and only in
a README in exactly the old shape."""

from collections.abc import Callable

import pytest
from tests._readmes import OLD_MARKER

from bundesarchiv.persistence import collection_readme, readme
from bundesarchiv.persistence._front_matter import HEAD
from bundesarchiv.persistence.marker_move import marker_moved

#: An Article README as the app wrote it before 2026-10-16.
OLD_ARTICLE = (
    f"{OLD_MARKER}"
    "---\n"
    "ulid: 01J0\n"
    "version: 3\n"
    "changed_at: '2026-09-25T10:30:00Z'\n"
    "changed_by: anna\n"
    "title: 'Zeltlager 1955: Fahrt'\n"
    "collection_id: coll-fotos\n"
    "lifecycle: draft\n"
    "deleted_at: '2026-10-01T08:00:00Z'\n"
    "deleted_by: bert\n"
    "audience:\n"
    "  tier: groups\n"
    "  groups:\n"
    "  - bundesfuehrung\n"
    "ref_code: Foto-1955/007\n"
    "media_type: Foto\n"
    "document_type: Fotografie\n"
    "tags:\n"
    "- zeltlager\n"
    "- a, b\n"
    "physical_location: Schrank 3 (100 %)\n"
    "date: 1955-07\n"
    "creator: Jürgen\n"
    "subject_place: ' Burg Waldeck '\n"
    "media:\n"
    "- filename: photo.jpg\n"
    "  content_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    "  media_type: image/jpeg\n"
    "  byte_size: 1234\n"
    "  caption: Unterschrift\n"
    "  alt: Bild\n"
    "custom:\n"
    "  herkunft: Familie Müller\n"
    "added_at: '2017-06-26T06:06:40Z'\n"
    "template: true\n"
    "---\n"
    "Ein Foto.\n\n---\n\nSchwarz-weiß.\n"
)

#: A Collection README as the app wrote it before 2026-10-16.
OLD_COLLECTION = (
    f"{OLD_MARKER}"
    "---\n"
    "ulid: 01BESTAND\n"
    "name: Fotos\n"
    "version: 2\n"
    "changed_at: '2026-09-25T10:30:00Z'\n"
    "changed_by: anna\n"
    "parent_id: 01PARENT\n"
    "audience:\n"
    "  tier: groups\n"
    "  groups:\n"
    "  - bundesfuehrung\n"
    "---\n"
)


def test_only_the_marker_line_changes() -> None:
    old = OLD_ARTICLE + OLD_MARKER + "---\n"  # the old head again, in the body
    assert marker_moved(old.encode()) == (HEAD + old.split("\n", 2)[2]).encode()


@pytest.mark.parametrize(
    ("old", "decode"),
    [
        (OLD_ARTICLE, lambda text: readme.decode("01J0", text)),
        (OLD_COLLECTION, lambda text: collection_readme.decode_collection(text, ulid="01BESTAND")),
    ],
)
def test_the_record_reads_the_same(old: str, decode: Callable[[str], object]) -> None:
    moved = marker_moved(old.encode())
    assert moved is not None
    assert decode(moved.decode()) == decode(old)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"", id="empty"),
        pytest.param(OLD_ARTICLE.removeprefix(OLD_MARKER).encode(), id="no-marker"),
        pytest.param(f"\n{OLD_ARTICLE}".encode(), id="marker-not-at-start"),
        pytest.param(OLD_ARTICLE.replace("\n", "\r\n").encode(), id="hand-saved-crlf"),
    ],
)
def test_a_readme_not_in_exactly_the_old_shape_is_left_alone(data: bytes) -> None:
    assert marker_moved(data) is None
