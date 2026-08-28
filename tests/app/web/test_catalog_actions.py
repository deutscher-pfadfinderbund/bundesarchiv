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

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    DRAFT_ULID,
    PUBLISHED_ULID,
    Corpus,
    client_as,
    make_article,
    make_collection,
)

from bundesarchiv.domain.access import project
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.errors import NotFound


def _other_ulids(corpus: Corpus) -> set[str]:
    return set(corpus.articles.list_ulids()) - {DRAFT_ULID, PUBLISHED_ULID}


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- Kopieren ----------------------------------------------------------------------


def test_kopieren_creates_draft_copy_and_redirects_to_its_edit_form(corpus: Corpus) -> None:
    response = client_as(Archivist()).post(f"/artikel/{PUBLISHED_ULID}/kopieren")
    assert response.status_code == 302
    new = _other_ulids(corpus)
    assert len(new) == 1
    new_ulid = new.pop()
    # 302 to the copy's edit form with the Signatur autofocus hint (spec §5)
    assert response["Location"] == f"/artikel/{new_ulid}/bearbeiten?fokus=signatur"
    copy = corpus.articles.load(new_ulid).article
    assert copy.ref_code is None  # Signatur cleared (spec §7)
    assert copy.lifecycle is Lifecycle.DRAFT
    assert copy.media == ()
    assert copy.title == "Sommerfahrt 1962"  # metadata carried over


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_kopieren_denied_creates_nothing(corpus: Corpus, viewer: Viewer) -> None:
    response = client_as(viewer).post(f"/artikel/{PUBLISHED_ULID}/kopieren")
    assert_denied(response)
    assert _other_ulids(corpus) == set()  # nothing created


def test_kopieren_get_is_404(corpus: Corpus) -> None:
    # a copy is a mutation — GET must not create.
    response = client_as(Archivist()).get(f"/artikel/{PUBLISHED_ULID}/kopieren")
    assert_denied(response)
    assert _other_ulids(corpus) == set()


# --- Löschen -----------------------------------------------------------------------


def test_loeschen_confirm_page_shows_context(corpus: Corpus) -> None:
    response = client_as(Archivist()).get(f"/artikel/{PUBLISHED_ULID}/loeschen")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Artikel löschen?" in body
    assert "Sommerfahrt 1962" in body  # Titel context
    assert "F12" in body  # Signatur context
    assert "Ein Papierkorb steht in dieser Version nicht zur Verfügung." in body
    assert "Endgültig löschen" in body


def test_loeschen_confirm_page_verwerfen_wording(corpus: Corpus) -> None:
    response = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}/loeschen?verwerfen=1")
    body = response.content.decode()
    assert "Entwurf verwerfen?" in body
    assert "Entwurf verwerfen" in body


def test_loeschen_verwerfen_wording_only_for_drafts(corpus: Corpus) -> None:
    # A PUBLISHED article + ?verwerfen=1 is deleted, not discarded — server ignores the param and
    # shows the plain "Artikel löschen?" wording (behaviour identical, wording honest).
    body = (
        client_as(Archivist())
        .get(f"/artikel/{PUBLISHED_ULID}/loeschen?verwerfen=1")
        .content.decode()
    )
    assert "Artikel löschen?" in body
    assert "Entwurf verwerfen" not in body


def test_loeschen_post_hard_deletes_and_redirects_to_workbench(corpus: Corpus) -> None:
    response = client_as(Archivist()).post(f"/artikel/{PUBLISHED_ULID}/loeschen")
    assert response.status_code == 302
    assert response["Location"] == "/"
    with pytest.raises(NotFound):
        corpus.articles.load(PUBLISHED_ULID)


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
@pytest.mark.parametrize("method", ["get", "post"])
def test_loeschen_denied_leaves_article(corpus: Corpus, viewer: Viewer, method: str) -> None:
    response = getattr(client_as(viewer), method)(f"/artikel/{PUBLISHED_ULID}/loeschen")
    assert_denied(response)
    # the article still exists (the deny prevented the delete)
    assert corpus.articles.load(PUBLISHED_ULID).article.title == "Sommerfahrt 1962"


# --- the exposure statement (what replaced the publish gate) -----------------------


