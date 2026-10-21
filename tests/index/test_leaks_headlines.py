"""A hit's headlines per tier: they show only the hit's own member-searchable fields.

A word that lives only in ``archivist_text`` (Standort, Weitere Angaben) reaches no headline of any
viewer, an Archivist's included, even on a row the Archivist finds by that very word; a word of a
restricted row reaches no headline of a viewer who may not see that row. The excerpt contract
lives in ``test_headlines.py``.

Its own module and corpus, because ``indexer.rebuild`` wipes the table (see
``test_leaks_decades.py``).
"""

from collections.abc import Iterator
from typing import NamedTuple

import pytest
from pytest_django.plugin import DjangoDbBlocker
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.models import ULID, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_ROOT = ULID("LH_ROOT")
_ARCHIVIST_WORDS = ("Geheimregal", "Geheimnotiz")


class _Row(NamedTuple):
    word: str  # the word only this row's member-searchable fields carry
    audience: Audience
    lifecycle: Lifecycle
    seen_by: frozenset[str]  # the tiers below the Archivist that may see it


_ROWS: dict[str, _Row] = {
    "LH_PUBLIC": _Row(
        "Sommerlager",
        Audience(AudienceTier.PUBLIC),
        Lifecycle.PUBLISHED,
        frozenset({"public", "member", "vorstand"}),
    ),
    "LH_MEMBER": _Row(
        "Mitgliederwort",
        Audience(AudienceTier.MEMBERS),
        Lifecycle.PUBLISHED,
        frozenset({"member", "vorstand"}),
    ),
    "LH_GROUP": _Row(
        "Vorstandswort",
        Audience(AudienceTier.GROUPS, ("vorstand",)),
        Lifecycle.PUBLISHED,
        frozenset({"vorstand"}),
    ),
    "LH_DRAFT": _Row("Entwurfswort", Audience(AudienceTier.PUBLIC), Lifecycle.DRAFT, frozenset()),
}
#: Every row's word and every archivist-only word: one query reaching all of them.
_QUERY = " or ".join((*(row.word for row in _ROWS.values()), *_ARCHIVIST_WORDS))

_TIERS: tuple[tuple[str, Viewer], ...] = (
    ("public", Public()),
    ("member", Member(())),
    ("member", Member(("nicht-vorstand",))),
    ("vorstand", Member(("vorstand",))),
    ("archivist", Archivist()),
)


def _build_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(Collection(_ROOT, "Wurzel"), 0, changed_by="tester")
    repo = ArticleRepository(store)
    for ulid, row in _ROWS.items():
        article = make_article(
            ulid,
            collection_id=_ROOT,
            title=f"Bericht {row.word}",
            lifecycle=row.lifecycle,
            audience=row.audience,
            tags=(f"{row.word} am Lagerfeuer",),
            creator=row.word,
            subject_place=row.word,
            body=f"Ein Bericht über {row.word}.",
            # every row carries the archivist-only words, beside its own
            physical_location=f"{row.word} {_ARCHIVIST_WORDS[0]} 7",
            custom=(("Notiz", f"{_ARCHIVIST_WORDS[1]} {row.word}"),),
        )
        repo.save(article, 0, changed_by="tester")
    return store


@pytest.fixture(scope="module")
def _indexed(
    django_db_setup: None, django_db_blocker: DjangoDbBlocker
) -> Iterator[indexer.RebuildReport]:
    yield from fixtures.indexed_corpus(django_db_blocker, lambda: indexer.rebuild(_build_store()))


@pytest.fixture
def corpus(_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed corpus to the ``db`` transaction fixture."""


def _visible(tier: str) -> set[str]:
    return {u for u, row in _ROWS.items() if tier == "archivist" or tier in row.seen_by}


@pytest.mark.django_db
@pytest.mark.parametrize(("tier", "viewer"), _TIERS)
def test_a_headline_shows_only_words_of_its_own_rows_member_fields(
    corpus: None, tier: str, viewer: Viewer
) -> None:
    hits = search(viewer, text=_QUERY, headlines=True, page_size=200).hits
    assert {h.ulid for h in hits} == _visible(tier)
    for hit in hits:
        texts = ["".join(text for text, _ in h.runs) for h in hit.headlines]
        assert {h.field for h in hit.headlines} == {
            "title",
            "tags",
            "creator",
            "subject_place",
            "body",
        }
        others = {row.word for u, row in _ROWS.items() if u != hit.ulid}
        for text in texts:
            assert _ROWS[hit.ulid].word in text
            assert not [w for w in (*others, *_ARCHIVIST_WORDS) if w in text], (hit.ulid, text)


@pytest.mark.django_db
def test_a_row_the_archivist_finds_only_by_its_standort_shows_no_headline(corpus: None) -> None:
    for word in _ARCHIVIST_WORDS:
        hits = search(Archivist(), text=word, headlines=True, page_size=200).hits
        assert {h.ulid for h in hits} == set(_ROWS), word
        assert all(h.headlines == () for h in hits), word
