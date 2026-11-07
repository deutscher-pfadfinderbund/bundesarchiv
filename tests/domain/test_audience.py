"""``effective_audience``, fail-closed (ADR 0001)."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from bundesarchiv.domain.audience import ArchivistOnly, effective_audience
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.errors import MisresolvedChain
from bundesarchiv.domain.models import (
    ULID,
    Article,
    Aspect,
    Audience,
    AudienceTier,
    Change,
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
        ulid=ULID("01J0"),
        title="Zeltlager 1955",
        collection_id=ULID(collection_id),
        lifecycle=lifecycle,
        audience=audience,
    )


def _coll(
    ulid: str, *, parent_id: str | None = None, audience: Audience | None = None
) -> Collection:
    parent = None if parent_id is None else ULID(parent_id)
    return Collection(ulid=ULID(ulid), name=ulid, parent_id=parent, audience=audience)


def _chain(*collections: Collection) -> ResolvedChain:
    return ResolvedChain(collections)


def test_published_article_with_explicit_audience_resolves_to_that_rung() -> None:
    public = Audience(AudienceTier.PUBLIC)
    assert effective_audience(_article(audience=public), _chain(_coll("c-leaf"))) == public


def test_lifecycle_gate_makes_a_non_published_article_archivist_only() -> None:
    article = _article(audience=Audience(AudienceTier.PUBLIC), lifecycle=Lifecycle.DRAFT)
    assert effective_audience(article, _chain(_coll("c-leaf"))) == ArchivistOnly()


def test_a_marked_article_is_archivist_only_whatever_its_audience() -> None:
    # ADR 0022: a Public, Published Article in the Papierkorb.
    marked = replace(
        _article(audience=Audience(AudienceTier.PUBLIC)),
        deleted=Change(datetime(2026, 9, 30, tzinfo=UTC), "anna"),
    )
    assert effective_audience(marked, _chain(_coll("c-leaf"))) == ArchivistOnly()


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
    # by design (ADR 0001)
    public = Audience(AudienceTier.PUBLIC)
    chain = _chain(_coll("c-leaf", audience=Audience(AudienceTier.MEMBERS)))
    assert effective_audience(_article(audience=public), chain) == public


# --- The FILES aspect (ADR 0027) ----------------------------------------------------------------

_BOARD = Audience(AudienceTier.GROUPS, ("vorstand",))


def test_an_unset_files_rung_resolves_to_the_effective_record_rung() -> None:
    # Through a Collection's explicit record rung, not only the Article's own.
    chain = _chain(_coll("c-leaf", parent_id="c-root"), _coll("c-root", audience=_BOARD))
    assert effective_audience(_article(), chain, Aspect.FILES) == _BOARD


def test_an_explicit_files_rung_resolves_to_itself_and_leaves_the_record_alone() -> None:
    article = replace(_article(audience=Audience(AudienceTier.PUBLIC)), files_audience=_BOARD)
    chain = _chain(_coll("c-leaf"))
    assert effective_audience(article, chain, Aspect.FILES) == _BOARD
    assert effective_audience(article, chain) == Audience(AudienceTier.PUBLIC)


@pytest.mark.parametrize(
    "gated",
    [
        _article(lifecycle=Lifecycle.DRAFT),
        replace(_article(), deleted=Change(datetime(2026, 9, 30, tzinfo=UTC), "anna")),
    ],
)
def test_the_lifecycle_gate_makes_the_files_archivist_only(gated: Article) -> None:
    article = replace(gated, files_audience=Audience(AudienceTier.PUBLIC))
    assert effective_audience(article, _chain(_coll("c-leaf")), Aspect.FILES) == ArchivistOnly()


def test_the_binding_check_runs_for_the_files_too() -> None:
    article = replace(_article(), files_audience=Audience(AudienceTier.PUBLIC))
    with pytest.raises(MisresolvedChain):
        effective_audience(article, _chain(_coll("c-other")), Aspect.FILES)
