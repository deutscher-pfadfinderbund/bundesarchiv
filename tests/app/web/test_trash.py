"""The Papierkorb page (ADR 0022): what it offers for each marked Article. Needs Postgres (it lists
through ``search``); its archivist-only gate is the leak matrix's, its scoping
``test_leaks_papierkorb.py``'s."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from tests.app.web._fixtures import (
    PUB,
    Corpus,
    client_as,
    make_article,
    make_collection,
    page_forms,
    page_hrefs,
)

from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index import indexer

_MARKED = "01KX7YT9E3VX0CP3A5Q49RZMTA"
_LIVE = "01KX7YT9E3VX0CP3A5Q49RZMTB"


@pytest.fixture
def trash(db: None, make_corpus: Callable[[], Corpus]) -> Corpus:
    """One Article in the Papierkorb and one live, both indexed."""
    corpus = make_corpus()
    corpus.add_collection(
        make_collection(PUB, "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    marked = make_article(_MARKED, title="Winterlager 1961")
    corpus.articles.mark_deleted(marked, corpus.add_article(marked), changed_by="bert")
    corpus.add_article(make_article(_LIVE, title="Sommerlager 1962"))
    indexer.rebuild(corpus.store)
    return corpus


def _main() -> str:
    body = client_as(Archivist()).get("/trash").content.decode()
    return body[body.index("<main") :]


def test_each_row_restores_its_record_at_the_version_it_shows(trash: Corpus) -> None:
    main = _main()
    assert _LIVE not in main
    assert f"/articles/{_MARKED}/delete-permanently" in page_hrefs(main)
    [(action, fields)] = page_forms(main)
    assert action == f"/articles/{_MARKED}/restore"
    assert fields["expected_version"] == str(trash.articles.load(_MARKED).version)
    assert client_as(Archivist()).post(action, fields).status_code == 302
    assert trash.articles.load(_MARKED).article.deleted is None


def test_a_record_restored_since_the_index_was_written_is_not_offered(trash: Corpus) -> None:
    stored = trash.articles.load(_MARKED)
    trash.articles.save(replace(stored.article, deleted=None), stored.version, changed_by="bert")
    assert _MARKED not in _main()
