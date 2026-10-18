from datetime import UTC, datetime

import pytest

from bundesarchiv.domain.identity import create_article, is_valid_ulid
from bundesarchiv.domain.models import ULID, Lifecycle

_CANONICAL = "01KW2SAZ9BAFT2PABHSGPR2KJM"


def test_is_valid_ulid_accepts_the_canonical_spelling() -> None:
    assert is_valid_ulid(_CANONICAL)


@pytest.mark.parametrize(
    "value",
    [
        "",
        _CANONICAL[:-1],
        _CANONICAL + "0",
        _CANONICAL.lower(),
        *(_CANONICAL[:-1] + letter for letter in "ILOU"),  # outside Crockford base32
        "8" + _CANONICAL[1:],  # beyond 128 bits
        f" {_CANONICAL}",
        f"{_CANONICAL}\n",
        "../x",
        "a/b",
        "../" + _CANONICAL[3:],
        _CANONICAL[:12] + "/" + _CANONICAL[13:],
    ],
)
def test_is_valid_ulid_rejects_every_other_string(value: str) -> None:
    assert is_valid_ulid(value) is False


@pytest.mark.parametrize("value", [None, 0, _CANONICAL.encode(), [_CANONICAL]])
def test_is_valid_ulid_is_false_on_a_non_str(value: object) -> None:
    assert is_valid_ulid(value) is False


def test_create_article_mints_a_valid_unique_ulid() -> None:
    article = create_article(title="Zeltlager 1955", collection_id=ULID("coll-fotos"))
    assert is_valid_ulid(article.ulid)
    assert article.title == "Zeltlager 1955"
    assert article.collection_id == "coll-fotos"
    assert article.lifecycle is Lifecycle.DRAFT  # a new Article starts as a Draft
    assert article.audience is None  # inherit by default
    assert create_article(title="x", collection_id=ULID("c")).ulid != article.ulid  # minted fresh


def test_a_new_article_is_added_now() -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    added_at = create_article(title="x", collection_id=ULID("c")).added_at
    assert added_at is not None
    assert before <= added_at <= datetime.now(UTC)
