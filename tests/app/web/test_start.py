"""The start page (``/``) and the list's move to ``/articles``.

Postgres-backed: the start page's counts come from the viewer-scoped index. The leak spine: a
Bestand's count is what THIS viewer may see, and a Bestand with nothing the viewer may see is not
named at all.
"""

import re
from collections.abc import Callable
from typing import Any

import pytest
from tests.app.web._fixtures import Corpus, client_as, list_url, make_article, make_collection

from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Viewer
from bundesarchiv.index import indexer

_BUND = "01KX8A00000000000000000BND"
_VERBORGEN = "01KX8A00000000000000000VRB"
_FAHRTEN = "01KX8A00000000000000000FHR"


@pytest.fixture
def indexed_corpus(db: None, make_corpus: Callable[[], Corpus]) -> Corpus:
    """Two top-level Bestände beside the fixture's ROOT: "Bund" (two published Articles, one of them
    in its sub-Bestand "Fahrten", and a draft) and "Verborgen" (a draft only)."""
    corpus = make_corpus()
    public = Audience(AudienceTier.PUBLIC)
    corpus.add_collection(make_collection(_BUND, "Bund", parent_id=None, audience=public))
    corpus.add_collection(make_collection(_VERBORGEN, "Verborgen", parent_id=None, audience=public))
    corpus.add_collection(make_collection(_FAHRTEN, "Fahrten", parent_id=_BUND))
    for n, (collection, lifecycle) in enumerate(
        (
            (_BUND, Lifecycle.PUBLISHED),
            (_BUND, Lifecycle.DRAFT),
            (_FAHRTEN, Lifecycle.PUBLISHED),
            (_VERBORGEN, Lifecycle.DRAFT),
        )
    ):
        corpus.add_article(
            make_article(
                f"01KX8A00000000000000000AR{n}", collection_id=collection, lifecycle=lifecycle
            )
        )
    indexer.rebuild(corpus.store)
    return corpus


def _get(viewer: Viewer, path: str) -> Any:
    response = client_as(viewer).get(path)
    assert response.status_code == 200
    return response


def _bestand_counts(response: Any) -> dict[str, str]:
    """Each Bestand link in ``<main>`` and the count it carries."""
    main = response.content.decode().split("<main", 1)[1]
    return dict(re.findall(r'href="/articles\?bestand=(\w+)".*?<data value="(\d+)"', main))


def _screen(response: Any) -> str:
    return response.templates[0].name or ""


@pytest.mark.parametrize(
    ("viewer", "expected"),
    [
        (Member(groups=()), {_BUND: "2"}),
        (Archivist(), {_BUND: "3", _VERBORGEN: "1"}),
    ],
    ids=["member", "archivist"],
)
def test_the_start_page_counts_the_top_level_bestaende_the_viewer_may_see(
    indexed_corpus: Corpus, viewer: Viewer, expected: dict[str, str]
) -> None:
    assert _bestand_counts(_get(viewer, "/")) == expected


def test_a_bestand_link_lands_on_the_list_with_as_many_articles_as_it_counts(
    indexed_corpus: Corpus,
) -> None:
    member = Member(groups=())
    counts = _bestand_counts(_get(member, "/"))
    listed = _get(member, list_url(bestand=_BUND))
    assert _screen(listed) == "workbench/workbench.html"
    assert listed.context["total"] == counts[_BUND]


def test_the_root_is_the_start_page_and_an_old_list_link_lands_on_the_list(
    indexed_corpus: Corpus,
) -> None:
    assert _screen(_get(Archivist(), "/")) == "start/start.html"
    old = client_as(Archivist()).get(f"/?bestand={_BUND}&auswahl=")
    assert (old.status_code, old["Location"]) == (301, f"/articles?bestand={_BUND}&auswahl=")
