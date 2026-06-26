"""README codec — Article ⇄ front-matter bytes, tested directly (no store, no repo)."""

import pytest

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
    ],
)
def test_decode_rejects_corrupt_readme_as_archive_error(text: str, why: str) -> None:
    with pytest.raises(ArchiveError):
        readme.decode("x", text)


def test_read_version_rejects_corrupt_as_archive_error() -> None:
    with pytest.raises(ArchiveError):
        readme.read_version("x", "---\ntags: [unclosed\n---\n")
