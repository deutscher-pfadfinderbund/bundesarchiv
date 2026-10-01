"""Every write route records the signed-in archivist as the ``changed_by`` of the version it writes
(ADR 0019: the history is the audit trail)."""

from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import pytest
from django.http import HttpResponse
from django.urls import resolve
from tests.app.web._fixtures import DRAFT_ULID, PUB, PUBLISHED_ULID, WRITES, Corpus, client_as

from bundesarchiv.domain.models import Change
from bundesarchiv.domain.viewer import Archivist

_ARCHIVIST = Archivist("anna")


def _ulid_in(location: str) -> str:
    return str(resolve(urlparse(location).path).kwargs["ulid"])


def _article(ulid: str) -> Callable[[HttpResponse, Corpus], Change | None]:
    return lambda _response, corpus: corpus.articles.load(ulid).change


def _landed_article(response: HttpResponse, corpus: Corpus) -> Change | None:
    return corpus.articles.load(_ulid_in(response["Location"])).change


def _created_bestand(response: HttpResponse, corpus: Corpus) -> Change | None:
    [ulid] = parse_qs(urlparse(response["Location"]).query)["bestand"]
    return corpus.collections.load(ulid).change


def _bestand(_response: HttpResponse, corpus: Corpus) -> Change | None:
    return corpus.collections.load(PUB).change


#: Per write route: the version it wrote. Hard delete leaves none; the route-list test is
#: ``test_index_lag.py``'s.
_CHANGED: dict[str, Callable[[HttpResponse, Corpus], Change | None]] = {
    "artikel-neu": _landed_article,
    "artikel-bearbeiten": _article(DRAFT_ULID),
    "artikel-kopieren": _landed_article,
    "artikel-veroeffentlichen": _article(DRAFT_ULID),
    "artikel-loeschen": _article(PUBLISHED_ULID),
    "article-restore": _article(PUBLISHED_ULID),
    "artikel-medien-hochladen": _article(DRAFT_ULID),
    "artikel-medien-verschieben": _article(DRAFT_ULID),
    "artikel-medien-entfernen": _article(DRAFT_ULID),
    "artikel-sammelbearbeitung": _article(DRAFT_ULID),
}
_BESTAND_CHANGED = {"bestand-neu": _created_bestand, "bestand-bearbeiten": _bestand}


@pytest.mark.parametrize("route", _CHANGED)
def test_the_version_an_article_route_writes_names_the_signed_in_archivist(
    corpus: Corpus, route: str
) -> None:
    response = WRITES[route](client_as(_ARCHIVIST), corpus)
    change = _CHANGED[route](response, corpus)
    assert change is not None and change.by == _ARCHIVIST.username


@pytest.mark.django_db
@pytest.mark.parametrize("route", _BESTAND_CHANGED)
def test_the_version_a_bestand_route_writes_names_the_signed_in_archivist(
    corpus: Corpus, route: str
) -> None:
    response = WRITES[route](client_as(_ARCHIVIST), corpus)
    change = _BESTAND_CHANGED[route](response, corpus)
    assert change is not None and change.by == _ARCHIVIST.username


def test_every_write_route_is_checked_here_or_leaves_no_version() -> None:
    assert set(_CHANGED) | set(_BESTAND_CHANGED) | {"article-delete-permanently"} == set(WRITES)
