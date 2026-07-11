"""Bulk-edit confirm + commit route (Sammelbearbeitung, spec §2/§4/§6).

POST /artikel/sammelbearbeitung: archivist-gated, POST-only. Phase 1 (no bestaetigt) → confirm page;
phase 2 (bestaetigt=1) → apply + result page. The deny suite (spec §6) is the load-bearing part
(mutation-tested): non-archivist → byte-identical 404 with ZERO writes; GET → 404; feld allowlist;
dependent-pair server-enforced; orphan dokumenttyp_leeren server-enforced. The write path is real;
only index + queue seams are stubbed (conftest.py).
"""

from pathlib import Path

import pytest
from django.core import signing
from django.http.response import HttpResponseBase
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-bulk-views-key"
_A = "01KX7YT9E3VX0CP3A5Q49RZM01"
_B = "01KX7YT9E3VX0CP3A5Q49RZM02"


class _Corpus:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        collections = CollectionRepository(self.store)
        collections.save(Collection("ROOT", "Wurzel", None), 0)
        collections.save(Collection("PUB", "Öffentlich", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        collections.save(Collection("ARCH", "Archiv", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        repo = ArticleRepository(self.store)
        repo.save(
            Article(ulid=_A, title="Foto A", collection_id="PUB", lifecycle=Lifecycle.DRAFT), 0
        )
        repo.save(
            Article(ulid=_B, title="Foto B", collection_id="PUB", lifecycle=Lifecycle.DRAFT), 0
        )

    def article(self, ulid: str) -> Article:
        return ArticleRepository(self.store).load(ulid).article


@pytest.fixture
def corpus(tmp_path: Path) -> _Corpus:
    return _Corpus(tmp_path / "canonical")


def _settings(corpus: _Corpus) -> dict[str, object]:
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(corpus.root),
    }


def _client_as(viewer: Viewer) -> Client:
    client = Client()
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def _media_404_shape() -> tuple[bytes, frozenset[tuple[str, str]]]:
    from bundesarchiv.app.web.media_views import _not_found

    r = _not_found()
    volatile = {"Date", "Server", "X-Frame-Options", "Vary", "Content-Language"}
    return r.content, frozenset((k, v) for k, v in r.items() if k not in volatile)


def _404_shape(response: HttpResponseBase) -> tuple[bytes, frozenset[tuple[str, str]]]:
    volatile = {"Date", "Server", "X-Frame-Options", "Vary", "Content-Language"}
    headers = frozenset((k, v) for k, v in response.items() if k not in volatile)
    content: bytes = response.content  # type: ignore[attr-defined]
    return content, headers


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- deny suite (spec §6) — ZERO writes on every deny ------------------------------


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_bulk_denied_is_404_and_writes_nothing(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(
            "/artikel/sammelbearbeitung",
            {"auswahl": [_A, _B], "feld": "creator", "wert_text": "Gekapert", "bestaetigt": "1"},
        )
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    # nothing mutated
    assert corpus.article(_A).creator is None
    assert corpus.article(_B).creator is None


def test_bulk_get_is_404(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        assert _client_as(Archivist()).get("/artikel/sammelbearbeitung").status_code == 404


@pytest.mark.parametrize("feld", ["lifecycle", "audience", "ulid", "__class__", "sichtbarkeit"])
def test_forbidden_feld_writes_nothing(corpus: _Corpus, feld: str) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {"auswahl": [_A], "feld": feld, "wert_text": "x", "bestaetigt": "1"},
        )
    assert response.status_code == 200  # re-renders the confirm frame with the field error
    assert "Bitte ein Feld wählen." in response.content.decode()
    # the article is untouched (lifecycle/audience never bulk-editable)
    assert corpus.article(_A).lifecycle is Lifecycle.DRAFT


def test_empty_selection_is_error_no_write(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung", {"feld": "creator", "wert_text": "x", "bestaetigt": "1"}
        )
    assert "Keine Artikel ausgewählt." in response.content.decode()


def test_validation_error_re_renders_drawer_with_selection_preserved(corpus: _Corpus) -> None:
    # Design-gate blocker: a validation error must NOT dead-end and drop the selection (spec §2 C).
    # It re-renders the chooser drawer + the verbatim error, carrying every auswahl ulid as a hidden
    # input so the archivist fixes the value and re-submits from here — selection intact.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {"auswahl": [_A, _B], "feld": "", "wert_text": "x", "bestaetigt": "1"},
        )
    body = response.content.decode()
    assert "Bitte ein Feld wählen." in body  # verbatim error
    assert 'name="feld"' in body  # the drawer is re-rendered
    assert 'name="wert_text"' in body  # the value widgets are present
    # both selected ulids survive as hidden inputs (no dead-end, no dropped selection)
    assert f'name="auswahl" value="{_A}"' in body
    assert f'name="auswahl" value="{_B}"' in body


def test_collection_value_outside_set_same_as_empty(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {
                "auswahl": [_A],
                "feld": "collection_id",
                "wert_collection_id": "NOPE",
                "bestaetigt": "1",
            },
        )
    assert "Bitte einen Bestand wählen." in response.content.decode()
    assert corpus.article(_A).collection_id == "PUB"  # unchanged


# --- confirm phase (no bestaetigt) -------------------------------------------------


def test_confirm_page_lists_field_value_count_articles(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {"auswahl": [_A, _B], "feld": "creator", "wert_text": "K. Meyer"},
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Sammelbearbeitung prüfen" in body
    assert "Autor" in body  # the Feld label
    assert "K. Meyer" in body  # the new value
    assert "Betroffen: 2 Artikel" in body
    assert "Foto A" in body and "Foto B" in body  # the article list
    assert "Auf 2 Artikel anwenden" in body
    # confirm phase writes nothing
    assert corpus.article(_A).creator is None


def test_confirm_does_not_write(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung", {"auswahl": [_A], "feld": "creator", "wert_text": "X"}
        )
    assert corpus.article(_A).creator is None


# --- commit phase (bestaetigt=1) ---------------------------------------------------


def test_commit_applies_and_shows_result(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {"auswahl": [_A, _B], "feld": "creator", "wert_text": "K. Meyer", "bestaetigt": "1"},
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Sammelbearbeitung abgeschlossen" in body
    assert "2 Artikel gespeichert." in body
    assert corpus.article(_A).creator == "K. Meyer"
    assert corpus.article(_B).creator == "K. Meyer"


def test_commit_cas_race_loser_value_not_on_disk(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CAS honesty (spec §6.7): a bulk apply that loses the race on _A must report _A conflicted and
    # leave _A's value NOT on disk, while _B still saves. Force save_article to conflict for _A.
    from bundesarchiv.app import articles

    real_save = articles.save_article

    def _conflict_a(store_: object, article: Article, version: int) -> object:
        from bundesarchiv.persistence.errors import Conflict

        if article.ulid == _A:
            raise Conflict("raced")
        return real_save(store_, article, version)  # type: ignore[arg-type]

    monkeypatch.setattr(articles, "save_article", _conflict_a)
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {"auswahl": [_A, _B], "feld": "creator", "wert_text": "Bulk", "bestaetigt": "1"},
        )
    body = response.content.decode()
    assert "teilweise abgeschlossen" in body
    assert "1 gespeichert · 1 inzwischen geändert" in body
    assert "Foto A" in body  # the loser row is listed (c-sig + Titel)
    assert corpus.article(_A).creator is None  # loser value NOT on disk
    assert corpus.article(_B).creator == "Bulk"  # winner stands


def test_commit_custom_bag_upsert(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {"auswahl": [_A], "feld": "Quelle", "wert_text": "Nachlass", "bestaetigt": "1"},
        )
    assert dict(corpus.article(_A).custom)["Quelle"] == "Nachlass"


def test_commit_missing_ulid_bucketed(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {
                "auswahl": [_A, "01KX7YT9E3VX0CP3A5Q49RZMZZ"],
                "feld": "creator",
                "wert_text": "X",
                "bestaetigt": "1",
            },
        )
    body = response.content.decode()
    assert "1 Artikel gespeichert." in body
    assert "Nicht mehr vorhanden:" in body


# --- dependent pair (spec §3) ------------------------------------------------------


def test_document_type_mismatch_rejects_whole_apply(corpus: _Corpus) -> None:
    # _A has no media_type; Porträt (a Fotografie type) fits no article with a non-Fotografie/empty
    # media_type → whole apply rejected, zero writes (all-or-nothing, fail-closed).
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {
                "auswahl": [_A],
                "feld": "document_type",
                "wert_document_type": "Porträt",
                "bestaetigt": "1",
            },
        )
    body = response.content.decode()
    assert "gehört nicht zur Medienart aller ausgewählten Artikel" in body
    assert corpus.article(_A).document_type is None  # unchanged


def test_media_type_orphan_requires_leeren_flag(corpus: _Corpus) -> None:
    # give _A a Schriftgut + Brief pair; setting Medienart to Fotografie orphans Brief. A commit
    # WITHOUT dokumenttyp_leeren must NOT write — it re-confirms (server-enforced, spec §3).
    repo = ArticleRepository(corpus.store)
    stored = repo.load(_A)
    repo.save(
        Article(
            ulid=_A,
            title="Foto A",
            collection_id="PUB",
            media_type="Schriftgut",
            document_type="Brief",
        ),
        stored.version,
    )
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {
                "auswahl": [_A],
                "feld": "media_type",
                "wert_media_type": "Fotografie",
                "bestaetigt": "1",
            },
        )
    body = response.content.decode()
    assert "Medienart ändern — Achtung" in body  # re-confirm shown
    assert "Dokumenttyp: Brief → (leer)" in body
    assert corpus.article(_A).media_type == "Schriftgut"  # NOT written without the flag


def test_media_type_orphan_commits_with_leeren_flag(corpus: _Corpus) -> None:
    repo = ArticleRepository(corpus.store)
    stored = repo.load(_A)
    repo.save(
        Article(
            ulid=_A,
            title="Foto A",
            collection_id="PUB",
            media_type="Schriftgut",
            document_type="Brief",
        ),
        stored.version,
    )
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/sammelbearbeitung",
            {
                "auswahl": [_A],
                "feld": "media_type",
                "wert_media_type": "Fotografie",
                "bestaetigt": "1",
                "dokumenttyp_leeren": "1",
            },
        )
    assert "abgeschlossen" in response.content.decode()
    got = corpus.article(_A)
    assert got.media_type == "Fotografie"
    assert got.document_type is None  # orphan cleared


# --- dokumenttypen endpoint (ulid-free) --------------------------------------------


def test_bulk_dokumenttypen_archivist(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(
            "/artikel/sammelbearbeitung/dokumenttypen?media_type=Fotografie"
        )
    assert response.status_code == 200
    assert "Porträt" in response.content.decode()


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_bulk_dokumenttypen_denied_never_content(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).get(
            "/artikel/sammelbearbeitung/dokumenttypen?media_type=Fotografie"
        )
    assert response.status_code == 404
    assert b"Portr" not in response.content


def test_bulk_dokumenttypen_post_is_404(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        assert (
            _client_as(Archivist())
            .post("/artikel/sammelbearbeitung/dokumenttypen", {"media_type": "Fotografie"})
            .status_code
            == 404
        )
