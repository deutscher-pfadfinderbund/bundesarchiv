"""domain.identity — ULID minting/validation and the display-slug helper."""

from datetime import UTC, datetime

import pytest

from bundesarchiv.domain.identity import create_article, is_valid_ulid
from bundesarchiv.domain.models import Lifecycle


@pytest.mark.parametrize("value", ["", "not-a-ulid", "01J0", "z" * 26, "01KW2SAZ9BAFT2PABHSGPR2KJ"])
def test_is_valid_ulid_rejects_malformed(value: str) -> None:
    assert is_valid_ulid(value) is False


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


def test_a_new_article_is_added_now() -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    added_at = create_article(title="x", collection_id="c").added_at
    assert added_at is not None
    assert before <= added_at <= datetime.now(UTC)
