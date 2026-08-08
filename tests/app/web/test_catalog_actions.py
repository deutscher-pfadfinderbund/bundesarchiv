"""Read-view actions + lifecycle (Part 4.7 Slice C, spec §6.2/§7/§8).

Covers the four new routes and the read-view action row:

- ``/artikel/<ulid>/kopieren`` POST — copy to a fresh draft, 302 to the copy's edit form.
- ``/artikel/<ulid>/loeschen`` GET (confirm) + POST (execute) — hard-delete, 302 to workbench.
- the exposure statement on the edit render — what the retired over-exposure preview route (and its
  ``geprueft`` confirm checkbox) was replaced BY (owner ruling 5, 2026-08-08): the audience
  computation did not move, it is simply on screen. There is no lifecycle route left to cover: both
  verbs ride the edit form's own CAS write (tests/app/web/test_catalog_edit.py), and the standalone
  POST /lebenszyklus died with its UI-unreachable ``veroeffentlichen`` branch.
- the archivist action row on the detail stub (absent for non-archivists).

SECURITY is the load-bearing part (mutation-tested next review): every route archivist-gated for
BOTH methods → 404 for Member/Public/anon, and the deny tests assert the SIDE EFFECT
did not happen (nothing created / article still exists / lifecycle unchanged / no widget content).
The write path is REAL; only the index + queue seams are stubbed (see conftest.py).
"""

from dataclasses import replace
from pathlib import Path

import pytest
from django.core import signing
from django.test import Client, override_settings
from tests.app.web._asserts import assert_denied

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.access import project
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
                ref_code="F9",
            ),
            0,
        )
        self.pub_version = articles.save(
            Article(
                ulid=_PUBLISHED,
                title="Sommerfahrt 1962",
                collection_id="PUB",
                lifecycle=Lifecycle.PUBLISHED,
                ref_code="F12",
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


def _client_as(viewer: Viewer, *, enforce_csrf: bool = False) -> Client:
    client = Client(enforce_csrf_checks=enforce_csrf)
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


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
    assert_denied(response)
    assert _other_ulids(corpus) == set()  # nothing created


def test_kopieren_get_is_404(corpus: _Corpus) -> None:
    # a copy is a mutation — GET must not create.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_PUBLISHED}/kopieren")
    assert_denied(response)
    assert _other_ulids(corpus) == set()


# --- Löschen -----------------------------------------------------------------------


def test_loeschen_confirm_page_shows_context(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_PUBLISHED}/loeschen")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Artikel löschen?" in body
    assert "Sommerfahrt 1962" in body  # Titel context
    assert "F12" in body  # Signatur context
    assert "Ein Papierkorb steht in dieser Version nicht zur Verfügung." in body
    assert "Endgültig löschen" in body


def test_loeschen_confirm_page_verwerfen_wording(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_DRAFT}/loeschen?verwerfen=1")
    body = response.content.decode()
    assert "Entwurf verwerfen?" in body
    assert "Entwurf verwerfen" in body


def test_loeschen_verwerfen_wording_only_for_drafts(corpus: _Corpus) -> None:
    # A PUBLISHED article + ?verwerfen=1 is deleted, not discarded — server ignores the param and
    # shows the plain "Artikel löschen?" wording (behaviour identical, wording honest).
    with override_settings(**_settings(corpus)):
        body = (
            _client_as(Archivist())
            .get(f"/artikel/{_PUBLISHED}/loeschen?verwerfen=1")
            .content.decode()
        )
    assert "Artikel löschen?" in body
    assert "Entwurf verwerfen" not in body


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
    assert_denied(response)
    # the article still exists (the deny prevented the delete)
    assert ArticleRepository(corpus.store).load(_PUBLISHED).article.title == "Sommerfahrt 1962"


# --- the exposure statement (what replaced the publish gate) -----------------------


def test_edit_form_states_the_exposure_permanently(corpus: _Corpus) -> None:
    # What replaced the gate: the who-gains-sight fact is on the edit render itself (owner ruling 5),
    # computed by the domain preview() — for a DRAFT in the future tense, since a draft is
    # archivist-only until it is published. This is the fact the archivist used to buy with three
    # extra interactions.
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_DRAFT}/bearbeiten").content.decode()
    assert "Nach Veröffentlichung sichtbar für" in body
    assert "Öffentlich" in body  # the PUB collection is PUBLIC, so publishing would expose it
    assert "Sichtbare Felder:" in body
    assert "Verborgen: Standort, interne Felder." in body


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_edit_form_exposure_is_archivist_only(corpus: _Corpus, viewer: Viewer) -> None:
    # The exposure statement is the SAME oracle the retired /vorschau route was: preview() bypasses
    # the lifecycle gate by design, so it must never reach a non-archivist. Its only barrier is the
    # edit route's own archivist gate — deny is a plain 404 that reveals nothing.
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).get(f"/artikel/{_DRAFT}/bearbeiten")
    assert_denied(response)
    body = response.content.decode()
    assert "sichtbar für" not in body
    assert "Sichtbare Felder" not in body


