"""Effective-Audience resolver — the single, leak-sensitive source (ADR 0001).

Fixture-driven, no IO. Chains are `ResolvedChain`s (leaf-first); their structural invariant
is tested in test_collections.py. Here we test the resolver's own logic: the article-binding
check, the Lifecycle gate, the nearest-explicit cascade, and the root default.
"""

import pytest

from bundesarchiv.domain.audience import ArchivistOnly, effective_audience
from bundesarchiv.domain.collections import ResolvedChain
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


def _chain(*collections: Collection) -> ResolvedChain:
    return ResolvedChain(collections)


def test_published_article_with_explicit_audience_resolves_to_that_rung() -> None:
    public = Audience(AudienceTier.PUBLIC)
    assert effective_audience(_article(audience=public), _chain(_coll("c-leaf"))) == public


def test_lifecycle_gate_makes_a_non_published_article_archivist_only() -> None:
    # A Public *Draft* is Archivist-only: the Lifecycle gate overrides Audience entirely.
    article = _article(audience=Audience(AudienceTier.PUBLIC), lifecycle=Lifecycle.DRAFT)
    assert effective_audience(article, _chain(_coll("c-leaf"))) == ArchivistOnly()


def test_chain_resolved_for_a_different_article_is_rejected() -> None:
    # The chain is structurally valid but its leaf is not THIS Article's Collection — a
    # wiring bug. The binding check fails closed (MisresolvedChain).
    article = _article(collection_id="c-leaf", audience=Audience(AudienceTier.PUBLIC))
    with pytest.raises(MisresolvedChain):
        effective_audience(article, _chain(_coll("c-other")))


def test_binding_check_runs_before_the_lifecycle_gate() -> None:
    # Pins guard-before-gate: a DRAFT with a mismatched chain must RAISE, not be silently
    # swallowed into ArchivistOnly by an early gate.
    draft = _article(collection_id="c-leaf", audience=None, lifecycle=Lifecycle.DRAFT)
    with pytest.raises(MisresolvedChain):
        effective_audience(draft, _chain(_coll("c-other")))


def test_inherit_article_falls_through_an_empty_leaf_to_the_nearest_ancestor() -> None:
    public = Audience(AudienceTier.PUBLIC)
    chain = _chain(_coll("c-leaf", parent_id="c-root"), _coll("c-root", audience=public))
    assert effective_audience(_article(audience=None), chain) == public


def test_nearest_explicit_wins_over_a_more_distant_one() -> None:
    leaf_rung = Audience(AudienceTier.GROUPS, ("bundesfuehrung",))
    chain = _chain(
        _coll("c-leaf", parent_id="c-root", audience=leaf_rung),
        _coll("c-root", audience=Audience(AudienceTier.PUBLIC)),
    )
    assert effective_audience(_article(audience=None), chain) == leaf_rung


def test_nearest_explicit_ancestor_wins_in_a_deep_chain() -> None:
    # 3-deep: the explicit MIDDLE Collection wins over a different, more distant root.
    public = Audience(AudienceTier.PUBLIC)
    chain = _chain(
        _coll("c-leaf", parent_id="c-mid"),
        _coll("c-mid", parent_id="c-root", audience=public),
        _coll("c-root", audience=Audience(AudienceTier.MEMBERS)),
    )
    assert effective_audience(_article(audience=None), chain) == public


def test_silent_chain_falls_back_to_the_root_default_members() -> None:
    chain = _chain(_coll("c-leaf", parent_id="c-root"), _coll("c-root"))
    assert effective_audience(_article(audience=None), chain) == Audience(AudienceTier.MEMBERS)


def test_explicit_article_audience_may_widen_a_narrower_collection() -> None:
    # ADR 0001: the Article-level Audience wins and MAY WIDEN — a Public Article under a
    # Members Collection resolves to Public, not clamped down to Members.
    public = Audience(AudienceTier.PUBLIC)
    chain = _chain(_coll("c-leaf", audience=Audience(AudienceTier.MEMBERS)))
    assert effective_audience(_article(audience=public), chain) == public
