"""The full edit form ``/artikel/<ulid>/bearbeiten`` (Part 4.7 Slice B, spec §2/§3/§6.1/§8).

GET seeds the form from the stored Article; POST parses + saves under CAS (ADR 0013) and 302s to the
read view. Both methods are archivist-gated to a 404 for Member / Public / anonymous, and for a
malformed or absent ulid (existence-hiding). Validation re-renders
state F (verbatim error, preserved values). A raced concurrent save re-renders state G — the
"Inzwischen geändert" panel — with the loser's input preserved and a refreshed ``expected_version``.
The whole write path is REAL (repository + README + CAS); only the index + queue seams are stubbed
(see ``conftest.py``).
"""

from pathlib import Path

import pytest
from django.core import signing
from django.http import HttpRequest
from django.test import Client, override_settings
from tests.app.web._asserts import assert_denied

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


def test_edit_header_omits_hollow_sig_slot_when_no_ref_code(corpus: _Corpus) -> None:
    # fix-wave (owner finding): the edit header shows the Signatur mark ONLY when a code exists —
    # absence is carried by the Signatur INPUT on the same screen, not a hollow "ohne Signatur" slot
    # (signals-once). The hollow slot stays in the ledger + read view, not here.
    no_sig = "01KX7YT9E3VX0CP3A5Q49RZMWK"
    ArticleRepository(corpus.store).save(
        Article(ulid=no_sig, title="Unbetitelt", collection_id="PUB", lifecycle=Lifecycle.DRAFT),
        0,
    )
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{no_sig}/bearbeiten").content.decode()
    # the sr-only "Ohne Signatur" text (rendered by the hollow-slot signatur_tab) must NOT appear —
    # the edit header omits the slot entirely; the Signatur input carries absence instead
    assert "Ohne Signatur" not in body
    assert "c-sig--leer" not in body  # the hollow-slot class is absent
    # the Signatur input is present and empty
    assert 'name="ref_code" value=""' in body


# --- GET/POST: archivist gate (both methods, all tiers) ---------------------------


# (The GET deny is the leak matrix's cell for this route — only the POST twin adds the
# nothing-was-changed side-effect assert the matrix can't see.)
@pytest.mark.parametrize("viewer", [Public(), Member(groups=("vorstand",))])
def test_edit_post_is_404_for_non_archivist(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(
            f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gekapert")
        )
    assert_denied(response)
    # the non-archivist POST changed nothing
    assert ArticleRepository(corpus.store).load(_ULID).article.title == "Wanderfahrt 1962"


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_edit_malformed_or_absent_ulid_is_404(corpus: _Corpus, ulid: str) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{ulid}/bearbeiten")
    assert_denied(response)


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


# --- POST: stale save against a hard-deleted article -------------------------------


def test_stale_save_against_deleted_article_is_404(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The archivist opened the form at version 1 (the gate passes and loads the article); an
    # archivist hard-deletes it before THIS POST's save runs — the exact race window between the
    # view's initial gate/load and `save_catalog_form`'s own re-load on Conflict. `_current_version`
    # then reads 0 for the missing article, so `save_article` raises Conflict (0 != 1); the Conflict
    # handler's re-load hits NotFound. That must collapse to the SAME 404 as an absent article, never
    # an uncaught 500.
    from bundesarchiv.app.web import catalog_views

    real_gated = catalog_views._load_gated

    def _delete_then_gate(request: HttpRequest, ulid: str) -> tuple[object, object] | None:
        gated = real_gated(request, ulid)
        ArticleRepository(corpus.store).hard_delete(_ULID)
        return gated

    monkeypatch.setattr(catalog_views, "_load_gated", _delete_then_gate)
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus))
    assert_denied(response)


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


def test_custom_entfernen_index_survives_an_earlier_row_blanked_in_browser(
    corpus: _Corpus,
) -> None:
    # A blanked-out earlier row shifts positions once `_post_to_form_values` drops it — but
    # `custom_entfernen` names a position in the RAW POST lists (what the Entfernen button actually
    # submitted), not in that filtered result. Rows A/B/C, A blanked, Entfernen on B (raw index 1)
    # must drop B and keep C — not drop C because the filtered list only has two entries left.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                **_valid_post(corpus),
                "custom_key": ["", "Bkey", "Ckey", ""],
                "custom_value": ["", "Bval", "Cval", ""],
                "custom_entfernen": "1",
            },
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert 'value="Bkey"' not in body  # the removed row is gone
    assert 'value="Bval"' not in body
    assert 'value="Ckey"' in body  # the surviving row is preserved
    assert 'value="Cval"' in body
    # nothing was saved (removal is a re-render, not a save)
    assert ArticleRepository(corpus.store).load(_ULID).version == corpus.version


# --- POST re-render fidelity: lifecycle + custom-row accumulation ------------------


def test_published_article_invalid_post_re_render_omits_entwurf_badge(corpus: _Corpus) -> None:
    # fix-wave: `_post_to_form_values` hardcoded is_draft=True, so a PUBLISHED article's
    # validation-error re-render wrongly showed the ENTWURF badge.
    published = "01KX7YT9E3VX0CP3A5Q49RZMWP"
    ArticleRepository(corpus.store).save(
        Article(
            ulid=published,
            title="Veröffentlicht",
            collection_id="PUB",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="F 99/1",
        ),
        0,
    )
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{published}/bearbeiten",
            {
                **_valid_post(corpus, expected_version="0"),
                "title": "",  # invalid -> validation error re-render (state F)
            },
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body  # confirms we hit the error re-render
    assert 'class="c-badge c-badge--entwurf"' not in body  # no ENTWURF badge for PUBLISHED


def test_repeated_invalid_post_does_not_accumulate_blank_custom_rows(corpus: _Corpus) -> None:
    # fix-wave: the POSTed custom rows already include the trailing blank add-row; unconditionally
    # appending another produced +1 blank row per error re-render.
    with override_settings(**_settings(corpus)):
        first = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                **_valid_post(corpus, title=""),
                "custom_key": ["Fotograf", ""],
                "custom_value": ["Meyer", ""],
            },
        )
        assert first.status_code == 200
        first_body = first.content.decode()
        first_blank_pairs = first_body.count('name="custom_key" value=""')
        assert first_blank_pairs == 1  # exactly one trailing blank row, not two

        # re-send the same hand-built payload (the first assertion pinned it equivalent to the
        # re-rendered form) — the blank-row count must not grow
        second = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                **_valid_post(corpus, title=""),
                "custom_key": ["Fotograf", ""],
                "custom_value": ["Meyer", ""],
            },
        )
    assert second.status_code == 200
    second_body = second.content.decode()
    second_blank_pairs = second_body.count('name="custom_key" value=""')
    assert second_blank_pairs == 1
