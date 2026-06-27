"""domain.identity — ULID minting/validation and the display-slug helper."""

import pytest

from bundesarchiv.domain.identity import create_article, is_valid_ulid, new_ulid, slugify
from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle


def test_new_ulid_is_a_valid_unique_26_char_ulid() -> None:
    a, b = new_ulid(), new_ulid()
    assert len(a) == 26
    assert is_valid_ulid(a)
    assert a != b  # minted fresh each call


@pytest.mark.parametrize("value", ["", "not-a-ulid", "01J0", "z" * 26, "01KW2SAZ9BAFT2PABHSGPR2KJ"])
def test_is_valid_ulid_rejects_malformed(value: str) -> None:
    assert is_valid_ulid(value) is False


def test_is_valid_ulid_accepts_a_minted_one() -> None:
    assert is_valid_ulid(new_ulid()) is True


def test_is_valid_ulid_is_total_on_non_str() -> None:
    # A predicate named is_valid_* must return False, not raise, on a non-str (an
    # untyped caller parsing a README field to None).
    assert is_valid_ulid(None) is False  # type: ignore[arg-type]


def test_create_article_mints_a_valid_unique_ulid() -> None:
    article = create_article(title="Zeltlager 1955", collection_id="coll-fotos")
    assert is_valid_ulid(article.ulid)
    assert article.title == "Zeltlager 1955"
    assert article.collection_id == "coll-fotos"
    assert article.lifecycle is Lifecycle.DRAFT  # a new Article starts as a Draft
    assert article.audience is None  # inherit by default
    assert create_article(title="x", collection_id="c").ulid != article.ulid  # minted fresh


def test_create_article_passes_through_optional_fields() -> None:
    article = create_article(
        title="t",
        collection_id="c",
        lifecycle=Lifecycle.PUBLISHED,
        audience=Audience(AudienceTier.PUBLIC),
        ref_code="Foto-1955/007",
    )
    assert article.lifecycle is Lifecycle.PUBLISHED
    assert article.audience == Audience(AudienceTier.PUBLIC)
    assert article.ref_code == "Foto-1955/007"


def test_create_article_carries_custom_metadata() -> None:
    article = create_article(title="t", collection_id="c", custom=(("herkunft", "x"),))
    assert article.custom == (("herkunft", "x"),)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Zeltlager 1955", "zeltlager-1955"),
        ("  Hello, World!  ", "hello-world"),  # trims + collapses separators
        ("Café Grün", "cafe-grun"),  # accents → base letter
        ("Schwarz-Weiß Foto", "schwarz-wei-foto"),  # ß has no ASCII base → dropped
        ("Foto-1955/007", "foto-1955-007"),  # a ref_code shape
        ("", ""),
        ("你好", ""),  # nothing ASCII → empty slug
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected
