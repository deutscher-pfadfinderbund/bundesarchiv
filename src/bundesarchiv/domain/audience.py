"""The effective-Audience resolver — the single, pure, leak-sensitive source (ADR 0001).

Every visibility decision (list filters, detail authorization, the search-index filter,
the publish-time preview) must route an Article through *this* function and nowhere else;
duplicating the logic is the top data-leak risk. Pure: no IO, no framework; the Collection
chain is injected as a `ResolvedChain` (already built + structurally validated by
`collections.resolve_chain`), never fetched here.
"""

from dataclasses import dataclass

from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.errors import MisresolvedChain
from bundesarchiv.domain.models import Article, Audience, Lifecycle


@dataclass(frozen=True, slots=True)
class ArchivistOnly:
    """The effective Audience of any non-Published Article: only Archivists may see it.
    This is *not* a rung on the Public ⊃ Members ⊃ Groups ladder — it sits strictly above
    it, so it is its own type rather than an AudienceTier value."""


type EffectiveAudience = Audience | ArchivistOnly

ARCHIVIST_ONLY = ArchivistOnly()  # frozen + field-less, so this singleton is shareable


def effective_audience(article: Article, chain: ResolvedChain) -> EffectiveAudience:
    """Resolve the one effective Audience for `article` given its resolved Collection chain.

    `ResolvedChain` guarantees the chain is non-empty, parent-linked, and root-terminated, so
    the only check left here is the *binding*: the chain's leaf must be the Article's own
    Collection (a chain resolved for a different Article is a caller wiring bug → fail closed,
    `MisresolvedChain`). Then the Lifecycle gate wins first (a non-Published Article is
    Archivist-only); otherwise the nearest explicit Audience walking Article → chain wins (it
    may *widen* an ancestor, not only narrow), falling back to the root default Members.
    """
    if chain.leaf.ulid != article.collection_id:
        raise MisresolvedChain(
            f"chain is not rooted at Article {article.ulid!r}'s Collection "
            f"(collection_id={article.collection_id!r}, chain leaf={chain.leaf.ulid!r})"
        )
    if article.lifecycle is not Lifecycle.PUBLISHED:
        return ARCHIVIST_ONLY  # the Lifecycle gate overrides Audience entirely
    if article.audience is not None:
        return article.audience  # explicit Article-level Audience wins, and may widen
    for collection in chain.collections:  # leaf → root: nearest explicit ancestor Audience wins
        if collection.audience is not None:
            return collection.audience
    return Audience()  # whole chain silent → root default Members
