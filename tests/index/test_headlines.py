"""A hit's headlines: where in its member-searchable fields the query matched (ADR 0011 config).

Its own module and corpus, because ``indexer.rebuild`` wipes the table (see
``test_leaks_decades.py``). The leak half lives in ``test_leaks_headlines.py``.
"""

from collections.abc import Iterator

import pytest
from pytest_django.plugin import DjangoDbBlocker
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.models import ULID, Audience, AudienceTier, Collection
from bundesarchiv.domain.viewer import Public
from bundesarchiv.index import indexer
from bundesarchiv.index.query import Headline, SearchHit, search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_ROOT = ULID("HL_ROOT")
_LONG_TAG = (
    "Fahrtenbuch der Gruppe mit vielen Seiten über das Bundeslager des DPB 1960 auf Burg"
    " Königstein und danach noch weitere Fahrten in den Harz und an die See"
)
#: A bare "<", a tag-like word (ts_headline drops one from its own excerpt), an entity, unicode,
#: the control characters the headline uses itself, and surrounding whitespace: the excerpt gives
#: it all back as plain text, only the matched word marked.
_ODD_BODY = "  a < b <unleserlich> &amp; \x02Wörter\x03\x04 «Sonderlager» 💡 Ende  "


def _build_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(
        Collection(_ROOT, "Wurzel", audience=Audience(AudienceTier.PUBLIC)), 0, changed_by="tester"
    )
    repo = ArticleRepository(store)
    for article in (
        make_article(
            "HL_TITLE",
            collection_id=_ROOT,
            title="Bundeslager Königstein 1960",
            tags=("Königstein",),
        ),
        make_article(
            "HL_TAGS",
            collection_id=_ROOT,
            title="Ein Ritterspiegel",
            tags=("Spiegel", _LONG_TAG),
            creator="Hans Königstein",
        ),
        make_article("HL_ODD", collection_id=_ROOT, title="Allerlei", body=_ODD_BODY),
    ):
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


def _hits(text: str | None, *, headlines: bool = True) -> dict[str, SearchHit]:
    return {h.ulid: h for h in search(Public(), text=text, headlines=headlines).hits}


def _by_field(hit: SearchHit) -> dict[str, Headline]:
    return {h.field: h for h in hit.headlines}


def _marked(headline: Headline) -> list[str]:
    return [text for text, marked in headline.runs if marked]


def _plain(headline: Headline) -> str:
    return "".join(text for text, _ in headline.runs)


@pytest.mark.django_db
def test_headlines_come_only_when_asked_for_and_only_for_a_query(corpus: None) -> None:
    assert all(h.headlines == () for h in _hits("Königstein", headlines=False).values())
    assert all(h.headlines == () for h in _hits(None).values())


@pytest.mark.django_db
def test_every_field_holding_the_word_marks_it_and_no_other_field_has_one(corpus: None) -> None:
    hits = _hits("Königstein")
    assert set(hits) == {"HL_TITLE", "HL_TAGS"}
    title, tags = _by_field(hits["HL_TITLE"]), _by_field(hits["HL_TAGS"])
    assert set(title) == {"title", "tags"}
    assert set(tags) == {"tags", "creator"}
    assert all(_marked(h) == ["Königstein"] for h in (*title.values(), *tags.values()))


@pytest.mark.django_db
def test_the_trailing_prefix_marks_the_whole_compound(corpus: None) -> None:
    title = _by_field(_hits("Bundes")["HL_TITLE"])["title"]
    assert _marked(title) == ["Bundeslager"]


@pytest.mark.django_db
def test_an_excerpt_says_which_end_of_its_field_it_leaves_out(corpus: None) -> None:
    fields = _by_field(_hits("Königstein")["HL_TAGS"])
    tags, creator = fields["tags"], fields["creator"]
    assert (tags.cut_start, tags.cut_end) == (True, True)
    assert _plain(tags) in f"Spiegel · {_LONG_TAG}"
    assert (creator.cut_start, creator.cut_end, _plain(creator)) == (
        False,
        False,
        "Hans Königstein",
    )


@pytest.mark.django_db
def test_an_excerpt_gives_its_fields_text_back_verbatim_marking_only_the_word(
    corpus: None,
) -> None:
    body = _by_field(_hits("Sonderlager")["HL_ODD"])["body"]
    assert _marked(body) == ["Sonderlager"]
    assert _plain(body).strip() == _ODD_BODY.translate(dict.fromkeys(b"\x02\x03\x04")).strip()
    assert (body.cut_start, body.cut_end) == (False, False)
