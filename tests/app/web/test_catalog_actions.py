"""Read-view actions + lifecycle (Part 4.7 Slice C, spec §6.2/§7/§8).

Covers the four new routes and the read-view action row:

- ``/artikel/<ulid>/kopieren`` POST — copy to a fresh draft, 302 to the copy's edit form.
- ``/artikel/<ulid>/loeschen`` GET (confirm) + POST (execute) — hard-delete, 302 to workbench.
- the fail-closed publish affordance: no exposure, no Veröffentlichen.
- ``/artikel/<ulid>/veroeffentlichen`` POST — publish a draft from the article page (a3 round 7):
  CAS on the page's version, the same fail-closed gate as the edit form's Status.
- the archivist action row on the detail stub (absent for non-archivists).

SECURITY is the load-bearing part (mutation-tested next review): every route archivist-gated for
BOTH methods → 404 for Member/Public/anon, and the deny tests assert the SIDE EFFECT
did not happen (nothing created / article still exists / lifecycle unchanged / no widget content).
The write path is REAL; only the index + queue seams are stubbed (see conftest.py).
"""

from dataclasses import replace
from typing import Any

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

from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.repository import Stored


def _other_ulids(corpus: Corpus) -> set[str]:
    return set(corpus.articles.list_ulids()) - {DRAFT_ULID, PUBLISHED_ULID}


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- Duplizieren -------------------------------------------------------------------


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


# --- fail-closed: no exposure, no publish affordance (learning G.34) ---------------

_UNRESOLVABLE = "01KX7YT9E3VX0CP3A5Q49RZMWQ"


def _article_whose_bestand_chain_is_broken(
    corpus: Corpus, lifecycle: Lifecycle = Lifecycle.DRAFT
) -> str:
    """Save an article filed under a collection whose PARENT does not exist, so ``resolve_chain``
    raises ``BrokenCollectionTree`` and ``preview()`` can compute no exposure at all. The collection
    itself IS in the store, so the Bestand select still offers it and the edit form renders."""
    corpus.add_collection(make_collection("WAISE", "Waise", "FEHLT", Audience(AudienceTier.PUBLIC)))
    corpus.add_article(
        make_article(
            _UNRESOLVABLE,
            collection_id="WAISE",
            lifecycle=lifecycle,
            title="Ohne Bestandskette",
        )
    )
    return _UNRESOLVABLE


def test_an_unresolvable_bestand_chain_blocks_publishing(corpus: Corpus) -> None:
    # With no resolvable audience chain there is no exposure, so Veröffentlicht is not on offer (G.34).
    ulid = _article_whose_bestand_chain_is_broken(corpus)
    body = client_as(Archivist()).get(f"/artikel/{ulid}/bearbeiten").content.decode()
    assert 'name="lifecycle"' in body  # the Status select is there...
    assert '<option value="published"' not in body  # ...without Veröffentlicht
    # a resolvable record is unaffected — the gate is the missing FACT, not the screen
    ok = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}/bearbeiten").content.decode()
    assert '<option value="published"' in ok


def test_a_published_record_with_an_unresolvable_chain_keeps_its_status_on_offer(
    corpus: Corpus,
) -> None:
    # Without Veröffentlicht in the select, the next Speichern would withdraw the record silently.
    ulid = _article_whose_bestand_chain_is_broken(corpus, Lifecycle.PUBLISHED)
    body = client_as(Archivist()).get(f"/artikel/{ulid}/bearbeiten").content.decode()
    assert '<option value="published" selected>' in body


def _publish_post(corpus: Corpus, ulid: str, **overrides: str) -> dict[str, str]:
    """A form POST setting Status to Veröffentlicht, at the article's current version so CAS
    passes."""
    version = corpus.articles.load(ulid).version
    return {
        "title": "Ohne Bestandskette",
        "collection_id": "WAISE",
        "media_type": "Foto(s)",
        "expected_version": str(version),
        "lifecycle": "published",
        **overrides,
    }


