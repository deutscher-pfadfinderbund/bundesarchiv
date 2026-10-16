"""READMEs the app does not write today, for every suite: as a hand edit on the system of record
may leave them (ADR 0020), and in the layout before ADR 0019's amendments of 2026-10-16."""

import pytest

#: How the app opened a README before ADR 0019's amendment of 2026-10-16.
_OLD_MARKER = "<!-- Managed by bundesarchiv — do not edit by hand. -->\n"

#: An Article README as the app wrote it before 2026-10-16: the title in the front matter.
OLD_ARTICLE = (
    f"{_OLD_MARKER}"
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

#: A Collection README as the app wrote it before 2026-10-16: the name in the front matter.
OLD_COLLECTION = (
    f"{_OLD_MARKER}"
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

UNREADABLE_README = [
    pytest.param(b"---\ntitle: [unclosed\n---\n", id="not-yaml"),
    pytest.param("---\ntitle: Größe\n---\n".encode("cp1252"), id="not-utf8"),
]

#: How a hand edit may save a README the app wrote with LF line ends and no BOM.
HAND_SAVED = [
    pytest.param(lambda text: text.replace("\n", "\r\n").encode(), id="crlf"),
    pytest.param(lambda text: text.replace("\n", "\r").encode(), id="lone-cr"),
    pytest.param(lambda text: "\N{BYTE ORDER MARK}".encode() + text.encode(), id="bom"),
]
