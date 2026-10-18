from typing import Any

from bundesarchiv.domain.models import ULID, Article, Lifecycle


def make_article(
    ulid: str,
    *,
    collection_id: str,
    title: str = "Testartikel",
    lifecycle: Lifecycle = Lifecycle.PUBLISHED,
    **overrides: Any,
) -> Article:
    """An Article its audience can see — pass only what the test asserts about. ``Article`` itself
    defaults to DRAFT (archivist-only), so a row meant for other viewers would silently vanish."""
    return Article(
        ulid=ULID(ulid),
        title=title,
        collection_id=ULID(collection_id),
        lifecycle=lifecycle,
        **overrides,
    )
