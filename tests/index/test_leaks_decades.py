"""Own corpus: a decade carried only by a restricted row cannot exist in the shared one, whose
open-ended ``ART_PUBPLAKAT`` puts a public row in every decade from 1970 on.
"""

from collections.abc import Iterator

import pytest
from tests.index import fixtures

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    ULID,
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.domain.viewer import Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

PUBLIC = Public()
PLAIN_MEMBER = Member(())

_DEC_ROOT = ULID("DEC_ROOT")
_DEC_MEMBER_ULID = ULID("DEC_MEMBER_1810")  # MEMBERS-tier, decade 1810 (tier-exclusive)
_DEC_PUBLIC_ULID = ULID("DEC_PUBLIC_1820")  # PUBLIC-tier, decade 1820


def _build_decade_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(
        Collection(ulid=_DEC_ROOT, name="Dekaden-Wurzel", parent_id=None), 0, changed_by="tester"
    )
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
        changed_by="tester",
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
        changed_by="tester",
    )
    return store


def _build_indexed() -> indexer.RebuildReport:
    return indexer.rebuild(_build_decade_store())


@pytest.fixture(scope="module")
def _decade_indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
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
    assert "1810" not in _facet_values(PUBLIC, "decades")
    assert "1820" in _facet_values(PUBLIC, "decades")  # the public row's own decade is present
    assert _facet_count(PLAIN_MEMBER, "decades", "1810") == 1
    assert _facet_count(PLAIN_MEMBER, "decades", "1820") == 1


@pytest.mark.django_db
def test_member_only_decade_row_absent_from_public_hits_and_total(decade_corpus: None) -> None:
    public_hits = {hit.ulid for hit in search(PUBLIC, page_size=200).hits}
    assert _DEC_MEMBER_ULID not in public_hits
    assert search(PUBLIC, page_size=200).total == 1  # only the public 1820 row
