"""Every write route shows the lag state when the synchronous index update fails (ADR 0014): in
place, or on the page its redirect lands on. The route list is exhaustive over the prod urlconf."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from django.urls import URLPattern, get_resolver
from tests.app.web._fixtures import (
    DRAFT_ULID,
    PUB,
    PUBLISHED_ULID,
    WRITES,
    Corpus,
    client_as,
    list_url,
)

from bundesarchiv.app import after_write
from bundesarchiv.app.web import landing
from bundesarchiv.domain.models import Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member

#: The context keys that carry the notice: pages, the Medien drawer, the bulk result.
_LAG_KEYS = ("index_lag", "drawer_index_lag", "bulk_index_lag")
_DB = pytest.mark.django_db  # the landing page runs a search

#: Neither Bestand route syncs the index: a new Bestand holds no Article, and the rename route
#: changes the name only, which moves no Article's visibility.
_NEEDS_DB = {"article-delete-permanently", "collection-edit"}
_NO_SYNC = {"collection-create", "collection-edit"}


def _media(corpus: Corpus) -> tuple[str, ...]:
    return tuple(ref.filename for ref in corpus.articles.load(DRAFT_ULID).article.media)


def _titles(corpus: Corpus) -> list[str]:
    return [corpus.articles.load(u).article.title for u in corpus.articles.list_ulids()]


#: What the canonical write left behind, per route: the lag never undoes the write (ADR 0014).
_STOOD: dict[str, Callable[[Corpus], bool]] = {
    "article-create": lambda c: "Neu" in _titles(c),
    "article-edit": lambda c: c.articles.load(DRAFT_ULID).article.title == "Umbenannt",
    "article-copy": lambda c: len(_titles(c)) == 3,
    "article-publish": lambda c: (
        c.articles.load(DRAFT_ULID).article.lifecycle is Lifecycle.PUBLISHED
    ),
    "article-delete": lambda c: c.articles.load(PUBLISHED_ULID).article.deleted is not None,
    "article-delete-permanently": lambda c: PUBLISHED_ULID not in set(c.articles.list_ulids()),
    "article-restore": lambda c: c.articles.load(PUBLISHED_ULID).article.deleted is None,
    "article-media-upload": lambda c: _media(c) == ("scan.pdf",),
    "article-media-move": lambda c: _media(c) == ("b.pdf", "a.pdf"),
    "article-media-remove": lambda c: _media(c) == ("b.pdf",),
    "article-bulk-edit": lambda c: c.articles.load(DRAFT_ULID).article.creator == "Kurt",
    "collection-create": lambda c: "Karten" in {x.name for x in c.collections.load_all()},
    "collection-edit": lambda c: c.collections.load(PUB).collection.name == "Umbenannt",
}

#: Every route that writes nothing to the archive.
_READS = {
    "start",
    "workbench",
    "columns",
    "trash",
    "login",
    "oidc-callback",
    "logout",
    "article-bulk-edit-document-types",
    "upload-gate",
    "article-document-types",
    "tag-suggestions",
    "article-detail",
    "media",
    "media-thumb",
    "media-display",
}


@pytest.fixture
def failing_index(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """The synchronous index update raises; yields the ulids it was asked to index."""
    asked: list[str] = []

    def fail(_store: object, ulid: str, **_: object) -> None:
        asked.append(ulid)
        raise RuntimeError("index down")

    monkeypatch.setattr(after_write, "index_article", fail)
    monkeypatch.setattr(after_write, "index_subtree", fail)
    yield asked


@pytest.mark.parametrize(
    "route",
    [pytest.param(name, marks=[_DB] if name in _NEEDS_DB else []) for name in WRITES],
)
def test_a_write_whose_index_update_failed_shows_the_lag(
    corpus: Corpus, failing_index: list[str], route: str
) -> None:
    client = client_as(Archivist("anna"))
    response = WRITES[route](client, corpus)
    if response.status_code == 302:  # a redirect carries the lag to the page it lands on
        response = client.get(response["Location"])
    assert response.status_code == 200
    assert _STOOD[route](corpus)
    synced = route not in _NO_SYNC
    assert bool(failing_index) is synced
    shown = any(response.context.get(key) for key in _LAG_KEYS)
    assert shown is synced


def test_every_route_is_a_write_row_or_a_read() -> None:
    names = {
        p.name
        for p in get_resolver("bundesarchiv.app.web.urls").url_patterns
        if isinstance(p, URLPattern) and p.name and not p.name.startswith("alias-")
    }
    assert not set(WRITES) & _READS
    assert set(WRITES) | _READS == names
    assert set(_STOOD) == set(WRITES)


@pytest.mark.parametrize("ulid", [PUBLISHED_ULID, DRAFT_ULID])
def test_a_record_page_reached_by_a_lagging_write_says_so(corpus: Corpus, ulid: str) -> None:
    """Save, publish and restore land on the record's page, marked or not."""
    client = client_as(Archivist("anna"))
    assert client.get(f"/articles/{ulid}?index=lagging").context["index_lag"]
    assert not client.get(f"/articles/{ulid}").context["index_lag"]


def test_only_an_archivist_is_told_of_the_lag(corpus: Corpus) -> None:
    """A shared ``?index=lagging`` address says nothing to a Member or the public."""
    for viewer in (Member(), None):
        client = client_as(viewer)
        assert not client.get(f"/articles/{PUBLISHED_ULID}?index=lagging").context["index_lag"]


@pytest.mark.django_db
def test_no_list_link_carries_the_flag_on(corpus: Corpus) -> None:
    client = client_as(Archivist("anna"))
    page = client.get(list_url(index="lagging", collection=PUB))
    assert page.context["index_lag"]
    assert "index=" not in page.content.decode()
    assert "index=" not in page.context["columns_back"]


def test_the_script_that_clears_the_flag_spells_what_landing_writes() -> None:
    script = (Path(landing.__file__).parent / "static" / "list_address.js").read_text()
    key, value = landing.LAG_FLAG
    assert f'query.get("{key}") !== "{value}"' in script