def test_publishing_an_unresolvable_chain_is_refused_by_the_SERVER(corpus: Corpus) -> None:
    # The render half above hides the affordance; this is the half that actually holds. The state is
    # reachable with ordinary UI actions: re-parent a Bestand under a missing parent (the article's
    # own version is untouched, so CAS passes), then POST Veröffentlicht.
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
    assert ">Frisch getippt</textarea>" in body  # the archivist's input is preserved


def test_withdrawing_an_unresolvable_chain_stays_allowed(corpus: Corpus) -> None:
    # The refusal is about PUBLISHING. Taking a record back off the shelf needs no exposure fact, and
    # refusing it would strand a published record with a broken chain published forever.
    ulid = _article_whose_bestand_chain_is_broken(corpus, Lifecycle.PUBLISHED)
    response = client_as(Archivist()).post(
        f"/artikel/{ulid}/bearbeiten",
        _publish_post(corpus, ulid, lifecycle="draft"),
    )
    assert response.status_code == 302
    assert corpus.articles.load(ulid).article.lifecycle is Lifecycle.DRAFT


@pytest.mark.parametrize("lifecycle", [Lifecycle.DRAFT, Lifecycle.PUBLISHED])
def test_an_unchanged_status_with_an_unresolvable_chain_stays_a_plain_save(
    corpus: Corpus, lifecycle: Lifecycle
) -> None:
    # Only draft to published is gated.
    ulid = _article_whose_bestand_chain_is_broken(corpus, lifecycle)
    response = client_as(Archivist()).post(
        f"/artikel/{ulid}/bearbeiten",
        _publish_post(corpus, ulid, title="Nur gespeichert", lifecycle=lifecycle.value),
    )
    assert response.status_code == 302
    stored = corpus.articles.load(ulid).article
    assert (stored.title, stored.lifecycle) == ("Nur gespeichert", lifecycle)


# --- Veröffentlichen from the article page (a3 round 7) ------------------------------


def _veroeffentlichen(
    corpus: Corpus, ulid: str, viewer: Viewer | None = None, version: int | None = None
) -> Any:
    if version is None:
        version = corpus.articles.load(ulid).version
    return client_as(viewer or Archivist("anna")).post(
        f"/artikel/{ulid}/veroeffentlichen", {"expected_version": str(version)}
    )


def test_veroeffentlichen_publishes_the_draft_and_returns_to_its_page(corpus: Corpus) -> None:
    before = corpus.articles.load(DRAFT_ULID)
    response = _veroeffentlichen(corpus, DRAFT_ULID)
    assert response.status_code == 302
    assert response["Location"] == f"/artikel/{DRAFT_ULID}"
    after = corpus.articles.load(DRAFT_ULID)
    assert after.article == replace(before.article, lifecycle=Lifecycle.PUBLISHED)
    assert after.change is not None and after.change.by == "anna"


def _assert_refused(corpus: Corpus, ulid: str, version: int | None = None) -> None:
    """A refused publish writes nothing and sends the archivist back to the page as it stands."""
    before = corpus.articles.load(ulid)
    response = _veroeffentlichen(corpus, ulid, version=version)
    assert response.status_code == 302
    assert response["Location"] == f"/artikel/{ulid}"
    assert corpus.articles.load(ulid) == before


def test_veroeffentlichen_on_a_stale_page_writes_nothing(corpus: Corpus) -> None:
    _assert_refused(corpus, DRAFT_ULID, version=corpus.articles.load(DRAFT_ULID).version - 1)


