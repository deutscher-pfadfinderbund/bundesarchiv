"""The effective-Audience resolver: the single source every visibility decision routes
through (ADR 0001). Never duplicate it. Pure; the chain is injected."""

from dataclasses import dataclass

from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.errors import MisresolvedChain
from bundesarchiv.domain.models import Article, Audience, Lifecycle


@dataclass(frozen=True, slots=True)
class ArchivistOnly:
    """The effective Audience of any non-Published or deleted Article: only Archivists may see it.
    This is *not* a rung on the Public ⊃ Members ⊃ Groups ladder — it sits strictly above
    it, so it is its own type rather than an AudienceTier value."""


type EffectiveAudience = Audience | ArchivistOnly

ARCHIVIST_ONLY = ArchivistOnly()


def effective_audience(article: Article, chain: ResolvedChain) -> EffectiveAudience:
    """The one effective Audience of `article`: Archivist-only unless Published and not in the
    Papierkorb (ADR 0022); otherwise the nearest explicit Audience, Article first, then leaf to
    root (it may widen an ancestor's); otherwise Members. Raises `MisresolvedChain` if `chain`
    is not this Article's."""
    if chain.leaf.ulid != article.collection_id:
        raise MisresolvedChain(
            f"chain is not rooted at Article {article.ulid!r}'s Collection "
            f"(collection_id={article.collection_id!r}, chain leaf={chain.leaf.ulid!r})"
        )
    if article.lifecycle is not Lifecycle.PUBLISHED or article.deleted is not None:
        return ARCHIVIST_ONLY
    if article.audience is not None:
        return article.audience
    for collection in chain.collections:  # leaf → root: nearest explicit ancestor Audience wins
        if collection.audience is not None:
            return collection.audience
    return Audience()  # whole chain silent → root default Members