def test_the_readers_sheet_is_built_from_the_reader_projection(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The app owns ONE reader pipeline (article_auth.resolve_visible_* -> access.visible = can_view +
    # project), and a box labelled aria-label="Leseansicht" must show what project() produces. That
    # cannot be proven from the RENDER today: project floors exactly {physical_location, custom} and
    # the sheet shows neither, so reading the stored Article printed identical bytes — equality by
    # coincidence (G.22) on the very surface whose promise retired the publish gate. What CAN be
    # proven is that the projection is IN THE PATH, so the floor already holds the day a field joins
    # ARCHIVIST_ONLY_FIELDS: floor a field the sheet does read and watch only the SHEET follow.
    def floor_the_title(viewer: Viewer, article: Article) -> Article:
        return replace(project(viewer, article), title="GEFLOORT")

    monkeypatch.setattr("bundesarchiv.app.web.catalog_views.project", floor_the_title)
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_DRAFT}/bearbeiten").content.decode()
    assert "<h2>GEFLOORT</h2>" in body, "the reader's sheet does not go through access.project()"
    # ...and the EDITABLE card still shows the stored record: the projection is the reader's view of
    # the record, never a filter on what the archivist may type into it.
    assert 'value="Entwurf Lagerchronik"' in body


def test_the_readers_sheet_prints_the_title_plain(corpus: _Corpus) -> None:
    # The sheet used to invent `default:"Ohne Titel"` — a sheet-only spelling of an absence no reader
    # surface names (the pane prints {{ pane.title }} plain), i.e. one renderer more than law C7
    # allows for the fact. A stored record with an empty Titel is only reachable past the form's own
    # validation, and even then the sheet stays silent about it.
    untitled = "01KX7YT9E3VX0CP3A5Q49RZMWN"
    ArticleRepository(corpus.store).save(
        Article(ulid=untitled, title="", collection_id="PUB", lifecycle=Lifecycle.DRAFT), 0
    )
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{untitled}/bearbeiten").content.decode()
    assert "Ohne Titel" not in body


# --- fail-closed: no exposure statement, no publish affordance (learning G.34) ------

_UNRESOLVABLE = "01KX7YT9E3VX0CP3A5Q49RZMWQ"


def _article_whose_bestand_chain_is_broken(corpus: _Corpus) -> str:
    """Save an article filed under a collection whose PARENT does not exist, so ``resolve_chain``
    raises ``BrokenCollectionTree`` and ``preview()`` can compute no exposure at all. The collection
    itself IS in the store, so the Bestand select still offers it and the edit form renders."""
    CollectionRepository(corpus.store).save(
        Collection("WAISE", "Waise", "FEHLT", Audience(AudienceTier.PUBLIC)), 0
    )
    ArticleRepository(corpus.store).save(
        Article(
            ulid=_UNRESOLVABLE,
            title="Ohne Bestandskette",
            collection_id="WAISE",
            lifecycle=Lifecycle.DRAFT,
        ),
        0,
    )
    return _UNRESOLVABLE


def test_an_unresolvable_bestand_chain_blocks_publishing(corpus: _Corpus) -> None:
    # The retired preview gate BLOCKED publishing when the audience chain could not be resolved — its
    # required `geprueft` checkbox lived inside the branch that rendered the statement. The permanent
    # statement inherited the promise but not the teeth: the view-model was None, the statement
    # rendered as nothing at all, and Veröffentlichen stayed one click away (G.34). Both halves are
    # asserted here: the absence is STATED, and the affordance is gone.
    ulid = _article_whose_bestand_chain_is_broken(corpus)
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{ulid}/bearbeiten").content.decode()
    assert "Einblick nicht ermittelbar." in body
    # the affordance itself is gone — asserted on the submit that carries the verb, because the
    # German note deliberately NAMES Veröffentlichen to say it is locked
    assert 'value="veroeffentlichen"' not in body
    # a resolvable record is unaffected — the gate is the missing FACT, not the screen
    with override_settings(**_settings(corpus)):
        ok = _client_as(Archivist()).get(f"/artikel/{_DRAFT}/bearbeiten").content.decode()
    assert 'value="veroeffentlichen"' in ok
    assert "Einblick nicht ermittelbar." not in ok


# --- malformed / absent ulid across every new route --------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/artikel/not-a-ulid/kopieren",
        "/artikel/not-a-ulid/loeschen",
        "/artikel/01BX5ZZKBKACTAV9WEVGEMMVRZ/loeschen",  # well-formed but absent
    ],
)
def test_malformed_or_absent_ulid_is_404(corpus: _Corpus, path: str) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(path)
    assert_denied(response)


