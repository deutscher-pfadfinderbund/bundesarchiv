"""The effective-Audience resolver, the single source of every visibility decision (ADR 0001)."""

from dataclasses import dataclass
from typing import assert_never

from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.errors import MisresolvedChain
from bundesarchiv.domain.models import Article, Aspect, Audience, Lifecycle


@dataclass(frozen=True, slots=True)
class ArchivistOnly:
    """The effective Audience of any non-Published or deleted Article: only Archivists may see it.
    This is *not* a rung on the Public ⊃ Members ⊃ Groups ladder — it sits strictly above
    it, so it is its own type rather than an AudienceTier value."""


type EffectiveAudience = Audience | ArchivistOnly

ARCHIVIST_ONLY = ArchivistOnly()


def effective_audience(
    article: Article, chain: ResolvedChain, aspect: Aspect = Aspect.RECORD
) -> EffectiveAudience:
    """The nearest explicit Audience for `aspect` wins, even where it widens an ancestor's; an
    aspect with none takes the record's (ADR 0027)."""
    if chain.leaf.ulid != article.collection_id:
        raise MisresolvedChain(
            f"chain is not rooted at Article {article.ulid!r}'s Collection "
            f"(collection_id={article.collection_id!r}, chain leaf={chain.leaf.ulid!r})"
        )
    if article.lifecycle is not Lifecycle.PUBLISHED or article.deleted is not None:
        return ARCHIVIST_ONLY
    match aspect:
        case Aspect.RECORD:
            return _record_audience(article, chain)
        case Aspect.FILES:
            if article.files_audience is not None:
                return article.files_audience
            return _record_audience(article, chain)
        case _ as unreachable:
            assert_never(unreachable)


def _record_audience(article: Article, chain: ResolvedChain) -> Audience:
    if article.audience is not None:
        return article.audience
    for collection in chain.collections:
        if collection.audience is not None:
            return collection.audience
    return Audience()  # whole chain silent → root default Members