def test_edit_form_states_the_exposure_permanently(corpus: Corpus) -> None:
    # What replaced the gate: the who-gains-sight fact is on the edit render itself (owner ruling 5),
    # computed by the domain preview() — for a DRAFT in the future tense, since a draft is
    # archivist-only until it is published. This is the fact the archivist used to buy with three
    # extra interactions.
    body = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}/bearbeiten").content.decode()
    assert "Nach Veröffentlichung sichtbar für" in body
    assert "Öffentlich" in body  # the PUB collection is PUBLIC, so publishing would expose it
    assert "Sichtbare Felder:" in body
    assert "Verborgen: Standort, interne Felder." in body


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_edit_form_exposure_is_archivist_only(corpus: Corpus, viewer: Viewer) -> None:
    # The exposure statement is the SAME oracle the retired /vorschau route was: preview() bypasses
    # the lifecycle gate by design, so it must never reach a non-archivist. Its only barrier is the
    # edit route's own archivist gate — deny is a plain 404 that reveals nothing.
    response = client_as(viewer).get(f"/artikel/{DRAFT_ULID}/bearbeiten")
    assert_denied(response)
    body = response.content.decode()
    assert "sichtbar für" not in body
    assert "Sichtbare Felder" not in body


def test_the_readers_sheet_is_built_from_the_reader_projection(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
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
    body = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}/bearbeiten").content.decode()
    assert "<h2>GEFLOORT</h2>" in body, "the reader's sheet does not go through access.project()"
    # ...and the EDITABLE card still shows the stored record: the projection is the reader's view of
    # the record, never a filter on what the archivist may type into it.
    assert 'value="Entwurf Lagerchronik"' in body


def test_the_readers_sheet_prints_the_title_plain(corpus: Corpus) -> None:
    # The sheet used to invent `default:"Ohne Titel"` — a sheet-only spelling of an absence no reader
    # surface names (the pane prints {{ pane.title }} plain), i.e. one renderer more than law C7
    # allows for the fact. A stored record with an empty Titel is only reachable past the form's own
    # validation, and even then the sheet stays silent about it.
    untitled = "01KX7YT9E3VX0CP3A5Q49RZMWN"
    corpus.add_article(make_article(untitled, title="", lifecycle=Lifecycle.DRAFT))
    body = client_as(Archivist()).get(f"/artikel/{untitled}/bearbeiten").content.decode()
    assert "Ohne Titel" not in body


# --- fail-closed: no exposure statement, no publish affordance (learning G.34) ------

_UNRESOLVABLE = "01KX7YT9E3VX0CP3A5Q49RZMWQ"


def _article_whose_bestand_chain_is_broken(corpus: Corpus) -> str:
    """Save an article filed under a collection whose PARENT does not exist, so ``resolve_chain``
    raises ``BrokenCollectionTree`` and ``preview()`` can compute no exposure at all. The collection
    itself IS in the store, so the Bestand select still offers it and the edit form renders."""
    corpus.add_collection(make_collection("WAISE", "Waise", "FEHLT", Audience(AudienceTier.PUBLIC)))
    corpus.add_article(
        make_article(
            _UNRESOLVABLE,
            collection_id="WAISE",
            lifecycle=Lifecycle.DRAFT,
            title="Ohne Bestandskette",
        )
    )
    return _UNRESOLVABLE


def test_an_unresolvable_bestand_chain_blocks_publishing(corpus: Corpus) -> None:
    # The retired preview gate BLOCKED publishing when the audience chain could not be resolved — its
    # required `geprueft` checkbox lived inside the branch that rendered the statement. The permanent
    # statement inherited the promise but not the teeth: the view-model was None, the statement
    # rendered as nothing at all, and Veröffentlichen stayed one click away (G.34). Both halves are
    # asserted here: the absence is STATED, and the affordance is gone.
    ulid = _article_whose_bestand_chain_is_broken(corpus)
    body = client_as(Archivist()).get(f"/artikel/{ulid}/bearbeiten").content.decode()
    assert "Einblick nicht ermittelbar." in body
    # the affordance itself is gone — asserted on the submit that carries the verb, because the
    # German note deliberately NAMES Veröffentlichen to say it is locked
    assert 'value="veroeffentlichen"' not in body
    # a resolvable record is unaffected — the gate is the missing FACT, not the screen
    ok = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}/bearbeiten").content.decode()
    assert 'value="veroeffentlichen"' in ok
    assert "Einblick nicht ermittelbar." not in ok


def _publish_post(corpus: Corpus, ulid: str, **overrides: str) -> dict[str, str]:
    """A form POST carrying the publish verb, at the article's current version so CAS passes."""
    version = corpus.articles.load(ulid).version
    return {
        "title": "Ohne Bestandskette",
        "collection_id": "WAISE",
        "media_type": "Fotografie",
        "expected_version": str(version),
        "lebenszyklus": "veroeffentlichen",
        **overrides,
    }


