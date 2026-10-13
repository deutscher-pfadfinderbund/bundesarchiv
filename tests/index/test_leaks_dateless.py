"""Own corpus: the shared one dates every article, so it has no tier-exclusive dateless row."""

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
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import SearchFilters, search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

PUBLIC = Public()
PLAIN_MEMBER = Member(())
ARCHIVIST = Archivist()

_DL_ROOT = "DL_ROOT"
_DL_PUBLIC_DATED = "DL_PUBLIC_DATED"  # PUBLIC, has a date (the "index isn't empty" anchor)
_DL_PUBLIC_NODATE = "DL_PUBLIC_NODATE"  # PUBLIC, no date (a Public dateless row DOES count for all)
_DL_MEMBER_NODATE = "DL_MEMBER_NODATE"  # MEMBERS, no date (must NOT count for Public)
_DL_DRAFT_NODATE = "DL_DRAFT_NODATE"  # DRAFT (archivist-only), no date (must NOT count for anyone)


def _build_dateless_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(
        Collection(ulid=_DL_ROOT, name="Datum-Wurzel", parent_id=None), 0, changed_by="tester"
    )
    articles.save(
        Article(
            ulid=_DL_PUBLIC_DATED,
            title="Öffentliches datiertes Dokument",
            collection_id=_DL_ROOT,
            lifecycle=Lifecycle.PUBLISHED,
            audience=Audience(AudienceTier.PUBLIC),
            date=EdtfDate("1930"),
        ),
        0,
        changed_by="tester",
    )
    articles.save(
        Article(
            ulid=_DL_PUBLIC_NODATE,
            title="Öffentliches Dokument ohne Datum",
            collection_id=_DL_ROOT,
            lifecycle=Lifecycle.PUBLISHED,
            audience=Audience(AudienceTier.PUBLIC),
            date=None,
        ),
        0,
        changed_by="tester",
    )
    articles.save(
        Article(
            ulid=_DL_MEMBER_NODATE,
            title="Mitgliederdokument ohne Datum",
            collection_id=_DL_ROOT,
            lifecycle=Lifecycle.PUBLISHED,
            audience=Audience(AudienceTier.MEMBERS),
            date=None,
        ),
        0,
        changed_by="tester",
    )
    articles.save(
        Article(
            ulid=_DL_DRAFT_NODATE,
            title="Entwurf ohne Datum",
            collection_id=_DL_ROOT,
            lifecycle=Lifecycle.DRAFT,
            audience=Audience(AudienceTier.PUBLIC),  # audience irrelevant: DRAFT → archivist-only
            date=None,
        ),
        0,
        changed_by="tester",
    )
    return store


def _build_indexed() -> indexer.RebuildReport:
    return indexer.rebuild(_build_dateless_store())


@pytest.fixture(scope="module")
def _dateless_indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
    yield from fixtures.indexed_corpus(django_db_blocker, _build_indexed)


@pytest.fixture
def dateless_corpus(_dateless_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed dateless corpus to the ``db`` transaction fixture."""


def _dateless_ulids(viewer: Viewer) -> set[str]:
    page = search(viewer, filters=SearchFilters(dateless=True), page_size=200)
    return {hit.ulid for hit in page.hits}


@pytest.mark.django_db
def test_public_dateless_count_excludes_restricted_rows(dateless_corpus: None) -> None:
    assert search(PUBLIC, page_size=200).dateless_count == 1


@pytest.mark.django_db
def test_public_dateless_filter_returns_only_visible_undated(dateless_corpus: None) -> None:
    assert _dateless_ulids(PUBLIC) == {_DL_PUBLIC_NODATE}


@pytest.mark.django_db
def test_member_dateless_count_includes_member_row_not_draft(dateless_corpus: None) -> None:
    assert search(PLAIN_MEMBER, page_size=200).dateless_count == 2
    assert _dateless_ulids(PLAIN_MEMBER) == {_DL_PUBLIC_NODATE, _DL_MEMBER_NODATE}


@pytest.mark.django_db
def test_archivist_dateless_count_includes_draft(dateless_corpus: None) -> None:
    """The positive: the negatives above are a scope gate, not an indexing gap."""
    assert search(ARCHIVIST, page_size=200).dateless_count == 3
    assert _dateless_ulids(ARCHIVIST) == {
        _DL_PUBLIC_NODATE,
        _DL_MEMBER_NODATE,
        _DL_DRAFT_NODATE,
    }


@pytest.mark.django_db
def test_dated_public_row_never_counted_as_dateless(dateless_corpus: None) -> None:
    """The dated PUBLIC row anchors "index is non-empty": it appears in a normal browse but never in
    the dateless bucket or filter, so the count assertions above measure scope, not emptiness."""
    assert _DL_PUBLIC_DATED in {h.ulid for h in search(PUBLIC, page_size=200).hits}
    assert _DL_PUBLIC_DATED not in _dateless_ulids(ARCHIVIST)
