"""Suggestions while typing per tier: every group offers only what the viewer may see.

Titles (``search``), Autor and Ort values and Schlagworte (``values_containing``) with their counts:
a value carried by a restricted, draft or Papierkorb row never reaches another viewer, and a value
shared across tiers counts only the viewer's rows. ``archivist_text`` is never read: a word only in
it suggests nothing, even to the Archivist.

Its own module and corpus, because ``indexer.rebuild`` wipes the table.
"""

from collections import Counter
from collections.abc import Iterator
from typing import NamedTuple

import pytest
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.models import Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import Suggested, search, values_containing
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_ROOT = "SG_ROOT"


class _Row(NamedTuple):
    creator: str
    place: str
    tags: tuple[str, ...]
    audience: Audience
    lifecycle: Lifecycle
    seen_by: frozenset[str]  # the tiers below the Archivist that may see it
    marked: bool = False  # in the Papierkorb: no viewer's suggestion sees it


#: Every value contains "wald", so one text reaches every row.
_ROWS: dict[str, _Row] = {
    "SG_PUBLIC": _Row(
        "Waldemar Öffentlich",
        "Burg Waldeck",
        ("Waldlauf", "Waldfest"),
        Audience(AudienceTier.PUBLIC),
        Lifecycle.PUBLISHED,
        frozenset({"public", "member", "vorstand"}),
    ),
    "SG_MEMBER": _Row(
        "Waldemar Öffentlich",
        "Waldheim",
        ("Waldlauf", "Waldmitglied"),
        Audience(AudienceTier.MEMBERS),
        Lifecycle.PUBLISHED,
        frozenset({"member", "vorstand"}),
    ),
    "SG_GROUP": _Row(
        "Waldvorstand",
        "Burg Waldeck",
        ("Waldlauf", "Waldgeheim"),
        Audience(AudienceTier.GROUPS, ("vorstand",)),
        Lifecycle.PUBLISHED,
        frozenset({"vorstand"}),
    ),
    "SG_DRAFT": _Row(
        "Waldentwurf",
        "Waldentwurfsort",
        ("Waldlauf", "Waldentwurfstag"),
        Audience(AudienceTier.PUBLIC),
        Lifecycle.DRAFT,
        frozenset(),
    ),
    "SG_MARKED": _Row(
        "Waldpapierkorb",
        "Burg Waldeck",
        ("Waldlauf", "Waldmüll"),
        Audience(AudienceTier.PUBLIC),
        Lifecycle.PUBLISHED,
        frozenset(),
        marked=True,
    ),
}

_TIERS: tuple[tuple[str, Viewer], ...] = (
    ("public", Public()),
    ("member", Member(())),
    ("member", Member(("nicht-vorstand",))),
    ("vorstand", Member(("vorstand",))),
    ("archivist", Archivist()),
)


def _visible(tier: str) -> list[_Row]:
    return [
        row
        for row in _ROWS.values()
        if not row.marked and (tier == "archivist" or tier in row.seen_by)
    ]


def _values(row: _Row, field: Suggested) -> tuple[str, ...]:
    return {"creator": (row.creator,), "place": (row.place,), "tags": row.tags}[field]


def _build_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(Collection(_ROOT, "Wurzel"), 0, changed_by="tester")
    repo = ArticleRepository(store)
    for ulid, row in _ROWS.items():
        article = make_article(
            ulid,
            collection_id=_ROOT,
            title=f"Waldtitel {ulid}",
            lifecycle=row.lifecycle,
            audience=row.audience,
            creator=row.creator,
            subject_place=row.place,
            tags=row.tags,
            physical_location="Regal Waldgeheimnis",
        )
        version = repo.save(article, 0, changed_by="tester")
        if row.marked:
            repo.mark_deleted(article, version, changed_by="tester")
    return store


@pytest.fixture(scope="module")
def _indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
    yield from fixtures.indexed_corpus(django_db_blocker, lambda: indexer.rebuild(_build_store()))


@pytest.fixture
def corpus(_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed corpus to the ``db`` transaction fixture."""


@pytest.mark.django_db
@pytest.mark.parametrize(("tier", "viewer"), _TIERS)
@pytest.mark.parametrize("field", ["creator", "place", "tags"])
def test_each_value_group_offers_and_counts_only_the_viewers_rows(
    corpus: None, tier: str, viewer: Viewer, field: Suggested
) -> None:
    expected = Counter(value for row in _visible(tier) for value in _values(row, field))
    offered = values_containing(viewer, field, "WALD")
    assert {fc.value: fc.count for fc in offered} == expected
    assert len(offered) == len(expected)


@pytest.mark.django_db
@pytest.mark.parametrize(("tier", "viewer"), _TIERS)
def test_the_article_group_names_only_the_viewers_titles(
    corpus: None, tier: str, viewer: Viewer
) -> None:
    page = search(viewer, text="Waldtitel", page_size=3, facets=())
    visible = {u for u, row in _ROWS.items() if row in _visible(tier)}
    assert page.total == len(visible)
    assert {h.ulid for h in page.hits} <= visible


@pytest.mark.django_db
def test_the_archivist_text_suggests_nothing(corpus: None) -> None:
    assert all(not values_containing(Archivist(), f, "Regal") for f in ("creator", "place", "tags"))


@pytest.mark.django_db
def test_values_starting_with_the_text_come_first_then_by_count(corpus: None) -> None:
    offered = values_containing(Archivist(), "place", "wald")
    assert [fc.value for fc in offered] == ["Waldentwurfsort", "Waldheim", "Burg Waldeck"]
