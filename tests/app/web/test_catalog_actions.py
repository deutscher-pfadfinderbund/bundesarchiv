"""Read-view actions + lifecycle (Part 4.7 Slice C, spec §6.2/§7/§8).

Covers the four new routes and the read-view action row:

- ``/articles/<ulid>/copy`` POST — copy to a fresh draft, 302 to the copy's edit form.
- ``/articles/<ulid>/delete`` GET (confirm) + POST (execute) — into the Papierkorb, 302 to the
  workbench; ``/delete-permanently`` the same for a marked record, deleting it for good;
  ``/restore`` POST takes it out again (ADR 0022).
- the fail-closed publish affordance: no exposure, no Veröffentlichen.
- ``/articles/<ulid>/publish`` POST — publish a draft from the article page (a3 round 7):
  CAS on the page's version, the same fail-closed gate as the edit form's Status.
- the archivist action row on the detail stub (absent for non-archivists).

SECURITY is the load-bearing part (mutation-tested next review): every route archivist-gated for
BOTH methods → 404 for Member/Public/anon, and the deny tests assert the SIDE EFFECT
did not happen (nothing created / article still exists / lifecycle unchanged / no widget content).
The write path is REAL; only the index + queue seams are stubbed (see conftest.py).
"""

from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    DRAFT_ULID,
    PUBLISHED_ULID,
    Corpus,
    client_as,
    make_article,
    make_collection,
    page_forms,
)

from bundesarchiv.domain.models import Audience, AudienceTier, Change, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.repository import Stored


def _mark(corpus: Corpus, ulid: str) -> None:
    stored = corpus.articles.load(ulid)
    corpus.articles.mark_deleted(stored.article, stored.version, changed_by="bert")


def _mark_of(corpus: Corpus, ulid: str) -> Change | None:
    return corpus.articles.load(ulid).article.deleted


def _other_ulids(corpus: Corpus) -> set[str]:
    return set(corpus.articles.list_ulids()) - {DRAFT_ULID, PUBLISHED_ULID}


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- Duplizieren -------------------------------------------------------------------


def test_kopieren_creates_draft_copy_and_redirects_to_its_edit_form(corpus: Corpus) -> None:
    response = client_as(Archivist()).post(f"/articles/{PUBLISHED_ULID}/copy")
    assert response.status_code == 302
    new = _other_ulids(corpus)
    assert len(new) == 1
    new_ulid = new.pop()
    # 302 to the copy's edit form with the Signatur autofocus hint (spec §5)
    assert response["Location"] == f"/articles/{new_ulid}/edit?fokus=signatur"
    copy = corpus.articles.load(new_ulid).article
    assert copy.ref_code is None  # Signatur cleared (spec §7)
    assert copy.lifecycle is Lifecycle.DRAFT
    assert copy.media == ()
    assert copy.title == "Sommerfahrt 1962"  # metadata carried over


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_kopieren_denied_creates_nothing(corpus: Corpus, viewer: Viewer) -> None:
    response = client_as(viewer).post(f"/articles/{PUBLISHED_ULID}/copy")
    assert_denied(response)
    assert _other_ulids(corpus) == set()  # nothing created


def test_kopieren_get_is_404(corpus: Corpus) -> None:
    # a copy is a mutation — GET must not create.
    response = client_as(Archivist()).get(f"/articles/{PUBLISHED_ULID}/copy")
    assert_denied(response)
    assert _other_ulids(corpus) == set()


# --- Löschen -----------------------------------------------------------------------


def _delete_forms(body: str, ulid: str) -> list[tuple[str, dict[str, str]]]:
    return [f for f in page_forms(body) if f[0].startswith(f"/articles/{ulid}/delete")]


def _submit_delete_form(client: Any, body: str, ulid: str) -> Any:
    """Post the page's one delete confirm exactly as the page hands it out."""
    [(action, fields)] = _delete_forms(body, ulid)
    return client.post(action, fields)


def test_loeschen_confirm_page_names_the_record(corpus: Corpus) -> None:
    response = client_as(Archivist()).get(f"/articles/{PUBLISHED_ULID}/delete")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Sommerfahrt 1962" in body
    assert "F12" in body


def test_the_confirm_page_deletes_and_returns_to_the_workbench(corpus: Corpus) -> None:
    client = client_as(Archivist())
    body = client.get(f"/articles/{PUBLISHED_ULID}/delete").content.decode()
    response = _submit_delete_form(client, body, PUBLISHED_ULID)
    assert response.status_code == 302
    assert response["Location"] == "/articles"
    assert _mark_of(corpus, PUBLISHED_ULID) is not None


