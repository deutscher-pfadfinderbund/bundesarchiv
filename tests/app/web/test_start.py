"""The start page (``/``) and the list's move to ``/articles``.

Postgres-backed: the start page's counts come from the viewer-scoped index. The leak spine: a
Bestand's count is what THIS viewer may see, and a Bestand with nothing the viewer may see is not
named at all.
"""

import re
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import unquote

import pytest
from django.test import RequestFactory
from tests.app.web._fixtures import Corpus, client_as, list_url, make_article, make_collection

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import start
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import FacetCount

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
    for n, (collection, lifecycle, media_type, date) in enumerate(
        (
            (_BUND, Lifecycle.PUBLISHED, "Foto(s)", EdtfDate("1962-07")),
            (_BUND, Lifecycle.DRAFT, "Foto(s)", EdtfDate("1965")),
            (_FAHRTEN, Lifecycle.PUBLISHED, "Buch", None),
            (_VERBORGEN, Lifecycle.DRAFT, "Buch", EdtfDate("1962")),
        )
    ):
        corpus.add_article(
            make_article(
                f"01KX8A00000000000000000AR{n}",
                title=f"Titel {n}",
                collection_id=collection,
                lifecycle=lifecycle,
                media_type=media_type,
                date=date,
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


def _preset_counts(response: Any, param: str) -> dict[str, str]:
    """Each link of the list preset ``param`` in ``<main>`` and the count it carries."""
    main = response.content.decode().split("<main", 1)[1]
    found = re.findall(rf'href="/articles\?{param}=([^"]+)".*?<data value="(\d+)"', main)
    return {unquote(value): count for value, count in found}


@pytest.mark.parametrize(
    ("viewer", "art", "decades", "undated"),
    [
        (Member(groups=()), {"Foto(s)": "1", "Buch": "1"}, {"1960": "1"}, "1"),
        (Archivist(), {"Foto(s)": "2", "Buch": "2"}, {"1960": "3"}, "1"),
    ],
    ids=["member", "archivist"],
)
def test_nach_art_and_zeitleiste_count_what_the_viewer_may_see(
    indexed_corpus: Corpus,
    viewer: Viewer,
    art: dict[str, str],
    decades: dict[str, str],
    undated: str,
) -> None:
    response = _get(viewer, "/")
    assert _preset_counts(response, "medienart") == art
    assert _preset_counts(response, "jahrzehnt") == decades
    assert _preset_counts(response, "ohne_datum") == {"1": undated}


def test_weitere_arten_sums_what_the_top_arten_leave() -> None:
    counts = {"media_type": tuple(FacetCount(f"Art {n}", 10 - n) for n in range(9))}
    area = start.nach_art(Archivist(), RequestFactory().get("/"), counts, None)  # type: ignore[arg-type]
    tiles = cast("tuple[start.Tile, ...]", area["tiles"])
    assert [(t.label, t.count) for t in tiles][-2:] == [("Art 6", 4), ("Weitere Arten", 3 + 2)]


def test_weiter_bearbeiten_names_the_drafts_to_an_archivist_and_nothing_to_a_member(
    indexed_corpus: Corpus,
) -> None:
    archivist = _get(Archivist(), "/").content.decode()
    assert len(re.findall(r'href="/articles/\w+/edit"', archivist)) == 2
    assert "/edit" not in _get(Member(groups=()), "/").content.decode()


def test_weiter_bearbeiten_folds_more_than_three_drafts_into_a_link_to_the_drafts_list(
    indexed_corpus: Corpus,
) -> None:
    for n in range(3):
        indexed_corpus.add_article(
            make_article(
                f"01KX8A00000000000000000DR{n}", collection_id=_BUND, lifecycle=Lifecycle.DRAFT
            )
        )
    indexer.rebuild(indexed_corpus.store)
    main = _get(Archivist(), "/").content.decode().split("<main", 1)[1]
    assert len(re.findall(r'href="/articles/\w+/edit"', main)) == 2
    assert 'href="/articles?entwuerfe=1">und 3 weitere<' in main


@pytest.mark.parametrize(
    ("viewer", "titles"),
    [(Member(groups=()), {"Titel 0", "Titel 2"}), (Archivist(), {f"Titel {n}" for n in range(4)})],
    ids=["member", "archivist"],
)
def test_zuletzt_hinzugefuegt_lists_only_what_the_viewer_may_see(
    indexed_corpus: Corpus, viewer: Viewer, titles: set[str]
) -> None:
    bestand = BestandChooser.of(Archive.canonical())
    area = start.zuletzt_hinzugefuegt(viewer, RequestFactory().get("/"), {}, bestand)
    rows = cast("tuple[tuple[str, str, str, str], ...]", area["rows"])
    assert {title for _, title, _, _ in rows} == titles
