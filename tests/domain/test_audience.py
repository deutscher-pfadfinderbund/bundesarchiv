"""Effective-Audience resolver — the single, leak-sensitive source (ADR 0001).

Fixture-driven, no IO: small Collection chains and Articles built in-memory and injected.
The chain is leaf-first (the Article's own Collection at index 0), as resolve_chain returns.
"""

import pytest

from bundesarchiv.domain.audience import ArchivistOnly, effective_audience
from bundesarchiv.domain.errors import MisresolvedChain
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)


def _article(
    *,
    audience: Audience | None = None,
    lifecycle: Lifecycle = Lifecycle.PUBLISHED,
    collection_id: str = "c-leaf",
) -> Article:
    return Article(
        ulid="01J0",
        title="Zeltlager 1955",
        collection_id=collection_id,
        lifecycle=lifecycle,
        audience=audience,
    )


def _coll(
    ulid: str, *, parent_id: str | None = None, audience: Audience | None = None
) -> Collection:
    return Collection(ulid=ulid, name=ulid, parent_id=parent_id, audience=audience)


def test_published_article_with_explicit_audience_resolves_to_that_rung() -> None:
    public = Audience(AudienceTier.PUBLIC)
    article = _article(audience=public)
    chain = (_coll("c-leaf"),)
    assert effective_audience(article, chain) == public


def test_lifecycle_gate_makes_a_non_published_article_archivist_only() -> None:
    # A Public *Draft* is Archivist-only: the Lifecycle gate overrides Audience entirely.
    article = _article(audience=Audience(AudienceTier.PUBLIC), lifecycle=Lifecycle.DRAFT)
    chain = (_coll("c-leaf"),)
    assert effective_audience(article, chain) == ArchivistOnly()


def test_empty_chain_is_rejected_not_silently_defaulted() -> None:
    # An inherit Article with an empty chain must NOT fall through to root-default
    # Members (a latent over-exposure). It is a caller bug — fail loud, fail closed.
    article = _article(audience=None)
    with pytest.raises(MisresolvedChain):
        effective_audience(article, ())


def test_chain_whose_leaf_is_not_the_articles_collection_is_rejected() -> None:
    # The chain must be *this* Article's resolved chain; a mismatched leaf is a wiring bug.
    article = _article(collection_id="c-leaf", audience=Audience(AudienceTier.PUBLIC))
    wrong_chain = (_coll("c-other"),)
    with pytest.raises(MisresolvedChain):
        effective_audience(article, wrong_chain)


def test_inherit_article_falls_through_an_empty_leaf_to_the_nearest_ancestor() -> None:
    # Article inherits, its own Collection is silent → take the nearest ancestor's explicit.
    public = Audience(AudienceTier.PUBLIC)
    chain = (_coll("c-leaf", parent_id="c-root"), _coll("c-root", audience=public))
    assert effective_audience(_article(audience=None), chain) == public


def test_nearest_explicit_wins_over_a_more_distant_one() -> None:
    # Both leaf and root are explicit → the *nearest* (leaf) wins, not the root.
    leaf_rung = Audience(AudienceTier.GROUPS, ("bundesfuehrung",))
    chain = (
        _coll("c-leaf", parent_id="c-root", audience=leaf_rung),
        _coll("c-root", audience=Audience(AudienceTier.PUBLIC)),
    )
    assert effective_audience(_article(audience=None), chain) == leaf_rung


def test_silent_chain_falls_back_to_the_root_default_members() -> None:
    # Article inherits and the whole chain is silent → root default Members.
    chain = (_coll("c-leaf", parent_id="c-root"), _coll("c-root"))
    assert effective_audience(_article(audience=None), chain) == Audience(AudienceTier.MEMBERS)


def test_explicit_article_audience_may_widen_a_narrower_collection() -> None:
    # ADR 0001: the Article-level Audience wins and MAY WIDEN — a Public Article under a
    # Members Collection resolves to Public, not clamped down to Members.
    public = Audience(AudienceTier.PUBLIC)
    chain = (_coll("c-leaf", audience=Audience(AudienceTier.MEMBERS)),)
    assert effective_audience(_article(audience=public), chain) == public


def test_truncated_chain_silent_leaf_is_rejected_not_defaulted_to_members() -> None:
    # A silent leaf that names a parent but whose chain stops at the leaf is NOT a root:
    # falling through to root-default Members would widen a possibly-narrower ancestor.
    # The chain must reach a real root (parent_id is None) — else fail closed.
    chain = (_coll("c-leaf", parent_id="c-mid"),)
    with pytest.raises(MisresolvedChain):
        effective_audience(_article(audience=None), chain)


def test_spliced_chain_with_a_disconnected_parent_is_rejected() -> None:
    # chain[1] is not chain[0]'s parent — an unrelated Collection spliced in. Returning
    # its rung would expose the Article to a tier from a Collection it does not belong to.
    chain = (
        _coll("c-leaf", parent_id="c-true-parent"),
        _coll("c-root", audience=Audience(AudienceTier.PUBLIC)),
    )
    with pytest.raises(MisresolvedChain):
        effective_audience(_article(audience=None), chain)


def test_misresolved_chain_is_rejected_even_for_a_non_published_article() -> None:
    # Pins guard-before-gate ordering: a DRAFT with a bad chain must RAISE, not be
    # silently swallowed into ArchivistOnly by an early Lifecycle gate (a wiring bug).
    draft = _article(audience=None, lifecycle=Lifecycle.DRAFT)
    with pytest.raises(MisresolvedChain):
        effective_audience(draft, ())
    with pytest.raises(MisresolvedChain):
        effective_audience(draft, (_coll("c-other"),))


def test_nearest_explicit_ancestor_wins_in_a_deep_chain() -> None:
    # 3-deep: the explicit MIDDLE Collection wins over a different, more distant root —
    # proving the walk truly stops at the first explicit ancestor (not chain[-1]/two-ended).
    public = Audience(AudienceTier.PUBLIC)
    chain = (
        _coll("c-leaf", parent_id="c-mid"),
        _coll("c-mid", parent_id="c-root", audience=public),
        _coll("c-root", audience=Audience(AudienceTier.MEMBERS)),
    )
    assert effective_audience(_article(audience=None), chain) == public