def test_a_confirm_older_than_the_record_deletes_nothing_and_asks_again(corpus: Corpus) -> None:
    """The confirm names what goes; a record saved since then may hold more, so the delete waits for
    a confirm of the record as it now stands."""
    client = client_as(Archivist())
    body = client.get(f"/articles/{PUBLISHED_ULID}/delete").content.decode()
    stored = corpus.articles.load(PUBLISHED_ULID)
    corpus.articles.save(
        replace(stored.article, title="Inzwischen"), stored.version, changed_by="x"
    )
    refused = _submit_delete_form(client, body, PUBLISHED_ULID)
    assert refused.status_code == 200
    assert corpus.articles.load(PUBLISHED_ULID).article.title == "Inzwischen"
    assert _mark_of(corpus, PUBLISHED_ULID) is None
    assert _submit_delete_form(client, refused.content.decode(), PUBLISHED_ULID).status_code == 302
    assert _mark_of(corpus, PUBLISHED_ULID) is not None


def test_the_article_page_deletes_in_place_and_asks_again_when_stale(corpus: Corpus) -> None:
    """The article page's own confirm deletes; one older than the record comes back asking again,
    with htmx too (it answers in place, then navigates on success)."""
    client = client_as(Archivist())
    body = client.get(f"/articles/{PUBLISHED_ULID}").content.decode()
    stored = corpus.articles.load(PUBLISHED_ULID)
    corpus.articles.save(
        replace(stored.article, title="Inzwischen"), stored.version, changed_by="x"
    )
    [(action, fields)] = _delete_forms(body, PUBLISHED_ULID)
    refused = client.post(action, fields, headers={"HX-Request": "true"})
    assert refused.status_code == 200
    assert corpus.articles.load(PUBLISHED_ULID).article.title == "Inzwischen"
    [(action, fields)] = _delete_forms(refused.content.decode(), PUBLISHED_ULID)
    done = client.post(action, fields, headers={"HX-Request": "true"})
    assert done["HX-Redirect"] == "/articles"
    assert _mark_of(corpus, PUBLISHED_ULID) is not None


