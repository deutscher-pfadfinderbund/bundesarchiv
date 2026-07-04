"""Per-tier leak guard for the "Ohne Datum" facet (Part 4) — its own module + corpus.

The shared corpus (``tests/index/fixtures.py``) dates every article, so it cannot exhibit a
tier-exclusive DATELESS row — the property this guard needs. Mirroring ``test_leaks_decades.py``
(same reason, same shape), this module builds a dedicated corpus where an undated row sits on a
RESTRICTED tier and another undated row sits on PUBLIC, so a leak (a restricted dateless row
inflating a lesser viewer's ``dateless_count`` or appearing under the ``dateless`` filter) is
distinguishable from an empty index.

Separate module because ``indexer.rebuild`` is destructive (wipes the whole ``ArticleIndex``), so
two module-scoped corpora cannot coexist in one module's shared table.
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
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer, search
from bundesarchiv.index.query import SearchFilters
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
    """A four-article corpus: one dated PUBLIC row (so the index is provably non-empty), one
    undated PUBLIC row (dateless, visible to all), one undated MEMBERS row (dateless, hidden from
    Public), and one undated DRAFT row (archivist-only). ``EdtfDate`` cannot express "no date" — a
    dateless Article is simply ``date=None`` (the default)."""
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(Collection(ulid=_DL_ROOT, name="Datum-Wurzel", parent_id=None), 0)
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
    """Public's "Ohne Datum" count is exactly 1 (its own undated PUBLIC row) — the undated MEMBERS
    row and the undated DRAFT row must NOT inflate it. A count of 2 or 3 would be the leak."""
    assert search(PUBLIC, page_size=200).dateless_count == 1


@pytest.mark.django_db
def test_public_dateless_filter_returns_only_visible_undated(dateless_corpus: None) -> None:
    """Under the ``dateless`` filter, Public sees only its own undated PUBLIC row — never the
    member-only or draft undated rows."""
    assert _dateless_ulids(PUBLIC) == {_DL_PUBLIC_NODATE}


@pytest.mark.django_db
def test_member_dateless_count_includes_member_row_not_draft(dateless_corpus: None) -> None:
    """A Member's count is 2 (the undated PUBLIC row + the undated MEMBERS row); the DRAFT row is
    archivist-only and must never count for a Member."""
    assert search(PLAIN_MEMBER, page_size=200).dateless_count == 2
    assert _dateless_ulids(PLAIN_MEMBER) == {_DL_PUBLIC_NODATE, _DL_MEMBER_NODATE}


@pytest.mark.django_db
def test_archivist_dateless_count_includes_draft(dateless_corpus: None) -> None:
    """The Archivist's count is 3 — every undated row, including the DRAFT — so the negatives above
    are a scope gate, not an indexing gap."""
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