def test_veroeffentlichen_refuses_a_record_changed_while_it_publishes(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The page's version matches the first load; a concurrent save lands before the write service
    # loads again. What would be published is no longer what the archivist confirmed.
    from bundesarchiv.persistence.repository import ArticleRepository

    real_load = ArticleRepository.load
    loads = 0

    def load_with_a_concurrent_save(self: ArticleRepository, ulid: str) -> Stored:
        nonlocal loads
        loads += 1
        if loads == 2:
            stored = real_load(self, ulid)
            audience = Audience(AudienceTier.GROUPS, ("vorstand",))
            self.save(replace(stored.article, audience=audience), stored.version, changed_by="bert")
        return real_load(self, ulid)

    version = corpus.articles.load(DRAFT_ULID).version
    monkeypatch.setattr(ArticleRepository, "load", load_with_a_concurrent_save)
    response = _veroeffentlichen(corpus, DRAFT_ULID, version=version)
    monkeypatch.undo()
    after = corpus.articles.load(DRAFT_ULID)
    assert response.status_code == 302
    assert after.article.lifecycle is Lifecycle.DRAFT
    assert after.change is not None and after.change.by == "bert"  # only the concurrent save


def test_veroeffentlichen_refuses_an_unresolvable_bestand_chain(corpus: Corpus) -> None:
    _assert_refused(corpus, _article_whose_bestand_chain_is_broken(corpus))


def test_veroeffentlichen_leaves_a_published_record_alone(corpus: Corpus) -> None:
    _assert_refused(corpus, PUBLISHED_ULID)


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_veroeffentlichen_denied_publishes_nothing(corpus: Corpus, viewer: Viewer) -> None:
    before = corpus.articles.load(DRAFT_ULID)
    assert_denied(_veroeffentlichen(corpus, DRAFT_ULID, viewer=viewer))
    assert corpus.articles.load(DRAFT_ULID) == before


def test_veroeffentlichen_get_is_404(corpus: Corpus) -> None:
    before = corpus.articles.load(DRAFT_ULID)
    assert_denied(client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}/veroeffentlichen"))
    assert corpus.articles.load(DRAFT_ULID) == before


def test_veroeffentlichen_with_index_lag_says_so(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR 0014: publishing is a visibility change; a lagging index must be said, not swallowed.
    from bundesarchiv.app import articles

    monkeypatch.setattr(
        articles, "index_article", lambda *a, **k: (_ for _ in ()).throw(Exception())
    )
    response = _veroeffentlichen(corpus, DRAFT_ULID)
    assert response.status_code == 200
    assert "Die Suche zeigt die Änderung in Kürze." in response.content.decode()
    assert corpus.articles.load(DRAFT_ULID).article.lifecycle is Lifecycle.PUBLISHED


def test_the_confirmation_says_who_will_see_the_record(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}").content.decode()
    assert 'popovertarget="veroeffentlichen"' in body
    assert f'action="/artikel/{DRAFT_ULID}/veroeffentlichen"' in body
    version = corpus.articles.load(DRAFT_ULID).version
    assert f'name="expected_version" value="{version}"' in body
    assert "Nach dem Veröffentlichen ist dieser Artikel öffentlich." in body  # PUB is public
    # the statement follows the record's own audience, not a fixed wording
    articles = corpus.articles
    stored = articles.load(DRAFT_ULID)
    members = replace(stored.article, audience=Audience(AudienceTier.MEMBERS))
    articles.save(members, stored.version, changed_by="tester")
    body = client_as(Archivist()).get(f"/artikel/{DRAFT_ULID}").content.decode()
    assert "Nach dem Veröffentlichen sehen alle Mitglieder diesen Artikel." in body


def test_a_published_record_has_no_confirmation(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/artikel/{PUBLISHED_ULID}").content.decode()
    assert "veroeffentlichen" not in body
    assert "Nach dem Veröffentlichen" not in body


# --- malformed / absent ulid across every new route --------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/artikel/not-a-ulid/kopieren",
        "/artikel/not-a-ulid/loeschen",
        "/artikel/01BX5ZZKBKACTAV9WEVGEMMVRZ/loeschen",  # well-formed but absent
        "/artikel/not-a-ulid/veroeffentlichen",
        "/artikel/01BX5ZZKBKACTAV9WEVGEMMVRZ/veroeffentlichen",
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
