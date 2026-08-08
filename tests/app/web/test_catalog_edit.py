"""The full edit form ``/artikel/<ulid>/bearbeiten`` (Part 4.7 Slice B, spec §2/§3/§6.1/§8).

GET seeds the form from the stored Article; POST parses + saves under CAS (ADR 0013) and 302s to the
read view. Both methods are archivist-gated to a 404 for Member / Public / anonymous, and for a
malformed or absent ulid (existence-hiding). Validation re-renders
state F (verbatim error, preserved values). A raced concurrent save re-renders state G — the
"Inzwischen geändert" panel — with the loser's input preserved and a refreshed ``expected_version``.
The whole write path is REAL (repository + README + CAS); only the index + queue seams are stubbed
(see ``conftest.py``).
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.core import signing
from django.http import HttpRequest
from django.test import Client, override_settings
from tests.app.web._asserts import assert_denied

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.edtf import EdtfDate
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
                ref_code="F12/3",
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
        "ref_code": "F12/3",
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
    assert 'value="F12/3"' in body
    # the group drawers are present (spec §3)
    for legend in ("Kerndaten", "Einordnung", "Herkunft", "Beschreibung", "Zugriff"):
        assert legend in body
    assert "Weitere Angaben" in body  # Gruppe 7
    # the hidden expected_version rides the form
    assert f'name="expected_version" value="{corpus.version}"' in body
    # the ENTWURF badge (draft) sits in the header
    assert "Entwurf" in body
    # the Signatur mark reflects ref_code
    assert "F12/3" in body


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
            ref_code="F99/1",
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
    assert 'class="badge entwurf"' not in body  # no ENTWURF badge for PUBLISHED


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


# --- folded sections: a fold may hide neither a message nor the focus -------------
#
# Owner ruling 4 folds the rare sections WITH their values in the summary — folding may never hide
# data. The form wave left two ways for it to hide something else: a validation error rendered inside
# a folded section is invisible (Sichtbarkeit=Gruppe(n) with an empty Gruppen field; errors.custom in
# the bag), and `autofocus` on a field inside a fold focuses nothing at all, because a closed
# <details> has no focusable contents (_FOCUSABLE_FIELDS holds three such fields). Both are now
# decided server-side from the same context that renders the message — catalog_views._open_sections.


@dataclass
class _Fold:
    """One rendered ``<details>`` inside the record card: its summary label, whether it renders open,
    and the names of the form fields it CONTAINS (possibly none — a fold may hold only a message)."""

    label: str = ""
    is_open: bool = False
    fields: set[str] = field(default_factory=set)


#: HTML elements with no end tag. The scanner tracks nesting depth to know what is inside the card,
#: and a void element that never closes would leave the depth counter permanently one too deep.
_VOID = frozenset({"input", "img", "br", "hr", "meta", "link", "source", "col", "area"})


class _FoldScanner(HTMLParser):
    """Collect every ``<details>`` INSIDE THE RECORD CARD with its ``open`` state, summary label and
    contained field names, plus the name of the ONE field carrying ``autofocus``. A real parser rather
    than a regex, because "contained" is a nesting question.

    Scoped to ``.karte`` STRUCTURALLY. The record row's "Mehr …" overflow is a ``<details>`` too, and
    it used to be excluded by the accident of holding no input — which is the same accident that hid
    field-less CARD folds from the guard below. Hidden inputs are still skipped: they are plumbing
    (CSRF, expected_version, the media hashes), not fields the archivist fills."""

    def __init__(self) -> None:
        super().__init__()
        self.folds: list[_Fold] = []
        self.autofocused = ""
        self._stack: list[_Fold] = []
        self._in_summary = False
        self._depth = 0
        self._karte_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag not in _VOID:
            self._depth += 1
            if self._karte_depth is None and "karte" in (values.get("class") or "").split():
                self._karte_depth = self._depth
        in_karte = self._karte_depth is not None
        if tag == "details" and in_karte:
            fold = _Fold(is_open="open" in values)
            self.folds.append(fold)
            self._stack.append(fold)
        elif tag == "summary" and self._stack:
            self._in_summary = True
        elif tag in ("input", "select", "textarea"):
            name = values.get("name")
            if not name or values.get("type") == "hidden":
                return
            if "autofocus" in values:
                self.autofocused = name
            for fold in self._stack:
                fold.fields.add(name)

    def handle_endtag(self, tag: str) -> None:
        if tag == "details" and self._stack:
            self._stack.pop()
        elif tag == "summary":
            self._in_summary = False
        if tag not in _VOID:
            if self._karte_depth is not None and self._depth == self._karte_depth:
                self._karte_depth = None
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_summary and self._stack and not self._stack[-1].label:
            self._stack[-1].label = data.strip()


def _scan(body: str) -> _FoldScanner:
    scanner = _FoldScanner()
    scanner.feed(body)
    return scanner


def _folds(body: str) -> list[_Fold]:
    """Every ``<details>`` the record card renders, in POSITION order — field-bearing or not.

    Keyed by position, never by label: a summary label is not unique (nothing stops two sections
    sharing one, and the label is free German copy), so a dict keyed by it silently collapses folds
    and the count assertion below then passes over a SHRUNKEN walk — exactly the defect class this
    wave just fixed in the C8 walker (learning G.37). Field-less folds are included for the same
    reason: filtering on ``fold.fields`` dropped precisely the shape the guard exists for — a fold
    whose contents are a MESSAGE (``errors.custom``) rather than an input."""
    return _scan(body).folds


def _fold(body: str, label: str) -> _Fold:
    """The one card fold whose summary starts with ``label`` (folds are position-keyed; callers name
    the section they mean). Fails loudly on zero or several matches rather than picking one."""
    matches = [f for f in _folds(body) if f.label.startswith(label)]
    assert len(matches) == 1, (
        f"„{label}“ matched {len(matches)} folds: {[f.label for f in _folds(body)]}"
    )
    return matches[0]


def test_folded_sections_own_every_field_they_hold(corpus: _Corpus) -> None:
    # The drift guard for the mechanism above: the field registry is the ONE declaration of which
    # fields live behind which fold, so a field moved into a fold without a `section` would silently
    # lose the open-on-error/open-on-focus behaviour. Walk the real render instead of trusting the map.
    #
    # A field maps to AT MOST ONE section BY CONSTRUCTION now — the registry gives each field one
    # `section` string, where the old shape was three frozensets that could overlap — so the three
    # lines that used to rule out that impossibility went with it.
    from bundesarchiv.app.web.catalog_views import _SECTION_FIELDS

    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten").content.decode()
    folds = _folds(body)
    assert len(folds) == 3, (
        f"the scanner found {[f.label for f in folds]} — the guard proves nothing"
    )
    for fold in folds:
        owners = [name for name, fields in _SECTION_FIELDS.items() if fold.fields & fields]
        assert owners, f"„{fold.label}“ ({sorted(fold.fields)}) belongs to no declared section"
        unowned = fold.fields - _SECTION_FIELDS[owners[0]]
        assert not unowned, f"„{fold.label}“ holds {sorted(unowned)}, absent from the registry"


def test_error_inside_a_folded_section_renders_it_open(corpus: _Corpus) -> None:
    # Sichtbarkeit=Gruppe(n) with an empty Gruppen field: the message and the errored input both live
    # in the folded Zugriff section. Folded, the archivist saw a form that simply refused to save.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, sichtbarkeit="groups", gruppen="")
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Bitte mindestens eine Gruppe angeben." in body
    assert _fold(body, "Zugriff").is_open, "the errored Zugriff section rendered folded"
    assert not _fold(body, "Herkunft").is_open  # the clean folds stay folded (ruling 4)


def test_custom_bag_error_renders_the_bag_open(corpus: _Corpus) -> None:
    # errors.custom is the same class: it renders as a <p class="error"> inside #custom-bag.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {**_valid_post(corpus), "custom_key": ["title"], "custom_value": ["gekapert"]},
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Bezeichnung ist reserviert." in body
    assert _fold(body, "Weitere Angaben").is_open, "the errored custom bag rendered folded"


def test_autofocus_target_inside_a_folded_section_renders_it_open(corpus: _Corpus) -> None:
    # _FOCUSABLE_FIELDS scans for the first EMPTY field, and three of them (Autor, Ort, Standort) sit
    # behind the Herkunft fold — so on a record whose earlier fields are all filled the autofocus
    # landed on an input inside a closed <details>, focusing nothing at all.
    filled = "01KX7YT9E3VX0CP3A5Q49RZMWQ"
    ArticleRepository(corpus.store).save(
        Article(
            ulid=filled,
            title="Vollständig",
            collection_id="PUB",
            lifecycle=Lifecycle.DRAFT,
            ref_code="F1",
            media_type="Fotografie",
            document_type="Positiv",
            tags=("sommer",),
            date=EdtfDate("1962"),
        ),
        0,
    )
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{filled}/bearbeiten").content.decode()
    assert _scan(body).autofocused == "creator"  # confirms the case this guard is about
    assert _fold(body, "Herkunft").is_open, "the autofocus target rendered inside a closed fold"
    assert not _fold(body, "Zugriff").is_open  # the other folds are untouched


# --- publish/withdraw FROM THE EDIT SCREEN: saving is part of publishing ----------
#
# Owner ruling 2 put Veröffentlichen in the same row as Speichern; the lifecycle POST it fired
# rebuilt the record from disk and 302'd away, so every unsaved edit on screen was silently
# discarded. That is DATA LOSS, so this block gets real coverage (testing razor). The decision
# (2026-08-08): publishing from the edit screen SAVES the form first and transitions in the same CAS
# write. No confirm step — that is the gate ruling 5 retired.


def test_publish_from_the_edit_screen_saves_the_form_first(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                **_valid_post(corpus, title="Frisch getippt", creator="Kurt Meyer"),
                "lebenszyklus": "veroeffentlichen",
            },
        )
    assert response.status_code == 302
    assert response["Location"] == f"/artikel/{_ULID}"  # same destination as a plain save
    stored = ArticleRepository(corpus.store).load(_ULID)
    assert stored.article.title == "Frisch getippt"  # the edit was NOT discarded
    assert stored.article.creator == "Kurt Meyer"
    assert stored.article.lifecycle is Lifecycle.PUBLISHED
    assert stored.version == corpus.version + 1  # ONE write, not save-then-publish


def test_withdraw_from_the_edit_screen_saves_the_form_first(corpus: _Corpus) -> None:
    published = "01KX7YT9E3VX0CP3A5Q49RZMWR"
    version = ArticleRepository(corpus.store).save(
        Article(
            ulid=published,
            title="Veröffentlicht",
            collection_id="PUB",
            lifecycle=Lifecycle.PUBLISHED,
        ),
        0,
    )
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{published}/bearbeiten",
            {
                **_valid_post(corpus, title="Doch noch Entwurf", expected_version=str(version)),
                "lebenszyklus": "zurueckziehen",
            },
        )
    assert response.status_code == 302
    stored = ArticleRepository(corpus.store).load(published)
    assert stored.article.title == "Doch noch Entwurf"
    assert stored.article.lifecycle is Lifecycle.DRAFT


def test_publish_with_an_invalid_form_publishes_nothing(corpus: _Corpus) -> None:
    # A validation failure must behave EXACTLY like a failed save: re-render, values preserved,
    # nothing published. It does by construction — the parse runs before any save.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                **_valid_post(corpus, title="", creator="Behalten"),
                "lebenszyklus": "veroeffentlichen",
            },
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body
    assert 'value="Behalten"' in body
    stored = ArticleRepository(corpus.store).load(_ULID)
    assert stored.article.lifecycle is Lifecycle.DRAFT  # nothing published
    assert stored.version == corpus.version  # nothing saved either


def test_publish_on_a_stale_version_behaves_like_a_save_conflict(corpus: _Corpus) -> None:
    archivist = _client_as(Archivist())
    with override_settings(**_settings(corpus)):
        archivist.post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gewinner"))
        loser = archivist.post(
            f"/artikel/{_ULID}/bearbeiten",
            {**_valid_post(corpus, title="Verlierer"), "lebenszyklus": "veroeffentlichen"},
        )
    assert loser.status_code == 200
    body = loser.content.decode()
    assert "Inzwischen geändert" in body
    assert 'value="Verlierer"' in body  # the loser's input survives the conflict re-render
    assert f'name="expected_version" value="{corpus.version + 1}"' in body  # refreshed
    stored = ArticleRepository(corpus.store).load(_ULID)
    assert stored.article.title == "Gewinner"
    assert stored.article.lifecycle is Lifecycle.DRAFT  # the lost race published nothing


def test_unknown_lifecycle_verb_on_the_edit_post_is_404_without_saving(corpus: _Corpus) -> None:
    # Same rule as the standalone lifecycle route: never mutate on a bad verb — and here that means
    # the SAVE does not happen either.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {**_valid_post(corpus, title="Gekapert"), "lebenszyklus": "sabotage"},
        )
    assert_denied(response)
    stored = ArticleRepository(corpus.store).load(_ULID)
    assert stored.article.title == "Wanderfahrt 1962"
    assert stored.version == corpus.version
