"""Decade facet-leak differential (controller #3, decade half) — its own module + corpus.

The tag half of the differential facet-leak guard lives in ``test_leaks.py`` on the shared corpus.
The decade half needs a decade carried by ONLY a restricted row, which the shared corpus can't give:
its open-ended ``ART_PUBPLAKAT`` (1970/..) puts a *public* row in every decade from 1970 on, so no
decade there is tier-exclusive. This module builds a dedicated two-row corpus where one decade sits
only on a member-only row.

It is a SEPARATE module (not another fixture in ``test_leaks.py``) because ``indexer.rebuild`` is
destructive — it wipes the whole ``ArticleIndex`` table — so two module-scoped corpora cannot
coexist in one module's shared table. Across modules each module-scoped fixture rebuilds on first
use, so ordering stays deterministic; within a module it would not.
"""

from collections.abc import Iterator

import pytest
from tests.index import fixtures

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.domain.viewer import Member, Public, Viewer
from bundesarchiv.index import indexer, search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

# Viewers this module needs: Public (must NOT see the member-only decade) and a plain Member (must).
PUBLIC = Public()
PLAIN_MEMBER = Member(())  # a groupless Member

_DEC_ROOT = "DEC_ROOT"
_DEC_MEMBER_ULID = "DEC_MEMBER_1810"  # MEMBERS-tier, decade 1810 (tier-exclusive)
_DEC_PUBLIC_ULID = "DEC_PUBLIC_1820"  # PUBLIC-tier, decade 1820


def _build_decade_store() -> InMemoryObjectStore:
    """A two-article corpus isolating a decade on a member-only row: a MEMBERS article dated 1815
    (decade 1810) and a PUBLIC article dated 1825 (decade 1820). No public row touches 1810, so
    that decade is a clean member-exclusive facet value; the public row's own 1820 stays visible so
    the test distinguishes 'scoped out' from 'empty index'."""
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(Collection(ulid=_DEC_ROOT, name="Dekaden-Wurzel", parent_id=None))
    articles.save(
        Article(
            ulid=_DEC_MEMBER_ULID,
            title="Mitgliederdokument mit seltener Dekade",
            collection_id=_DEC_ROOT,
            lifecycle=Lifecycle.PUBLISHED,
            audience=Audience(AudienceTier.MEMBERS),
            date=EdtfDate("1815"),
        ),
        0,
    )
    articles.save(
        Article(
            ulid=_DEC_PUBLIC_ULID,
            title="Öffentliches Dokument",
            collection_id=_DEC_ROOT,
            lifecycle=Lifecycle.PUBLISHED,
            audience=Audience(AudienceTier.PUBLIC),
            date=EdtfDate("1825"),
        ),
        0,
    )
    return store


def _build_indexed() -> indexer.RebuildReport:
    return indexer.rebuild(_build_decade_store())


@pytest.fixture(scope="module")
def _decade_indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
    """Build + index the dedicated decade corpus once for the whole module (search is read-only),
    routed through ``fixtures.indexed_corpus`` — the single isolation mechanism, which wipes the
    table on module teardown so the committed corpus never leaks into a later module."""
    yield from fixtures.indexed_corpus(django_db_blocker, _build_indexed)


@pytest.fixture
def decade_corpus(_decade_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed decade corpus to the ``db`` transaction fixture."""


def _facet_values(viewer: Viewer, key: str) -> set[str]:
    return {fc.value for fc in search(viewer, page_size=200).facets[key]}


def _facet_count(viewer: Viewer, key: str, value: str) -> int:
    facets = search(viewer, page_size=200).facets[key]
    return next((fc.count for fc in facets if fc.value == value), 0)


@pytest.mark.django_db
def test_member_only_decade_absent_from_public_facets(decade_corpus: None) -> None:
    """Decade 1810 is carried ONLY by the member-only row: absent from Public's decade facet,
    present (count 1) for a Member. Public still sees its own 1820 decade, so this is a scope
    difference, not an empty index."""
    assert "1810" not in _facet_values(PUBLIC, "decades")
    assert "1820" in _facet_values(PUBLIC, "decades")  # the public row's own decade is present
    assert _facet_count(PLAIN_MEMBER, "decades", "1810") == 1
    assert _facet_count(PLAIN_MEMBER, "decades", "1820") == 1


@pytest.mark.django_db
def test_member_only_decade_row_absent_from_public_hits_and_total(decade_corpus: None) -> None:
    """Belt-and-braces: the same row is absent from Public's hits and total too, so the facet
    absence above is not masking a hit-level leak."""
    public_hits = {hit.ulid for hit in search(PUBLIC, page_size=200).hits}
    assert _DEC_MEMBER_ULID not in public_hits
    assert search(PUBLIC, page_size=200).total == 1  # only the public 1820 row