# --- read-view action row ----------------------------------------------------------


def test_detail_action_row_present_for_archivist(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_PUBLISHED}").content.decode()
    assert 'class="actions"' in body
    assert f"/artikel/{_PUBLISHED}/bearbeiten" in body
    assert f"/artikel/{_PUBLISHED}/kopieren" in body
    assert f"/artikel/{_PUBLISHED}/loeschen" in body
    # published article → the unpublish action, not Veröffentlichen
    assert "Als Entwurf zurückziehen" in body


def test_detail_action_row_absent_for_non_archivist(corpus: _Corpus) -> None:
    # PUB is public, so Public can VIEW the published article — but the action row must be ABSENT.
    with override_settings(**_settings(corpus)):
        body = _client_as(Public()).get(f"/artikel/{_PUBLISHED}").content.decode()
    assert 'class="actions"' not in body
    assert "/kopieren" not in body
    assert "/loeschen" not in body


def test_detail_action_row_draft_shows_veroeffentlichen(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_DRAFT}").content.decode()
    assert "Veröffentlichen" in body
    assert "Als Entwurf zurückziehen" not in body


# --- template-comment hygiene (a multi-line {# #} leaks — same rule as the workbench) ----------


def test_no_leaked_template_comment(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_DRAFT}").content.decode()
    assert "{#" not in body  # a multi-line {# #} would leak into the rendered page


# --- CSRF enforcement (fix wave: prod/dev now run CsrfViewMiddleware) ---------------


def test_destructive_post_without_csrf_token_is_403(corpus: _Corpus) -> None:
    # A cross-site destructive POST with no CSRF token must be rejected (CsrfViewMiddleware active).
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist(), enforce_csrf=True).post(
            f"/artikel/{_PUBLISHED}/loeschen"
        )
    assert response.status_code == 403
    # the article is untouched — the forged POST was rejected before hard_delete ran
    assert ArticleRepository(corpus.store).load(_PUBLISHED).article.title == "Sommerfahrt 1962"


def test_destructive_post_with_csrf_token_works(corpus: _Corpus) -> None:
    # The legitimate flow — GET the confirm page (sets the csrf cookie + token), then POST with it.
    with override_settings(**_settings(corpus)):
        client = _client_as(Archivist(), enforce_csrf=True)
        client.get(f"/artikel/{_PUBLISHED}/loeschen")  # seeds the csrf cookie
        token = client.cookies["csrftoken"].value
        response = client.post(f"/artikel/{_PUBLISHED}/loeschen", {"csrfmiddlewaretoken": token})
    assert response.status_code == 302  # accepted → hard-deleted → redirect
    with pytest.raises(NotFound):
        ArticleRepository(corpus.store).load(_PUBLISHED)
