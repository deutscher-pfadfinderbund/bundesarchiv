"""The full edit form ``/artikel/<ulid>/bearbeiten`` (Part 4.7 Slice B, spec §2/§3/§6.1/§8).

GET seeds the form from the stored Article; POST parses + saves under CAS (ADR 0013) and 302s to the
read view. Both methods are archivist-gated to the media route's byte-identical 404 for Member /
Public / anonymous, and for a malformed or absent ulid (existence-hiding). Validation re-renders
state F (verbatim error, preserved values). A raced concurrent save re-renders state G — the
"Inzwischen geändert" panel — with the loser's input preserved and a refreshed ``expected_version``.
The whole write path is REAL (repository + README + CAS); only the index + queue seams are stubbed
(see ``conftest.py``).
"""

from pathlib import Path

import pytest
from django.core import signing
from django.http.response import HttpResponseBase
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-catalog-edit-key"
_ULID = "01KX7YT9E3VX0CP3A5Q49RZMVH"


class _Corpus:
    """A tiny FS-store archive: two collections + one DRAFT article under PUB to edit."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        collections = CollectionRepository(self.store)
        collections.save(Collection("ROOT", "Wurzel", None), 0)
        collections.save(Collection("PUB", "Öffentlich", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        collections.save(Collection("MEM", "Mitglieder", "ROOT", Audience(AudienceTier.MEMBERS)), 0)
        self.version = ArticleRepository(self.store).save(
            Article(
                ulid=_ULID,
                title="Wanderfahrt 1962",
                collection_id="PUB",
                lifecycle=Lifecycle.DRAFT,
                ref_code="F 12/3",
            ),
            0,
        )


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


def _valid_post(corpus: _Corpus, **overrides: str) -> dict[str, str]:
    """A minimally-valid edit POST at the article's current version."""
    base = {
        "title": "Wanderfahrt 1962",
        "collection_id": "PUB",
        "ref_code": "F 12/3",
        "media_type": "Fotografie",
        "document_type": "",
        "tags": "",
        "date": "",
        "creator": "",
        "subject_place": "",
        "physical_location": "",
        "body": "",
        "sichtbarkeit": "",
        "gruppen": "",
        "expected_version": str(corpus.version),
    }
    base.update(overrides)
    return base


# --- GET: the seeded form ----------------------------------------------------------


def test_edit_form_renders_seeded_for_archivist(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten")
    assert response.status_code == 200
    body = response.content.decode()
    # the stored values are seeded into the form
    assert 'value="Wanderfahrt 1962"' in body
    assert 'value="F 12/3"' in body
    # the group drawers are present (spec §3)
    for legend in ("Kerndaten", "Einordnung", "Herkunft", "Beschreibung", "Zugriff"):
        assert legend in body
    assert "Weitere Angaben" in body  # Gruppe 7
    # the hidden expected_version rides the form
    assert f'name="expected_version" value="{corpus.version}"' in body
    # the ENTWURF badge (draft) sits in the header
    assert "Entwurf" in body
    # the Signatur mark reflects ref_code
    assert "F 12/3" in body


# --- GET/POST: archivist gate (both methods, all tiers) ---------------------------


@pytest.mark.parametrize("viewer", [Public(), Member(groups=("vorstand",))])
def test_edit_get_is_byte_identical_404_for_non_archivist(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).get(f"/artikel/{_ULID}/bearbeiten")
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()


@pytest.mark.parametrize("viewer", [Public(), Member(groups=("vorstand",))])
def test_edit_post_is_byte_identical_404_for_non_archivist(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(
            f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gekapert")
        )
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    # the non-archivist POST changed nothing
    assert ArticleRepository(corpus.store).load(_ULID).article.title == "Wanderfahrt 1962"


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_edit_malformed_or_absent_ulid_is_byte_identical_404(corpus: _Corpus, ulid: str) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{ulid}/bearbeiten")
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()


# --- POST: save success + read-view redirect ---------------------------------------


def test_edit_post_saves_and_redirects_to_read_view(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            _valid_post(corpus, title="Neuer Titel", creator="Kurt Meyer"),
        )
    assert response.status_code == 302
    assert response["Location"] == f"/artikel/{_ULID}"
    stored = ArticleRepository(corpus.store).load(_ULID)
    assert stored.article.title == "Neuer Titel"
    assert stored.article.creator == "Kurt Meyer"
    assert stored.version == corpus.version + 1


def test_edit_post_empties_optional_to_none(corpus: _Corpus) -> None:
    # Clearing the Signatur field must store None, not "" (the "" -> None boundary, spec §8).
    with override_settings(**_settings(corpus)):
        _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, ref_code="")
        )
    assert ArticleRepository(corpus.store).load(_ULID).article.ref_code is None