def test_a_save_landing_while_the_delete_runs_survives(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0013: the delete checks the confirm's version under the save lock, so a save that lands
    after the view's own load is never deleted."""
    from bundesarchiv.persistence.repository import ArticleRepository

    client = client_as(Archivist())
    body = client.get(f"/articles/{PUBLISHED_ULID}").content.decode()
    real_load = ArticleRepository.load

    def load_then_a_concurrent_save(self: ArticleRepository, ulid: str) -> Stored:
        monkeypatch.setattr(ArticleRepository, "load", real_load)
        loaded = real_load(self, ulid)
        self.save(replace(loaded.article, title="Inzwischen"), loaded.version, changed_by="bert")
        return loaded

    monkeypatch.setattr(ArticleRepository, "load", load_then_a_concurrent_save)
    refused = _submit_delete_form(client, body, PUBLISHED_ULID)
    assert refused.status_code == 200
    survivor = corpus.articles.load(PUBLISHED_ULID).article
    assert (survivor.title, survivor.deleted) == ("Inzwischen", None)


def test_a_drafts_edit_form_deletes_through_its_one_confirm(corpus: Corpus) -> None:
    client = client_as(Archivist())
    body = client.get(f"/articles/{DRAFT_ULID}/edit").content.decode()
    [(action, fields)] = _delete_forms(body, DRAFT_ULID)
    assert fields["expected_version"] == str(corpus.articles.load(DRAFT_ULID).version)
    assert client.post(action, fields).status_code == 302
    assert _mark_of(corpus, DRAFT_ULID) is not None


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
@pytest.mark.parametrize("method", ["get", "post"])
def test_loeschen_denied_leaves_article(corpus: Corpus, viewer: Viewer, method: str) -> None:
    response = getattr(client_as(viewer), method)(f"/articles/{PUBLISHED_ULID}/delete")
    assert_denied(response)
    assert _mark_of(corpus, PUBLISHED_ULID) is None  # the deny prevented the delete


# --- Endgültig löschen -------------------------------------------------------------


def _for_good_forms(body: str, ulid: str) -> list[tuple[str, dict[str, str]]]:
    return [f for f in page_forms(body) if f[0].startswith(f"/articles/{ulid}/delete-permanently")]


def test_endgueltig_loeschen_deletes_a_marked_record_for_good(corpus: Corpus) -> None:
    _mark(corpus, PUBLISHED_ULID)
    client = client_as(Archivist())
    body = client.get(f"/articles/{PUBLISHED_ULID}/delete-permanently").content.decode()
    [(action, fields)] = _for_good_forms(body, PUBLISHED_ULID)
    response = client.post(action, fields)
    assert (response.status_code, response["Location"]) == (302, "/trash")
    with pytest.raises(NotFound):
        corpus.articles.load(PUBLISHED_ULID)


def test_an_endgueltig_confirm_older_than_the_record_deletes_nothing_and_asks_again(
    corpus: Corpus,
) -> None:
    _mark(corpus, PUBLISHED_ULID)
    client = client_as(Archivist())
    body = client.get(f"/articles/{PUBLISHED_ULID}/delete-permanently").content.decode()
    stored = corpus.articles.load(PUBLISHED_ULID)
    corpus.articles.save(
        replace(stored.article, title="Inzwischen"), stored.version, changed_by="x"
    )
    [(action, fields)] = _for_good_forms(body, PUBLISHED_ULID)
    refused = client.post(action, fields)
    assert refused.status_code == 200
    assert corpus.articles.load(PUBLISHED_ULID).article.title == "Inzwischen"
    [(action, fields)] = _for_good_forms(refused.content.decode(), PUBLISHED_ULID)
    assert client.post(action, fields).status_code == 302
    with pytest.raises(NotFound):
        corpus.articles.load(PUBLISHED_ULID)


def test_a_restore_landing_while_endgueltig_runs_survives(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate saw the record in the Papierkorb; a restore landing after that load is never
    deleted for good (ADR 0013, 0022)."""
    from bundesarchiv.persistence.repository import ArticleRepository

    _mark(corpus, PUBLISHED_ULID)
    client = client_as(Archivist())
    body = client.get(f"/articles/{PUBLISHED_ULID}/delete-permanently").content.decode()
    real_load = ArticleRepository.load

    def load_then_a_restore(self: ArticleRepository, ulid: str) -> Stored:
        monkeypatch.setattr(ArticleRepository, "load", real_load)
        loaded = real_load(self, ulid)
        self.save(replace(loaded.article, deleted=None), loaded.version, changed_by="bert")
        return loaded

    monkeypatch.setattr(ArticleRepository, "load", load_then_a_restore)
    [(action, fields)] = _for_good_forms(body, PUBLISHED_ULID)
    assert_denied(client.post(action, fields))  # no longer marked: the re-load refuses
    assert _mark_of(corpus, PUBLISHED_ULID) is None


# --- Wiederherstellen --------------------------------------------------------------


def _restore(client: Any, ulid: str, version: int) -> Any:
    return client.post(f"/articles/{ulid}/restore", {"expected_version": str(version)})


def test_wiederherstellen_takes_the_record_out_of_the_papierkorb(corpus: Corpus) -> None:
    _mark(corpus, PUBLISHED_ULID)
    before = corpus.articles.load(PUBLISHED_ULID)
    response = _restore(client_as(Archivist()), PUBLISHED_ULID, before.version)
    assert (response.status_code, response["Location"]) == (302, f"/articles/{PUBLISHED_ULID}")
    assert corpus.articles.load(PUBLISHED_ULID).article == replace(before.article, deleted=None)


@pytest.mark.parametrize("hx", [False, True], ids=["plain", "htmx"])
def test_loeschen_with_index_lag_says_so(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch, hx: bool
) -> None:
    # ADR 0014: the mark takes the record out of search; a lagging index is said, as on a restore.
    from bundesarchiv.app import after_write

    monkeypatch.setattr(
        after_write, "index_article", lambda *a, **k: (_ for _ in ()).throw(Exception())
    )
    client = client_as(Archivist())
    [(action, fields)] = _delete_forms(
        client.get(f"/articles/{PUBLISHED_ULID}").content.decode(), PUBLISHED_ULID
    )
    done = client.post(action, fields, headers={"HX-Request": "true"} if hx else {})
    landing = done["HX-Redirect"] if hx else done["Location"]
    assert _mark_of(corpus, PUBLISHED_ULID) is not None
    assert urlparse(landing).path == f"/articles/{PUBLISHED_ULID}"
    assert client.get(landing).context["index_lag"]
    assert not client.get(f"/articles/{PUBLISHED_ULID}").context["index_lag"]


def _version(corpus: Corpus, ulid: str) -> int:
    return corpus.articles.load(ulid).version


def test_the_page_of_a_marked_record_offers_restore_and_delete_permanently_only(
    corpus: Corpus,
) -> None:
    """ADR 0022: a marked record cannot be edited, copied, published or deleted again; its page
    offers the two Papierkorb actions, each at the version it shows."""
    _mark(corpus, PUBLISHED_ULID)
    body = client_as(Archivist()).get(f"/articles/{PUBLISHED_ULID}").content.decode()
    main = body[body.index("<main") :]
    version = str(_version(corpus, PUBLISHED_ULID))
    forms = dict(page_forms(main))
    assert set(forms) == {
        f"/articles/{PUBLISHED_ULID}/restore",
        f"/articles/{PUBLISHED_ULID}/delete-permanently",
    }
    assert all(fields["expected_version"] == version for fields in forms.values())
    for refused in ("edit", "copy", "delete", "publish"):
        assert f'/articles/{PUBLISHED_ULID}/{refused}"' not in main


def test_wiederherstellen_on_a_stale_page_restores_nothing(corpus: Corpus) -> None:
    _mark(corpus, PUBLISHED_ULID)
    before = corpus.articles.load(PUBLISHED_ULID)
    assert _restore(client_as(Archivist()), PUBLISHED_ULID, before.version - 1).status_code == 302
    assert corpus.articles.load(PUBLISHED_ULID) == before


def test_a_save_landing_while_the_restore_runs_survives(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bundesarchiv.persistence.repository import ArticleRepository

    _mark(corpus, PUBLISHED_ULID)
    version = corpus.articles.load(PUBLISHED_ULID).version
    real_load = ArticleRepository.load

    def load_then_a_concurrent_save(self: ArticleRepository, ulid: str) -> Stored:
        monkeypatch.setattr(ArticleRepository, "load", real_load)
        loaded = real_load(self, ulid)
        self.save(replace(loaded.article, title="Inzwischen"), loaded.version, changed_by="bert")
        return loaded

    monkeypatch.setattr(ArticleRepository, "load", load_then_a_concurrent_save)
    assert _restore(client_as(Archivist()), PUBLISHED_ULID, version).status_code == 302
    survivor = corpus.articles.load(PUBLISHED_ULID).article
    assert survivor.title == "Inzwischen" and survivor.deleted is not None


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
@pytest.mark.parametrize("route", ["delete-permanently", "restore"])
def test_the_papierkorb_routes_deny_and_change_nothing(
    corpus: Corpus, viewer: Viewer, route: str
) -> None:
    _mark(corpus, PUBLISHED_ULID)
    before = corpus.articles.load(PUBLISHED_ULID)
    client = client_as(viewer)
    path = f"/articles/{PUBLISHED_ULID}/{route}"
    assert_denied(client.get(path))
    assert_denied(client.post(path, {"expected_version": str(before.version)}))
    assert corpus.articles.load(PUBLISHED_ULID) == before


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
    body = client_as(Archivist()).get(f"/articles/{ulid}/edit").content.decode()
    assert 'name="lifecycle"' in body  # the Status select is there...
    assert '<option value="published"' not in body  # ...without Veröffentlicht
    # a resolvable record is unaffected — the gate is the missing FACT, not the screen
    ok = client_as(Archivist()).get(f"/articles/{DRAFT_ULID}/edit").content.decode()
    assert '<option value="published"' in ok


def test_a_published_record_with_an_unresolvable_chain_keeps_its_status_on_offer(
    corpus: Corpus,
) -> None:
    # Without Veröffentlicht in the select, the next Speichern would withdraw the record silently.
    ulid = _article_whose_bestand_chain_is_broken(corpus, Lifecycle.PUBLISHED)
    body = client_as(Archivist()).get(f"/articles/{ulid}/edit").content.decode()
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
        f"/articles/{ulid}/edit", _publish_post(corpus, ulid, title="Frisch getippt")
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
        f"/articles/{ulid}/edit",
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
        f"/articles/{ulid}/edit",
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
        f"/articles/{ulid}/publish", {"expected_version": str(version)}
    )


def test_veroeffentlichen_publishes_the_draft_and_returns_to_its_page(corpus: Corpus) -> None:
    before = corpus.articles.load(DRAFT_ULID)
    response = _veroeffentlichen(corpus, DRAFT_ULID)
    assert response.status_code == 302
    assert response["Location"] == f"/articles/{DRAFT_ULID}"
    after = corpus.articles.load(DRAFT_ULID)
    assert after.article == replace(before.article, lifecycle=Lifecycle.PUBLISHED)
    assert after.change is not None and after.change.by == "anna"


def _assert_refused(corpus: Corpus, ulid: str, version: int | None = None) -> None:
    """A refused publish writes nothing and sends the archivist back to the page as it stands."""
    before = corpus.articles.load(ulid)
    response = _veroeffentlichen(corpus, ulid, version=version)
    assert response.status_code == 302
    assert response["Location"] == f"/articles/{ulid}"
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
    assert_denied(client_as(Archivist()).get(f"/articles/{DRAFT_ULID}/publish"))
    assert corpus.articles.load(DRAFT_ULID) == before


def test_the_confirmation_says_who_will_see_the_record(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/articles/{DRAFT_ULID}").content.decode()
    assert 'popovertarget="veroeffentlichen"' in body
    assert f'action="/articles/{DRAFT_ULID}/publish"' in body
    version = corpus.articles.load(DRAFT_ULID).version
    assert f'name="expected_version" value="{version}"' in body
    assert "Nach dem Veröffentlichen ist dieser Artikel öffentlich." in body  # PUB is public
    # the statement follows the record's own audience, not a fixed wording
    articles = corpus.articles
    stored = articles.load(DRAFT_ULID)
    members = replace(stored.article, audience=Audience(AudienceTier.MEMBERS))
    articles.save(members, stored.version, changed_by="tester")
    body = client_as(Archivist()).get(f"/articles/{DRAFT_ULID}").content.decode()
    assert "Nach dem Veröffentlichen sehen alle Mitglieder diesen Artikel." in body


def test_a_published_record_has_no_confirmation(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/articles/{PUBLISHED_ULID}").content.decode()
    assert "veroeffentlichen" not in body
    assert "Nach dem Veröffentlichen" not in body


# --- malformed / absent ulid across every new route --------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/articles/not-a-ulid/copy",
        "/articles/not-a-ulid/delete",
        "/articles/01BX5ZZKBKACTAV9WEVGEMMVRZ/delete",  # well-formed but absent
        "/articles/not-a-ulid/publish",
        "/articles/01BX5ZZKBKACTAV9WEVGEMMVRZ/publish",
    ],
)
def test_malformed_or_absent_ulid_is_404(corpus: Corpus, path: str) -> None:
    response = client_as(Archivist()).post(path)
    assert_denied(response)


# --- read-view action row ----------------------------------------------------------


def test_detail_action_row_present_for_archivist(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/articles/{PUBLISHED_ULID}").content.decode()
    assert 'class="actions"' in body
    assert f"/articles/{PUBLISHED_ULID}/edit" in body
    assert f"/articles/{PUBLISHED_ULID}/copy" in body
    assert f"/articles/{PUBLISHED_ULID}/delete" in body
    # published article → the unpublish action, not Veröffentlichen
    assert "Als Entwurf zurückziehen" in body


def test_detail_action_row_absent_for_non_archivist(corpus: Corpus) -> None:
    # PUB is public, so Public can VIEW the published article — but the action row must be ABSENT.
    body = client_as(Public()).get(f"/articles/{PUBLISHED_ULID}").content.decode()
    assert 'class="actions"' not in body
    assert "/copy" not in body
    assert "/delete" not in body


# --- template-comment hygiene (a multi-line {# #} leaks — same rule as the workbench) ----------


def test_no_leaked_template_comment(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(f"/articles/{DRAFT_ULID}").content.decode()
    assert "{#" not in body  # a multi-line {# #} would leak into the rendered page


# --- CSRF enforcement (fix wave: prod/dev now run CsrfViewMiddleware) ---------------


def test_destructive_post_without_csrf_token_is_403(corpus: Corpus) -> None:
    # A cross-site destructive POST with no CSRF token must be rejected (CsrfViewMiddleware active).
    response = client_as(Archivist(), enforce_csrf=True).post(f"/articles/{PUBLISHED_ULID}/delete")
    assert response.status_code == 403
    # the article is untouched — the forged POST was rejected before the delete ran
    assert _mark_of(corpus, PUBLISHED_ULID) is None


def test_destructive_post_with_csrf_token_works(corpus: Corpus) -> None:
    # The legitimate flow — GET the confirm page (sets the csrf cookie + token), then POST with it.
    client = client_as(Archivist(), enforce_csrf=True)
    body = client.get(f"/articles/{PUBLISHED_ULID}/delete").content.decode()  # seeds the cookie
    response = _submit_delete_form(client, body, PUBLISHED_ULID)
    assert response.status_code == 302  # accepted → in the Papierkorb → redirect
    assert _mark_of(corpus, PUBLISHED_ULID) is not None
