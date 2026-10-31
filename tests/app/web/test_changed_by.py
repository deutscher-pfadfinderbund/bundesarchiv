"""Every write route records the signed-in archivist as the ``changed_by`` of the version it writes
(ADR 0019)."""

from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.http import HttpResponse
from django.urls import resolve
from tests.app.web._fixtures import DRAFT_ULID, PUBLISHED_ULID, WRITES, Corpus, client_as
from tests.app.web._tus import finish, staged, staging_at

from bundesarchiv.domain.models import ULID, Change
from bundesarchiv.domain.viewer import Archivist

_ARCHIVIST = Archivist("anna")


def _ulid_in(location: str) -> str:
    return str(resolve(urlparse(location).path).kwargs["ulid"])


def _article(ulid: str) -> Callable[[HttpResponse, Corpus], Change | None]:
    return lambda _response, corpus: corpus.articles.load(ULID(ulid)).change


def _landed_article(response: HttpResponse, corpus: Corpus) -> Change | None:
    return corpus.articles.load(ULID(_ulid_in(response["Location"]))).change


_CHANGED: dict[str, Callable[[HttpResponse, Corpus], Change | None]] = {
    "article-create": _landed_article,
    "article-edit": _article(DRAFT_ULID),
    "article-copy": _landed_article,
    "article-publish": _article(DRAFT_ULID),
    "article-delete": _article(PUBLISHED_ULID),
    "article-restore": _article(PUBLISHED_ULID),
    "article-media-upload": _article(DRAFT_ULID),
    "article-media-move": _article(DRAFT_ULID),
    "article-media-remove": _article(DRAFT_ULID),
    "article-bulk-edit": _article(DRAFT_ULID),
}


@pytest.mark.parametrize("route", _CHANGED)
def test_the_version_an_article_route_writes_names_the_signed_in_archivist(
    corpus: Corpus, route: str
) -> None:
    response = WRITES[route](client_as(_ARCHIVIST), corpus)
    change = _CHANGED[route](response, corpus)
    assert change is not None and change.by == _ARCHIVIST.username


def test_a_chunked_upload_finish_names_the_signed_in_archivist(
    corpus: Corpus, tmp_path: Path
) -> None:
    client = client_as(_ARCHIVIST)
    with staging_at(tmp_path / "staging"):
        finish(client, DRAFT_ULID, staged(client, DRAFT_ULID, b"%PDF-1.4"))
    change = corpus.articles.load(DRAFT_ULID).change
    assert change is not None and change.by == _ARCHIVIST.username


def test_every_write_route_is_checked_here_or_leaves_no_version() -> None:
    assert set(_CHANGED) | {"article-delete-permanently"} == set(WRITES)
