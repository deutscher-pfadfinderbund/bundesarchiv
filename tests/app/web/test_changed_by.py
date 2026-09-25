"""Every write route records the signed-in archivist as the ``changed_by`` of the version it writes
(ADR 0019: the history is the audit trail)."""

import io
from collections.abc import Callable
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import resolve
from tests.app.web._fixtures import DRAFT_ULID, PUB, PUBLISHED_ULID, Corpus, client_as

from bundesarchiv.domain.models import Change
from bundesarchiv.domain.viewer import Archivist

_ARCHIVIST = Archivist("anna")

_EDIT_FIELDS = (
    "ref_code",
    "document_type",
    "tags",
    "date",
    "creator",
    "subject_place",
    "physical_location",
    "body",
    "sichtbarkeit",
    "gruppen",
)


def _ulid_in(location: str) -> str:
    return str(resolve(urlparse(location).path).kwargs["ulid"])


def _with_two_media(corpus: Corpus) -> tuple[str, str]:
    stored = corpus.articles.load(DRAFT_ULID)
    first = corpus.articles.add_media(DRAFT_ULID, "a.pdf", io.BytesIO(b"a"))
    second = corpus.articles.add_media(DRAFT_ULID, "b.pdf", io.BytesIO(b"b"))
    corpus.articles.save(
        replace(stored.article, media=(first, second)), stored.version, changed_by="tester"
    )
    return first.content_hash, second.content_hash


def _create(client: Client, corpus: Corpus) -> Change | None:
    response = client.post("/artikel/neu", {"title": "Neu", "collection_id": PUB})
    return corpus.articles.load(_ulid_in(response["Location"])).change


def _edit(client: Client, corpus: Corpus) -> Change | None:
    stored = corpus.articles.load(DRAFT_ULID)
    client.post(
        f"/artikel/{DRAFT_ULID}/bearbeiten",
        {
            **dict.fromkeys(_EDIT_FIELDS, ""),
            "title": "Umbenannt",
            "collection_id": PUB,
            "media_type": "Foto(s)",
            "expected_version": str(stored.version),
        },
    )
    return corpus.articles.load(DRAFT_ULID).change


def _copy(client: Client, corpus: Corpus) -> Change | None:
    response = client.post(f"/artikel/{PUBLISHED_ULID}/kopieren")
    return corpus.articles.load(_ulid_in(response["Location"])).change


def _upload(client: Client, corpus: Corpus) -> Change | None:
    upload = SimpleUploadedFile("scan.pdf", b"%PDF-1.4", content_type="application/pdf")
    client.post(f"/artikel/{DRAFT_ULID}/medien/hochladen", {"dateien": upload})
    return corpus.articles.load(DRAFT_ULID).change


def _reorder(client: Client, corpus: Corpus) -> Change | None:
    first, _ = _with_two_media(corpus)
    client.post(f"/artikel/{DRAFT_ULID}/medien/verschieben", {"hash": first, "richtung": "runter"})
    return corpus.articles.load(DRAFT_ULID).change


def _remove(client: Client, corpus: Corpus) -> Change | None:
    first, _ = _with_two_media(corpus)
    client.post(f"/artikel/{DRAFT_ULID}/medien/entfernen", {"entfernen": first, "bestaetigt": "1"})
    return corpus.articles.load(DRAFT_ULID).change


def _bulk(client: Client, corpus: Corpus) -> Change | None:
    client.post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [DRAFT_ULID], "feld": "creator", "wert_text": "Kurt", "bestaetigt": "1"},
    )
    return corpus.articles.load(DRAFT_ULID).change


def _create_bestand(client: Client, corpus: Corpus) -> Change | None:
    response = client.post("/bestand/neu", {"name": "Karten", "parent_id": "", "sichtbarkeit": ""})
    [ulid] = parse_qs(urlparse(response["Location"]).query)["bestand"]
    return corpus.collections.load(ulid).change


def _rename_bestand(client: Client, corpus: Corpus) -> Change | None:
    stored = corpus.collections.load(PUB)
    client.post(
        f"/bestand/{PUB}/bearbeiten", {"name": "Umbenannt", "expected_version": str(stored.version)}
    )
    return corpus.collections.load(PUB).change


@pytest.mark.parametrize("write", [_create, _edit, _copy, _upload, _reorder, _remove, _bulk])
def test_the_version_an_article_route_writes_names_the_signed_in_archivist(
    corpus: Corpus, write: Callable[[Client, Corpus], Change | None]
) -> None:
    change = write(client_as(_ARCHIVIST), corpus)
    assert change is not None and change.by == _ARCHIVIST.username


@pytest.mark.django_db
@pytest.mark.parametrize("write", [_create_bestand, _rename_bestand])
def test_the_version_a_bestand_route_writes_names_the_signed_in_archivist(
    corpus: Corpus, write: Callable[[Client, Corpus], Change | None]
) -> None:
    change = write(client_as(_ARCHIVIST), corpus)
    assert change is not None and change.by == _ARCHIVIST.username
