"""The effective-Audience resolver — the single, pure, leak-sensitive source (ADR 0001).

Every visibility decision (list filters, detail authorization, the search-index filter,
the publish-time preview) must route an Article through *this* function and nowhere else;
duplicating the logic is the top data-leak risk. Pure: no IO, no framework; the Collection
chain is injected (already resolved by `collections.resolve_chain`), never fetched here.
"""

from dataclasses import dataclass
from itertools import pairwise

from bundesarchiv.domain.errors import MisresolvedChain
from bundesarchiv.domain.models import Article, Audience, Collection, Lifecycle


@dataclass(frozen=True, slots=True)
class ArchivistOnly:
    """The effective Audience of any non-Published Article: only Archivists may see it.
    This is *not* a rung on the Public ⊃ Members ⊃ Groups ladder — it sits strictly above
    it, so it is its own type rather than an AudienceTier value."""


type EffectiveAudience = Audience | ArchivistOnly

ARCHIVIST_ONLY = ArchivistOnly()  # frozen + field-less, so this singleton is shareable


def _require_articles_chain(article: Article, chain: tuple[Collection, ...]) -> None:
    """Fail closed unless `chain` is a usable owning chain for `article`: non-empty, rooted
    at the Article's own Collection, parent-linked leaf→root, and terminated at a real root.

    Validating only the leaf would let a *truncated* chain fall through to the root-default
    Members (widening a narrower ancestor) or a *spliced* chain return an unrelated rung —
    both silent over-exposures. A malformed chain is a caller wiring bug, surfaced loud.

    `collections.resolve_chain` already emits parent-linked, root-terminated chains, so the
    structural checks here are defense-in-depth for this leak-sensitive seam's other/future
    callers (search-index, preview) — not redundancy against that one producer."""
    if not chain or chain[0].ulid != article.collection_id:
        leaf = chain[0].ulid if chain else None
        raise MisresolvedChain(
            f"chain is not rooted at Article {article.ulid!r}'s Collection "
            f"(collection_id={article.collection_id!r}, chain leaf={leaf!r})"
        )
    for child, parent in pairwise(chain):
        if child.parent_id != parent.ulid:
            raise MisresolvedChain(
                f"chain is not parent-linked: {child.ulid!r}.parent_id="
                f"{child.parent_id!r} but next is {parent.ulid!r}"
            )
    if chain[-1].parent_id is not None:
        raise MisresolvedChain(
            f"chain does not terminate at a root: {chain[-1].ulid!r}.parent_id="
            f"{chain[-1].parent_id!r}"
        )


def effective_audience(article: Article, chain: tuple[Collection, ...]) -> EffectiveAudience:
    """Resolve the one effective Audience for `article` given its resolved Collection
    `chain` (leaf-first, root-last, as `collections.resolve_chain` returns it).

    The Lifecycle gate wins first (a non-Published Article is Archivist-only); otherwise
    the nearest explicit Audience walking Article → chain wins (it may *widen* an ancestor,
    not only narrow), falling back to the root default of Members when the whole chain is
    silent. Raises `MisresolvedChain` if `chain` is not this Article's resolved chain.
    """
    _require_articles_chain(article, chain)
    if article.lifecycle is not Lifecycle.PUBLISHED:
        return ARCHIVIST_ONLY  # the Lifecycle gate overrides Audience entirely
    if article.audience is not None:
        return article.audience  # explicit Article-level Audience wins, and may widen
    for collection in chain:  # leaf → root: the nearest explicit ancestor Audience wins
        if collection.audience is not None:
            return collection.audience
    return Audience()  # whole chain silent → root default Members
