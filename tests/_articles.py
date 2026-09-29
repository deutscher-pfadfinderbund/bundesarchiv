"""The Article builder both the web and the index suites use."""

from typing import Any

from bundesarchiv.domain.models import Article, Lifecycle, Ulid


def make_article(
    ulid: Ulid,
    *,
    collection_id: Ulid,
    title: str = "Testartikel",
    lifecycle: Lifecycle = Lifecycle.PUBLISHED,
    **overrides: Any,
) -> Article:
    """An Article its audience can see — pass only what the test asserts about. ``Article`` itself
    defaults to DRAFT (archivist-only), so a row meant for other viewers would silently vanish."""
    return Article(
        ulid=ulid, title=title, collection_id=collection_id, lifecycle=lifecycle, **overrides
    )
