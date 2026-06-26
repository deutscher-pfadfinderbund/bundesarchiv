"""The effective-Audience resolver — the single, pure, leak-sensitive source (ADR 0001).

Every visibility decision (list filters, detail authorization, the search-index filter,
the publish-time preview) must route an Article through *this* function and nowhere else;
duplicating the logic is the top data-leak risk. Pure: no IO, no framework; the Collection
chain is injected (already resolved by `collections.resolve_chain`), never fetched here.
"""

from dataclasses import dataclass

from bundesarchiv.domain.errors import MisresolvedChain
from bundesarchiv.domain.models import Article, Audience, Collection, Lifecycle


@dataclass(frozen=True, slots=True)
class ArchivistOnly:
    """The effective Audience of any non-Published Article: only Archivists may see it.
    This is *not* a rung on the Public ⊃ Members ⊃ Groups ladder — it sits strictly above
    it, so it is its own type rather than an AudienceTier value."""


type EffectiveAudience = Audience | ArchivistOnly

ARCHIVIST_ONLY = ArchivistOnly()  # frozen + field-less, so this singleton is shareable


def effective_audience(article: Article, chain: tuple[Collection, ...]) -> EffectiveAudience:
    """Resolve the one effective Audience for `article` given its resolved Collection
    `chain` (leaf-first, root-last, as `collections.resolve_chain` returns it).

    The Lifecycle gate wins first (a non-Published Article is Archivist-only); otherwise
    the nearest explicit Audience walking Article → chain wins (it may *widen* an ancestor,
    not only narrow), falling back to the root default of Members when the whole chain is
    silent. Raises `MisresolvedChain` if `chain` is not this Article's resolved chain.
    """
    if not chain or chain[0].ulid != article.collection_id:
        leaf = chain[0].ulid if chain else None
        raise MisresolvedChain(
            f"chain is not the resolved chain for Article {article.ulid!r} "
            f"(collection_id={article.collection_id!r}, chain leaf={leaf!r})"
        )
    if article.lifecycle is not Lifecycle.PUBLISHED:
        return ARCHIVIST_ONLY  # the Lifecycle gate overrides Audience entirely
    if article.audience is not None:
        return article.audience  # explicit Article-level Audience wins, and may widen
    for collection in chain:  # leaf → root: the nearest explicit ancestor Audience wins
        if collection.audience is not None:
            return collection.audience
    return Audience()  # whole chain silent → root default Members
