"""Read-view actions + lifecycle (Part 4.7 Slice C, spec §6.2/§7/§8).

Covers the four new routes and the read-view action row:

- ``/artikel/<ulid>/kopieren`` POST — copy to a fresh draft, 302 to the copy's edit form.
- ``/artikel/<ulid>/loeschen`` GET (confirm) + POST (execute) — hard-delete, 302 to workbench.
- ``/artikel/<ulid>/lebenszyklus`` POST — publish (gated by the over-exposure confirm) / unpublish.
- ``/artikel/<ulid>/vorschau`` POST — the over-exposure preview (highest-risk oracle).
- the archivist action row on the detail stub (absent for non-archivists).

SECURITY is the load-bearing part (mutation-tested next review): every route archivist-gated for
BOTH methods → byte-identical 404 for Member/Public/anon, and the deny tests assert the SIDE EFFECT
did not happen (nothing created / article still exists / lifecycle unchanged / no widget content).
The write path is REAL; only the index + queue seams are stubbed (see conftest.py).
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
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-catalog-actions-key"
_DRAFT = "01KX7YT9E3VX0CP3A5Q49RZMVH"
_PUBLISHED = "01KX7YT9E3VX0CP3A5Q49RZMWK"


class _Corpus:
    """A FS-store archive: PUB collection + one DRAFT and one PUBLISHED article to act on."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        collections = CollectionRepository(self.store)
        collections.save(Collection("ROOT", "Wurzel", None), 0)
        collections.save(Collection("PUB", "Öffentlich", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        articles = ArticleRepository(self.store)
        self.draft_version = articles.save(
            Article(
                ulid=_DRAFT,
                title="Entwurf Lagerchronik",
                collection_id="PUB",
                lifecycle=Lifecycle.DRAFT,
                ref_code="F 9",
            ),
            0,
        )
        self.pub_version = articles.save(
            Article(
                ulid=_PUBLISHED,
                title="Sommerfahrt 1962",
                collection_id="PUB",
                lifecycle=Lifecycle.PUBLISHED,
                ref_code="F 12",
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


def _other_ulids(corpus: _Corpus) -> set[str]:
    return set(ArticleRepository(corpus.store).list_ulids()) - {_DRAFT, _PUBLISHED}


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- Kopieren ----------------------------------------------------------------------


def test_kopieren_creates_draft_copy_and_redirects_to_its_edit_form(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(f"/artikel/{_PUBLISHED}/kopieren")
    assert response.status_code == 302
    new = _other_ulids(corpus)
    assert len(new) == 1
    new_ulid = new.pop()
    # 302 to the copy's edit form with the Signatur autofocus hint (spec §5)
    assert response["Location"] == f"/artikel/{new_ulid}/bearbeiten?fokus=signatur"
    copy = ArticleRepository(corpus.store).load(new_ulid).article
    assert copy.ref_code is None  # Signatur cleared (spec §7)
    assert copy.lifecycle is Lifecycle.DRAFT
    assert copy.media == ()
    assert copy.title == "Sommerfahrt 1962"  # metadata carried over


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_kopieren_denied_creates_nothing(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(f"/artikel/{_PUBLISHED}/kopieren")
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    assert _other_ulids(corpus) == set()  # nothing created


def test_kopieren_get_is_404(corpus: _Corpus) -> None:
    # a copy is a mutation — GET must not create.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_PUBLISHED}/kopieren")
    assert response.status_code == 404
    assert _other_ulids(corpus) == set()


# --- Löschen -----------------------------------------------------------------------


def test_loeschen_confirm_page_shows_context(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_PUBLISHED}/loeschen")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Artikel löschen?" in body
    assert "Sommerfahrt 1962" in body  # Titel context
    assert "F 12" in body  # Signatur context
    assert "Ein Papierkorb steht in dieser Version nicht zur Verfügung." in body
    assert "c-btn--gefahr" in body  # the ONE loud button
    assert "Endgültig löschen" in body


def test_loeschen_confirm_page_verwerfen_wording(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_DRAFT}/loeschen?verwerfen=1")
    body = response.content.decode()
    assert "Entwurf verwerfen?" in body
    assert "Entwurf verwerfen" in body


def test_loeschen_post_hard_deletes_and_redirects_to_workbench(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(f"/artikel/{_PUBLISHED}/loeschen")
    assert response.status_code == 302
    assert response["Location"] == "/"
    with pytest.raises(NotFound):
        ArticleRepository(corpus.store).load(_PUBLISHED)


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
@pytest.mark.parametrize("method", ["get", "post"])
def test_loeschen_denied_leaves_article(corpus: _Corpus, viewer: Viewer, method: str) -> None:
    with override_settings(**_settings(corpus)):
        response = getattr(_client_as(viewer), method)(f"/artikel/{_PUBLISHED}/loeschen")
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    # the article still exists (the deny prevented the delete)
    assert ArticleRepository(corpus.store).load(_PUBLISHED).article.title == "Sommerfahrt 1962"


# --- Lebenszyklus (publish / unpublish) --------------------------------------------


def test_publish_with_confirm_sets_published(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_DRAFT}/lebenszyklus",
            {
                "aktion": "veroeffentlichen",
                "geprueft": "1",
                "expected_version": str(corpus.draft_version),
            },
        )
    assert response.status_code == 302
    assert response["Location"] == f"/artikel/{_DRAFT}"
    assert ArticleRepository(corpus.store).load(_DRAFT).article.lifecycle is Lifecycle.PUBLISHED


def test_publish_without_confirm_reshows_preview_and_stays_draft(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_DRAFT}/lebenszyklus",
            {"aktion": "veroeffentlichen", "expected_version": str(corpus.draft_version)},
        )
    assert response.status_code == 200  # re-render, not a redirect
    assert "Wer bekommt nach Veröffentlichung Einblick?" in response.content.decode()
    # NOT published — the confirm gate held
    assert ArticleRepository(corpus.store).load(_DRAFT).article.lifecycle is Lifecycle.DRAFT


def test_unpublish_sets_draft(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_PUBLISHED}/lebenszyklus",
            {"aktion": "zurueckziehen", "expected_version": str(corpus.pub_version)},
        )
    assert response.status_code == 302
    assert ArticleRepository(corpus.store).load(_PUBLISHED).article.lifecycle is Lifecycle.DRAFT


def test_lifecycle_unknown_aktion_is_404_no_mutation(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_DRAFT}/lebenszyklus",
            {"aktion": "sabotage", "expected_version": str(corpus.draft_version)},
        )
    assert response.status_code == 404
    assert ArticleRepository(corpus.store).load(_DRAFT).article.lifecycle is Lifecycle.DRAFT


def test_lifecycle_stale_version_shows_conflict_panel(corpus: _Corpus) -> None:
    archivist = _client_as(Archivist())
    with override_settings(**_settings(corpus)):
        # a concurrent edit bumps the version
        archivist.post(
            f"/artikel/{_DRAFT}/lebenszyklus",
            {"aktion": "zurueckziehen", "expected_version": str(corpus.draft_version)},
        )
        # now publish at the STALE version -> Conflict -> state G
        loser = archivist.post(
            f"/artikel/{_DRAFT}/lebenszyklus",
            {
                "aktion": "veroeffentlichen",
                "geprueft": "1",
                "expected_version": str(corpus.draft_version),
            },
        )
    assert loser.status_code == 200
    assert "Inzwischen geändert" in loser.content.decode()


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_lifecycle_denied_leaves_lifecycle(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(
            f"/artikel/{_DRAFT}/lebenszyklus",
            {
                "aktion": "veroeffentlichen",
                "geprueft": "1",
                "expected_version": str(corpus.draft_version),
            },
        )
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    assert ArticleRepository(corpus.store).load(_DRAFT).article.lifecycle is Lifecycle.DRAFT


def test_lifecycle_get_is_404(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_DRAFT}/lebenszyklus")
    assert response.status_code == 404


# --- Vorschau (the highest-risk oracle) --------------------------------------------


def test_vorschau_renders_preview_panel_for_archivist(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(f"/artikel/{_DRAFT}/vorschau")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Wer bekommt nach Veröffentlichung Einblick?" in body
    assert "Ich habe geprüft, wer Einblick erhält." in body  # the confirm checkbox
    assert "Sichtbare Felder:" in body
    # PUB collection is PUBLIC → the article would be publicly visible
    assert "Öffentlich" in body


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_vorschau_denied_is_byte_identical_404_never_widget(
    corpus: _Corpus, viewer: Viewer
) -> None:
    # THE highest-risk oracle: preview() bypasses the lifecycle gate, so the ROUTE gate is the sole
    # barrier. A non-archivist must get the byte-identical 404 and NEVER the widget content.
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(f"/artikel/{_DRAFT}/vorschau")
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    body = response.content.decode()
    assert "Einblick" not in body  # no widget content leaked
    assert "Sichtbare Felder" not in body


def test_vorschau_get_is_404(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_DRAFT}/vorschau")
    assert response.status_code == 404


# --- malformed / absent ulid across every new route --------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/artikel/not-a-ulid/kopieren",
        "/artikel/not-a-ulid/loeschen",
        "/artikel/not-a-ulid/lebenszyklus",
        "/artikel/not-a-ulid/vorschau",
        "/artikel/01BX5ZZKBKACTAV9WEVGEMMVRZ/loeschen",  # well-formed but absent
    ],
)
def test_malformed_or_absent_ulid_is_byte_identical_404(corpus: _Corpus, path: str) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(path)
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()


# --- read-view action row ----------------------------------------------------------


def test_detail_action_row_present_for_archivist(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_PUBLISHED}").content.decode()
    assert "c-artikel-aktionen" in body
    assert f"/artikel/{_PUBLISHED}/bearbeiten" in body
    assert f"/artikel/{_PUBLISHED}/kopieren" in body
    assert f"/artikel/{_PUBLISHED}/loeschen" in body
    # published article → the unpublish action, not Veröffentlichen
    assert "Als Entwurf zurückziehen" in body


def test_detail_action_row_absent_for_non_archivist(corpus: _Corpus) -> None:
    # PUB is public, so Public can VIEW the published article — but the action row must be ABSENT.
    with override_settings(**_settings(corpus)):
        body = _client_as(Public()).get(f"/artikel/{_PUBLISHED}").content.decode()
    assert "c-artikel-aktionen" not in body
    assert "/kopieren" not in body
    assert "/loeschen" not in body


def test_detail_action_row_draft_shows_veroeffentlichen(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_DRAFT}").content.decode()
    assert "Veröffentlichen" in body
    assert "Als Entwurf zurückziehen" not in body