def test_publishing_an_unresolvable_chain_is_refused_by_the_SERVER(corpus: Corpus) -> None:
    # The render half above hides the affordance; this is the half that actually holds. The gate was
    # UI-only, and the state is reachable with ordinary UI actions: re-parent a Bestand under a missing
    # parent (the article's own version is untouched, so CAS passes), then POST Veröffentlichen — the
    # record stored as PUBLISHED and then 404'd for everyone, its own cataloguer included, and went live
    # at whatever rung a later repair produced with no archivist having read an exposure statement. The
    # deleted lifecycle route said it in its own docstring: server-enforced, not just the client-side
    # required attr.
    ulid = _article_whose_bestand_chain_is_broken(corpus)
    before = corpus.articles.load(ulid)
    response = client_as(Archivist()).post(
        f"/artikel/{ulid}/bearbeiten", _publish_post(corpus, ulid, title="Frisch getippt")
    )
    assert response.status_code == 200  # a re-render, exactly like a validation failure
    after = corpus.articles.load(ulid)
    assert after.article.lifecycle is Lifecycle.DRAFT  # nothing published
    assert after.version == before.version  # ...and nothing written at all
    body = response.content.decode()
    assert "Der Bestand lässt sich nicht auflösen — Veröffentlichen ist gesperrt." in body
    assert 'value="Frisch getippt"' in body  # the archivist's input is preserved


def test_withdrawing_an_unresolvable_chain_stays_allowed(corpus: Corpus) -> None:
    # The refusal is about PUBLISHING. Taking a record back off the shelf needs no exposure fact, and
    # refusing it would strand a published record with a broken chain published forever.
    ulid = _article_whose_bestand_chain_is_broken(corpus)
    articles = corpus.articles
    articles.save(replace(articles.load(ulid).article, lifecycle=Lifecycle.PUBLISHED), 1)
    response = client_as(Archivist()).post(
        f"/artikel/{ulid}/bearbeiten",
        _publish_post(corpus, ulid, lebenszyklus="zurueckziehen"),
    )
    assert response.status_code == 302
    assert articles.load(ulid).article.lifecycle is Lifecycle.DRAFT


# --- malformed / absent ulid across every new route --------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/artikel/not-a-ulid/kopieren",
        "/artikel/not-a-ulid/loeschen",
        "/artikel/01BX5ZZKBKACTAV9WEVGEMMVRZ/loeschen",  # well-formed but absent
    ],
)
def test_malformed_or_absent_ulid_is_404(corpus: Corpus, path: str) -> None:
    response = client_as(Archivist()).post(path)
    assert_denied(response)


# --- read-view action row ----------------------------------------------------------


def test_detail_action_row_present_for_archivist(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/artikel/{PUBLISHED_ULID}").content.decode()
    assert 'class="actions"' in body
    assert f"/artikel/{PUBLISHED_ULID}/bearbeiten" in body
    assert f"/artikel/{PUBLISHED_ULID}/kopieren" in body
    assert f"/artikel/{PUBLISHED_ULID}/loeschen" in body
    # published article → the unpublish action, not Veröffentlichen
    assert "Als Entwurf zurückziehen" in body


def test_detail_action_row_absent_for_non_archivist(corpus: Corpus) -> None:
    # PUB is public, so Public can VIEW the published article — but the action row must be ABSENT.
    body = client_as(Public()).get(f"/artikel/{PUBLISHED_ULID}").content.decode()
    assert 'class="actions"' not in body
    assert "/kopieren" not in body
    assert "/loeschen" not in body


def test_detail_action_row_draft_shows_veroeffentlichen(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}").content.decode()
    assert "Veröffentlichen" in body
    assert "Als Entwurf zurückziehen" not in body


# --- template-comment hygiene (a multi-line {# #} leaks — same rule as the workbench) ----------


def test_no_leaked_template_comment(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}").content.decode()
    assert "{#" not in body  # a multi-line {# #} would leak into the rendered page


# --- CSRF enforcement (fix wave: prod/dev now run CsrfViewMiddleware) ---------------


def test_destructive_post_without_csrf_token_is_403(corpus: Corpus) -> None:
    # A cross-site destructive POST with no CSRF token must be rejected (CsrfViewMiddleware active).
    response = client_as(Archivist(), enforce_csrf=True).post(f"/artikel/{PUBLISHED_ULID}/loeschen")
    assert response.status_code == 403
    # the article is untouched — the forged POST was rejected before hard_delete ran
    assert corpus.articles.load(PUBLISHED_ULID).article.title == "Sommerfahrt 1962"


def test_destructive_post_with_csrf_token_works(corpus: Corpus) -> None:
    # The legitimate flow — GET the confirm page (sets the csrf cookie + token), then POST with it.
    client = client_as(Archivist(), enforce_csrf=True)
    client.get(f"/artikel/{PUBLISHED_ULID}/loeschen")  # seeds the csrf cookie
    token = client.cookies["csrftoken"].value
    response = client.post(f"/artikel/{PUBLISHED_ULID}/loeschen", {"csrfmiddlewaretoken": token})
    assert response.status_code == 302  # accepted → hard-deleted → redirect
    with pytest.raises(NotFound):
        corpus.articles.load(PUBLISHED_ULID)