# --- POST: validation state F ------------------------------------------------------


def test_edit_post_missing_title_re_renders_state_f(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="", creator="Behalten")
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body
    assert 'value="Behalten"' in body  # the just-typed value is preserved
    # nothing saved
    assert ArticleRepository(corpus.store).load(_ULID).version == corpus.version


def test_edit_post_bad_document_type_pair_re_renders(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            _valid_post(corpus, media_type="Fotografie", document_type="Brief"),
        )
    assert response.status_code == 200
    # the straight closing quote in the verbatim string is HTML-escaped to &quot; in the render
    assert "Dieser Dokumenttyp gehört nicht zu „Fotografie&quot;." in response.content.decode()


# --- POST: CAS conflict state G (two racing clients through the real form) ---------


def test_raced_save_shows_conflict_panel_with_preserved_input(corpus: _Corpus) -> None:
    archivist = _client_as(Archivist())
    with override_settings(**_settings(corpus)):
        # Both clients load the form at the same version (corpus.version). The FIRST save wins.
        winner = archivist.post(
            f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gewinner")
        )
        assert winner.status_code == 302
        # The SECOND save carries the now-stale version -> Conflict -> state G re-render.
        loser = archivist.post(
            f"/artikel/{_ULID}/bearbeiten",
            _valid_post(corpus, title="Verlierer", creator="Meine Eingabe"),
        )
    assert loser.status_code == 200
    body = loser.content.decode()
    assert "Inzwischen geändert" in body  # the conflict panel heading
    assert "Verlierer" in body  # the loser's just-typed title is preserved
    assert 'value="Meine Eingabe"' in body  # and their other input
    # the diff lists the changed Titel field (winner's value vs mine)
    assert "Gewinner" in body
    # the store is at the WINNER's value + version (no last-writer-wins)
    stored = ArticleRepository(corpus.store).load(_ULID)
    assert stored.article.title == "Gewinner"
    assert stored.version == corpus.version + 1


def test_conflict_refreshes_expected_version_so_next_save_wins(corpus: _Corpus) -> None:
    archivist = _client_as(Archivist())
    with override_settings(**_settings(corpus)):
        archivist.post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gewinner"))
        loser = archivist.post(
            f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Verlierer")
        )
        body = loser.content.decode()
        # the re-rendered form now carries the WINNER's current version
        new_version = corpus.version + 1
        assert f'name="expected_version" value="{new_version}"' in body
        # re-submitting at that refreshed version now WINS
        retry = archivist.post(
            f"/artikel/{_ULID}/bearbeiten",
            _valid_post(corpus, title="Verlierer", expected_version=str(new_version)),
        )
    assert retry.status_code == 302
    assert ArticleRepository(corpus.store).load(_ULID).article.title == "Verlierer"


# --- autofocus (spec §5) -----------------------------------------------------------


def test_validation_re_render_autofocuses_first_errored_field(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="")
        )
    body = response.content.decode()
    # the Titel input carries autofocus (first errored field)
    assert 'name="title" value=""\n' in body or 'name="title" value="" autofocus' in body


# --- no-JS custom-row removal ------------------------------------------------------


def test_custom_entfernen_drops_the_row_without_saving(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                **_valid_post(corpus),
                "custom_key": ["Fotograf", "Auflage"],
                "custom_value": ["Meyer", "500"],
                "custom_entfernen": "0",
            },
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert 'value="Auflage"' in body  # the surviving row
    assert 'value="Meyer"' not in body  # the removed row's value is gone
    # nothing was saved (removal is a re-render, not a save)
    assert ArticleRepository(corpus.store).load(_ULID).version == corpus.version
