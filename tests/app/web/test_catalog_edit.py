"""The full edit form ``/articles/<ulid>/edit`` (Part 4.7 Slice B, spec §2/§3/§6.1/§8).

GET seeds the form from the stored Article; POST parses + saves under CAS (ADR 0013) and 302s to the
read view. Both methods are archivist-gated to a 404 for Member / Public / anonymous, and for a
malformed or absent ulid (existence-hiding). Validation re-renders
state F (verbatim error, preserved values). A raced concurrent save re-renders state G — the
"Inzwischen geändert" notice — with the loser's input preserved and a refreshed ``expected_version``.
The whole write path is REAL (repository + README + CAS); only the index + queue seams are stubbed
(see ``conftest.py``).
"""

import io
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest
from django.http import HttpRequest, QueryDict
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    PUB,
    PUBLISHED_ULID,
    Corpus,
    client_as,
    make_article,
    make_collection,
    page_forms,
)

from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Lifecycle,
    Version,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

if TYPE_CHECKING:
    from bundesarchiv.app.web.card import CardRow

_ULID = "01KX7YT9E3VX0CP3A5Q49RZMVH"


class _EditCorpus:
    """The archive this file edits against: PUB (public) + MEM (members, the Bestand the CAS-diff
    test moves to) and one DRAFT article, plus the version that article was stored at — every CAS
    expectation here is written relative to it. The standard corpus does not fit: its draft carries
    another Titel and Signatur, and these renders assert both verbatim."""

    def __init__(self, corpus: Corpus) -> None:
        self._corpus = corpus
        self.articles = corpus.articles
        corpus.add_collection(
            make_collection("PUB", "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
        )
        corpus.add_collection(
            make_collection("MEM", "Mitglieder", audience=Audience(AudienceTier.MEMBERS))
        )
        self.version = corpus.add_article(
            make_article(
                _ULID,
                collection_id="PUB",
                lifecycle=Lifecycle.DRAFT,
                title="Wanderfahrt 1962",
                ref_code="F12/3",
            )
        )

    def add_article(self, article: Article) -> Version:
        return self._corpus.add_article(article)


@pytest.fixture
def corpus(make_corpus: Callable[[], Corpus]) -> _EditCorpus:
    """Shadows the standard ``corpus`` fixture on purpose — see ``_EditCorpus``."""
    return _EditCorpus(make_corpus())


def _valid_post(corpus: _EditCorpus, **overrides: str) -> dict[str, str]:
    """A minimally-valid edit POST at the article's current version."""
    base = {
        "title": "Wanderfahrt 1962",
        "collection_id": "PUB",
        "ref_code": "F12/3",
        "media_type": "Foto(s)",
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


def test_edit_form_renders_seeded_for_archivist(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).get(f"/articles/{_ULID}/edit")
    assert response.status_code == 200
    body = response.content.decode()
    # the stored values are seeded into the form
    assert ">Wanderfahrt 1962</textarea>" in body
    assert 'value="F12/3"' in body
    for section in ("Kerndaten", "Beschreibung", "Einordnung", "Herkunft", "Medien"):
        assert section in body
    assert "Weitere Angaben" in body
    # the hidden expected_version rides the form
    assert f'name="expected_version" value="{corpus.version}"' in body
    # the Signatur mark reflects ref_code
    assert "F12/3" in body


def test_edit_header_omits_hollow_sig_slot_when_no_ref_code(corpus: _EditCorpus) -> None:
    # Owner finding: the edit header shows the Signatur mark ONLY when a code exists —
    # absence is carried by the Signatur INPUT on the same screen, not a hollow "ohne Signatur" slot
    # (signals-once). The hollow slot stays in the ledger + read view, not here.
    no_sig = "01KX7YT9E3VX0CP3A5Q49RZMWK"
    corpus.add_article(
        make_article(no_sig, collection_id="PUB", lifecycle=Lifecycle.DRAFT, title="Unbetitelt")
    )
    body = client_as(Archivist()).get(f"/articles/{no_sig}/edit").content.decode()
    # the sr-only "Ohne Signatur" text (rendered by the hollow-slot ref_code_tab) must NOT appear —
    # the edit header omits the slot entirely; the Signatur input carries absence instead
    assert "Ohne Signatur" not in body
    # the Signatur input is present and empty
    assert 'name="ref_code" value=""' in body


def test_the_inherit_option_names_who_will_see_the_record(corpus: _EditCorpus) -> None:
    # owner ruling 5: the exposure statement is permanently on screen — here the inherit option says
    # which rung the Bestand hands down, even when the article's own setting overrides it
    body = client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    assert '<option value="" selected>Öffentlich (wie Bestand)</option>' in body
    own = PUBLISHED_ULID
    corpus.add_article(
        make_article(own, collection_id="PUB", audience=Audience(AudienceTier.MEMBERS), title="X")
    )
    body = client_as(Archivist()).get(f"/articles/{own}/edit").content.decode()
    assert '<option value="">Öffentlich (wie Bestand)</option>' in body


# --- GET/POST: archivist gate (both methods, all tiers) ---------------------------


# (The GET deny is the leak matrix's cell for this route — only the POST twin adds the
# nothing-was-changed side-effect assert the matrix can't see.)
@pytest.mark.parametrize("viewer", [Public(), Member(groups=("vorstand",))])
def test_edit_post_is_404_for_non_archivist(corpus: _EditCorpus, viewer: Viewer) -> None:
    response = client_as(viewer).post(
        f"/articles/{_ULID}/edit", _valid_post(corpus, title="Gekapert")
    )
    assert_denied(response)
    # the non-archivist POST changed nothing
    assert corpus.articles.load(_ULID).article.title == "Wanderfahrt 1962"


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_edit_malformed_or_absent_ulid_is_404(corpus: _EditCorpus, ulid: str) -> None:
    response = client_as(Archivist()).get(f"/articles/{ulid}/edit")
    assert_denied(response)


# --- POST: save success + read-view redirect ---------------------------------------


def test_edit_post_saves_and_redirects_to_read_view(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        _valid_post(corpus, title="Neuer Titel", creator="Kurt Meyer"),
    )
    assert response.status_code == 302
    assert response["Location"] == f"/articles/{_ULID}"
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Neuer Titel"
    assert stored.article.creator == "Kurt Meyer"
    assert stored.version == corpus.version + 1


def test_an_edit_keeps_the_date_added(corpus: _EditCorpus) -> None:
    added_at = datetime(2017, 6, 26, 6, 6, 40, tzinfo=UTC)
    ulid = "01KX7YT9E3VX0CP3A5Q49RZMWK"
    version = corpus.add_article(
        make_article(ulid, collection_id="PUB", title="Wanderfahrt 1962", added_at=added_at)
    )
    post = _valid_post(corpus, expected_version=str(version), added_at="2026-01-01T00:00:00Z")
    assert client_as(Archivist()).post(f"/articles/{ulid}/edit", post).status_code == 302
    assert corpus.articles.load(ulid).article.added_at == added_at


@pytest.mark.parametrize("title", ["", "Neuer Titel"], ids=["unchanged", "title"])
def test_the_form_as_rendered_saves_every_other_value_unchanged(
    corpus: _EditCorpus, title: str
) -> None:
    # Each field's pre-fill is parsed back on save. 279 legacy Schlagworte carry a comma, and so may
    # a group name: a save of the form as rendered must not split them, nor touch any other value.
    stored = corpus.articles.load(_ULID)
    before = replace(
        stored.article,
        tags=("Dritte, umgearbeitete Auflage, 1924", "Motiv: 100 % Wolle", "\u00c4rmelwappen"),
        audience=Audience(AudienceTier.GROUPS, ("Gau Wartburg, Nord", "vorstand")),
        media_type="Foto(s)",
        document_type="Zeitschrift",
        date=EdtfDate("1962-07"),
        creator="Kurt Meyer, Bonn",
        body="  Zwei\nZeilen  ",
        custom=(("Quelle", "Nachlass, Teil 2"),),
    )
    version = corpus.articles.save(before, stored.version, changed_by="tester")
    archivist = client_as(Archivist())
    body = archivist.get(f"/articles/{_ULID}/edit").content.decode()
    rendered = next(fields for action, fields in page_forms(body) if action.endswith("/edit"))
    # a browser submits a textarea's line breaks as CRLF
    post = {name: value.replace("\n", "\r\n") for name, value in rendered.items()}
    post["title"] = title or post["title"]
    assert archivist.post(f"/articles/{_ULID}/edit", post).status_code == 302
    after = corpus.articles.load(_ULID)
    assert after.version == version + 1, "the form did not save"
    assert after.article == replace(before, title=title or before.title)


def test_edit_post_empties_optional_to_none(corpus: _EditCorpus) -> None:
    # Clearing the Signatur field must store None, not "" (the "" -> None boundary, spec §8).
    client_as(Archivist()).post(f"/articles/{_ULID}/edit", _valid_post(corpus, ref_code=""))
    assert corpus.articles.load(_ULID).article.ref_code is None


# --- POST: validation state F ------------------------------------------------------


def test_edit_post_bad_document_type_pair_re_renders(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        _valid_post(corpus, media_type="Foto(s)", document_type="Brief"),
    )
    assert response.status_code == 200
    assert "Dieser Dokumenttyp gehört nicht zu „Foto(s)“." in response.content.decode()


# --- POST: CAS conflict state G (two racing clients through the real form) ---------


def test_raced_save_shows_conflict_panel_with_preserved_input(corpus: _EditCorpus) -> None:
    archivist = client_as(Archivist())
    # Both clients load the form at the same version (corpus.version). The FIRST save wins.
    winner = archivist.post(f"/articles/{_ULID}/edit", _valid_post(corpus, title="Gewinner"))
    assert winner.status_code == 302
    # The SECOND save carries the now-stale version -> Conflict -> state G re-render.
    loser = archivist.post(
        f"/articles/{_ULID}/edit",
        _valid_post(corpus, title="Verlierer", creator="Meine Eingabe"),
    )
    assert loser.status_code == 200
    body = loser.content.decode()
    assert "Inzwischen geändert" in body  # the notice's heading
    assert ">Verlierer</textarea>" in body  # the loser's just-typed title is preserved
    assert 'value="Meine Eingabe"' in body  # and their other input
    # each differing field is invalid and described by what is stored now, "(leer)" for nothing
    conflict = _conflict(body)
    assert conflict.links == [("Titel", "feld-title"), ("Autor", "feld-creator")]
    assert conflict.stored_value("feld-title") == "Inzwischen gespeichert: Gewinner"
    assert conflict.stored_value("feld-creator") == "Inzwischen gespeichert: (leer)"
    # the store is at the WINNER's value + version (no last-writer-wins)
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Gewinner"
    assert stored.version == corpus.version + 1


def test_conflict_refreshes_expected_version_so_next_save_wins(corpus: _EditCorpus) -> None:
    archivist = client_as(Archivist())
    archivist.post(f"/articles/{_ULID}/edit", _valid_post(corpus, title="Gewinner"))
    loser = archivist.post(f"/articles/{_ULID}/edit", _valid_post(corpus, title="Verlierer"))
    body = loser.content.decode()
    # the re-rendered form now carries the WINNER's current version
    new_version = corpus.version + 1
    assert f'name="expected_version" value="{new_version}"' in body
    # re-submitting at that refreshed version now WINS
    retry = archivist.post(
        f"/articles/{_ULID}/edit",
        _valid_post(corpus, title="Verlierer", expected_version=str(new_version)),
    )
    assert retry.status_code == 302
    assert corpus.articles.load(_ULID).article.title == "Verlierer"


# --- POST: stale save against a hard-deleted article -------------------------------


@pytest.mark.parametrize("for_good", [True, False])
def test_stale_save_against_deleted_article_is_404(
    corpus: _EditCorpus, monkeypatch: pytest.MonkeyPatch, for_good: bool
) -> None:
    # Deleted, for good (media and all) or into the Papierkorb, between the gate's load and this
    # POST's save: the save refuses as stale before it checks media, and the re-load is the plain
    # 404 — never a 500, and never the conflict panel over a marked record (ADR 0022).
    from bundesarchiv.app.web import catalog_views

    stored = corpus.articles.load(_ULID)
    scan = corpus.articles.add_media(_ULID, "scan.pdf", io.BytesIO(b"scan"))
    version = corpus.articles.save(
        replace(stored.article, media=(scan,)), stored.version, changed_by="tester"
    )

    real_gated = catalog_views._load_gated

    def _delete_then_gate(request: HttpRequest, ulid: str) -> tuple[object, object, object] | None:
        gated = real_gated(request, ulid)
        now = corpus.articles.load(_ULID)
        if for_good:
            corpus.articles.hard_delete(_ULID, now.version)
        else:
            corpus.articles.mark_deleted(now.article, now.version, changed_by="bert")
        return gated

    monkeypatch.setattr(catalog_views, "_load_gated", _delete_then_gate)
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit", _valid_post(corpus, expected_version=str(version))
    )
    assert_denied(response)


# --- no-JS custom-row removal ------------------------------------------------------


def test_custom_entfernen_drops_the_row_without_saving(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
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
    assert corpus.articles.load(_ULID).version == corpus.version


def test_the_bag_renders_no_empty_pair_until_one_is_added(corpus: _EditCorpus) -> None:
    body = client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    assert 'name="custom_key"' not in body
    assert "+ Angabe hinzufügen" in body


def test_angabe_hinzufuegen_adds_one_empty_pair_without_saving(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {
            **_valid_post(corpus),
            "custom_key": ["Fotograf"],
            "custom_value": ["Meyer"],
            "custom_neu": "",
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert 'value="Meyer"' in body  # the typed row survives the round trip
    assert body.count('name="custom_key" value=""') == 1
    assert _autofocused(body) == "custom_key"
    assert corpus.articles.load(_ULID).version == corpus.version


def test_custom_entfernen_index_survives_an_earlier_row_blanked_in_browser(
    corpus: _EditCorpus,
) -> None:
    # A blanked-out earlier row shifts positions once `_post_to_form_values` drops it — but
    # `custom_entfernen` names a position in the RAW POST lists (what the row's remove cross
    # actually submitted), not in that filtered result. Rows A/B/C, A blanked, the cross on B (raw
    # index 1) must drop B and keep C — not drop C because the filtered list only has two left.
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
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
    assert corpus.articles.load(_ULID).version == corpus.version


# --- POST re-render fidelity: lifecycle + custom-row accumulation ------------------


def test_published_article_invalid_post_re_render_keeps_its_status(corpus: _EditCorpus) -> None:
    # The re-render takes the Status from the record, never assumes a draft.
    published = "01KX7YT9E3VX0CP3A5Q49RZMWP"
    corpus.add_article(
        make_article(
            published,
            collection_id="PUB",
            lifecycle=Lifecycle.PUBLISHED,
            title="Veröffentlicht",
            ref_code="F99/1",
        )
    )
    response = client_as(Archivist()).post(
        f"/articles/{published}/edit",
        {
            **_valid_post(corpus, expected_version="0"),
            "title": "",  # invalid -> validation error re-render (state F)
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body  # confirms we hit the error re-render
    assert _status(body).selected == ["published"]


def test_repeated_invalid_post_does_not_accumulate_blank_custom_rows(corpus: _EditCorpus) -> None:
    # An error re-render must not grow one blank custom row per round trip.
    first = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {
            **_valid_post(corpus, title=""),
            "custom_key": ["Fotograf", ""],
            "custom_value": ["Meyer", ""],
        },
    )
    assert first.status_code == 200
    first_body = first.content.decode()
    first_blank_pairs = first_body.count('name="custom_key" value=""')
    assert first_blank_pairs == 0  # the blank row is dropped, never re-added

    # re-send the same hand-built payload (the first assertion pinned it equivalent to the
    # re-rendered form) — the blank-row count must not grow
    second = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {
            **_valid_post(corpus, title=""),
            "custom_key": ["Fotograf", ""],
            "custom_value": ["Meyer", ""],
        },
    )
    assert second.status_code == 200
    second_body = second.content.decode()
    second_blank_pairs = second_body.count('name="custom_key" value=""')
    assert second_blank_pairs == 0


class _ControlScanner(HTMLParser):
    """The attributes of every named control a render prints, in document order — the page's own,
    not those of a form in a tool panel (the header's "Neuer Artikel …")."""

    def __init__(self) -> None:
        super().__init__()
        self.controls: list[dict[str, str | None]] = []
        self._in_panel = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form":
            self._in_panel = "popover" in values
        if values.get("name") and not self._in_panel:
            self.controls.append(values)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._in_panel = False


def _controls(body: str) -> list[dict[str, str | None]]:
    scanner = _ControlScanner()
    scanner.feed(body)
    return scanner.controls


def _autofocused(body: str) -> str:
    """The name of the control a render marks ``autofocus`` — the first, as a browser takes it."""
    return next((str(c["name"]) for c in _controls(body) if "autofocus" in c), "")


# --- the field registry's columns ---------------------------------------------------
#
# Dropping `scanned=True`, dropping `focusable=True`, or deleting a whole `_Field` row left the fast
# suite AND the e2e suite green.
# The consequential column is `diff`: `_conflict_rows` derives the CAS "Inzwischen geändert" notice
# from it, so a dropped `diff=` means a racing archivist is silently not told that field changed under
# them — loss-adjacent, on the surface tests/CLAUDE.md calls load-bearing. Each guard below joins the
# registry to the REAL render or the real behaviour, never to a second hand-written list.


def _card_rows(*, autofocus: str = "", errors: dict[str, str] | None = None) -> list[CardRow]:
    """Every record-card row the registry renders, in DOM order, for a blank form."""
    from bundesarchiv.app.web.card import card_fields

    sections = card_fields(
        {"ulid": _ULID}, CollectionChooser(lambda: ()), errors=errors or {}, autofocus=autofocus
    )
    return [row for group in sections.values() for row in group]


def test_the_card_renders_every_field_the_registry_declares(corpus: _EditCorpus) -> None:
    # The card's sections are `{% for %}` loops over `card_fields`, so the template can no longer
    # render a field the registry does not declare — that direction is closed by construction. The
    # open direction is a section whose loop was never wired: walk the real render for each declared
    # control.
    from bundesarchiv.app.web.card import FIELDS

    body = client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    declared = [f.name for f in FIELDS if f.control]
    assert len(declared) >= 13, f"the registry declares {declared} — the guard proves nothing"
    for name in declared:
        assert f'name="{name}"' in body, f"the card renders no control for {name}"


def test_only_a_focusable_field_can_carry_the_autofocus() -> None:
    # `focusable` is what `first_error_field` scans, so a field marked focusable whose control never
    # receives `autofocus` focuses NOTHING on a validation re-render — silent, and in source it looks
    # exactly like a working one. One partial wires the attribute now, off `row.autofocus`, so the
    # relation is the registry's: every focusable field can take the caret, nothing else can.
    from bundesarchiv.app.web.card import FIELDS

    focusable = [f.name for f in FIELDS if f.focusable]
    assert len(focusable) >= 8, f"only {focusable} focusable — the guard proves nothing"
    for name in focusable:
        focused = [row.name for row in _card_rows(autofocus=name) if row.autofocus]
        assert focused == [name], f"autofocus on {name} landed on {focused}"
    unfocusable = [row.name for row in _card_rows(autofocus="sichtbarkeit") if row.autofocus]
    assert not unfocusable, "„sichtbarkeit“ is not focusable but took the caret"


def test_every_card_field_seeds_from_the_stored_article() -> None:
    # The GET seed: one wrong `seed=` silently offers the archivist another field's value, and the
    # next Speichern writes it. The whole table in one place, so a mis-wired row cannot hide behind
    # the three fields the HTTP renders happen to assert.
    from bundesarchiv.app.web.catalog_views import _article_to_form_values

    article = make_article(
        _ULID,
        lifecycle=Lifecycle.DRAFT,
        title="Wanderfahrt 1962",
        ref_code="F12/3",
        media_type="Foto(s)",
        document_type="Zeitschrift",
        tags=("sommer", "fahrt"),
        date=EdtfDate("1962-07"),
        creator="Kurt Meyer",
        subject_place="Bonn",
        physical_location="Regal 3",
        body="Ein Text.",
        audience=Audience(tier=AudienceTier.GROUPS, groups=("vorstand", "archiv")),
        custom=(("Fotograf", "Meyer"),),
    )
    assert _article_to_form_values(article) == {
        "ulid": _ULID,
        "title": "Wanderfahrt 1962",
        "lifecycle": "draft",
        "collection_id": PUB,
        "ref_code": "F12/3",
        "media_type": "Foto(s)",
        "document_type": "Zeitschrift",
        "tags": "sommer\nfahrt",
        "date": "1962-07",
        "creator": "Kurt Meyer",
        "subject_place": "Bonn",
        "physical_location": "Regal 3",
        "body": "Ein Text.",
        "sichtbarkeit": "groups",
        "gruppen": "vorstand\narchiv",
        "custom_rows": [("Fotograf", "Meyer")],
    }


def test_every_card_field_echoes_the_post_verbatim() -> None:
    # The re-render echo: a field the echo forgets comes back BLANK, and the archivist's next save
    # writes that blank over the stored value. Data loss, so the whole table is walked, not sampled.
    from bundesarchiv.app.web.card import FIELDS
    from bundesarchiv.app.web.catalog_views import _post_to_form_values

    # the Status echoes only a Status (the fallback is its own test), so it types the other one
    typed = {f.name: f"getippt {f.name}" for f in FIELDS if f.control} | {"lifecycle": "published"}
    values = _post_to_form_values(QueryDict(urlencode(typed)), _ULID, Lifecycle.DRAFT)
    assert len(typed) >= 13, f"only {sorted(typed)} typed — the walk proves nothing"
    for name, text in typed.items():
        assert values[name] == text, f"{name} echoed {values.get(name)!r}, not {text!r}"


def test_the_cas_diff_spells_the_rung_and_the_state_in_german() -> None:
    # Two rows do not print their form value: Sichtbarkeit holds the rung's machine value in the
    # select ("members"), and lifecycle is an enum member. Both must reach the archivist as the German
    # word — the row list guards WHICH rows appear, this guards what they say.
    from bundesarchiv.app.web.catalog_views import _conflict_rows

    audience = _conflict_rows(
        make_article(_ULID, audience=Audience(AudienceTier.PUBLIC)),
        make_article(_ULID, audience=Audience(AudienceTier.MEMBERS)),
    )
    assert [(r.label, r.stored) for r in audience] == [("Sichtbarkeit", "Alle Mitglieder")]
    state = _conflict_rows(
        make_article(_ULID, lifecycle=Lifecycle.DRAFT),
        make_article(_ULID, lifecycle=Lifecycle.PUBLISHED),
    )
    assert [(r.label, r.stored) for r in state] == [("Status", "Veröffentlicht")]


def test_scanned_is_the_focusable_spine_minus_the_one_declared_exception() -> None:
    # `scanned` is the GET autofocus spine: the fields walked for the first EMPTY one. It is the
    # focusable set minus exactly ONE declared exception — Gruppen, which is empty on almost every
    # record by design (it means something only at the GROUPS rung), so scanning it would park the
    # caret there on every fully catalogued record. Pinning the relation rather than the membership means a dropped `scanned=True` fails here, and a SECOND
    # exception has to be argued for rather than typed.
    from bundesarchiv.app.web.card import FIELDS

    scanned = {f.name for f in FIELDS if f.scanned}
    focusable = {f.name for f in FIELDS if f.focusable}
    assert scanned == focusable - {"gruppen"}, f"spine {sorted(scanned)} vs {sorted(focusable)}"


def test_every_scanned_field_is_reachable_as_the_first_empty_one() -> None:
    # ...and the spine BEHAVES: for each scanned field, a record whose earlier spine fields are all
    # filled and this one empty must autofocus exactly it. A walker over the spine, so a field dropped
    # from it (or reordered out of DOM order) is caught for every field, not just for `creator` — the
    # one instance an existing e2e journey happens to pin.
    from bundesarchiv.app.web.card import FIELDS, first_empty_field

    spine = [f.name for f in FIELDS if f.scanned]
    assert len(spine) >= 8, f"the spine is {spine} — the walk proves nothing"
    for name in spine:
        values: dict[str, object] = {f: "gefüllt" for f in spine if f != name}
        assert first_empty_field(values) == name, (
            f"with only {name} empty the autofocus went to {first_empty_field(values)}"
        )


def test_the_card_marks_required_exactly_the_fields_the_save_rejects_blank(
    corpus: _EditCorpus,
) -> None:
    # The "*" is a promise about the save: a field it marks must be refused blank, and a field the
    # save refuses blank must carry it. Both sides are read back: the markers from the render, the
    # refusals from the parse.
    from bundesarchiv.app.web import catalog
    from bundesarchiv.app.web.card import FIELDS

    body = client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    marked = {str(c["name"]) for c in _controls(body) if c.get("aria-required") == "true"}
    chooser = CollectionChooser(lambda: (make_collection("PUB"),))
    refused = {
        registered.name
        for registered in FIELDS
        if registered.control
        and registered.name
        in catalog.parse_edit_form(
            {**_valid_post(corpus), registered.name: ""},
            ulid=_ULID,
            chooser=chooser,
            added_at=None,
            deleted=None,
        ).errors
    }
    assert refused, "no field is refused blank — the guard proves nothing"
    assert marked == refused


#: Every field the CAS "Inzwischen geändert" notice names when all of them changed, in the order it shows
#: them — the archivist's contract on the loss-adjacent surface, so it is pinned VERBATIM rather than
#: derived from the registry it guards (an expectation read off `FIELDS` moves with a dropped `diff=`
#: and asserts nothing: dropping `diff="Ort"` was green against it).
#: Bestand is deliberately absent: a diff of collection MOVES is its own surface, not this one.
_CAS_DIFF_ROWS = (
    "Titel",
    "Status",
    "Sichtbarkeit",
    "Signatur",
    "Standort",
    "Beschreibung",
    "Medienart",
    "Dokumenttyp",
    "Schlagworte",
    "Autor",
    "Ort",
    "Datierung",
)


def test_the_cas_diff_lists_every_registry_field_that_changed(corpus: _EditCorpus) -> None:
    # `diff` drives the "Inzwischen geändert" notice and the line under each field, and a dropped
    # label means a racing archivist is silently not told that field changed under them. Force a
    # conflict in which EVERY diffable field differs and compare the notice's links against the pinned
    # list — so a dropped `diff=`, a reordered registry and a field the notice cannot point at fail.
    archivist = client_as(Archivist())
    changed = {
        "title": "Anderer Titel",
        "collection_id": "MEM",
        "ref_code": "X99",
        "media_type": "Buch",
        "document_type": "Kalender",
        "tags": "herbst",
        "date": "1970",
        "creator": "Andere Hand",
        "subject_place": "Anderer Ort",
        "physical_location": "Anderes Regal",
        "body": "Andere Beschreibung",
        "sichtbarkeit": "members",
    }
    winner = archivist.post(f"/articles/{_ULID}/edit", _valid_post(corpus, **changed))
    assert winner.status_code == 302
    # The loser submits the ORIGINAL values at the now-stale version, so every field differs — and
    # publishes, which is the only way to make the STATUS row differ too (the loser's own lifecycle
    # is otherwise read from the article on disk, i.e. the winner's).
    loser = archivist.post(
        f"/articles/{_ULID}/edit",
        _valid_post(corpus, lifecycle="published"),
    )
    assert loser.status_code == 200
    conflict = _conflict(loser.content.decode())
    labels = [label for label, _ in conflict.links]
    assert labels == list(_CAS_DIFF_ROWS), f"the notice listed {labels}, not {list(_CAS_DIFF_ROWS)}"
    for label, target in conflict.links:
        assert conflict.stored_value(target).startswith("Inzwischen gespeichert: "), label


_VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"})


class _ConflictScanner(HTMLParser):
    """The conflict notice's links (label, target id), and every element by id with its attributes
    and text — enough to follow a link to its control and the control to its descriptions."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.attrs: dict[str, dict[str, str | None]] = {}
        self.text: dict[str, str] = {}
        self._open: list[str | None] = []
        self._alert_depth: int | None = None
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if element_id := values.get("id"):
            self.attrs[element_id] = values
            self.text.setdefault(element_id, "")
        if self._alert_depth is not None and tag == "a":
            self._href = (values.get("href") or "").removeprefix("#")
        if tag in _VOID:
            return
        if values.get("role") == "alert":
            self._alert_depth = len(self._open)
        self._open.append(values.get("id"))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or not self._open:
            return
        self._open.pop()
        if self._alert_depth is not None and len(self._open) == self._alert_depth:
            self._alert_depth = None

    def handle_data(self, data: str) -> None:
        for element_id in filter(None, self._open):
            self.text[element_id] += data
        if self._href is not None and data.strip():
            self.links.append((data.strip(), self._href))
            self._href = None

    def stored_value(self, control_id: str) -> str:
        """The "Inzwischen gespeichert" line of an INVALID control, found via aria-describedby."""
        control = self.attrs[control_id]
        assert control.get("aria-invalid") == "true", f"{control_id} is not marked invalid"
        described = (control.get("aria-describedby") or "").split()
        lines = [
            " ".join(self.text[i].split())
            for i in described
            if self.text.get(i, "").strip().startswith("Inzwischen gespeichert")
        ]
        assert len(lines) == 1, f"{control_id} is described by {described}"
        return lines[0]


def _conflict(body: str) -> _ConflictScanner:
    scanner = _ConflictScanner()
    scanner.feed(body)
    return scanner


def test_a_gruppen_error_renders_its_message(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit", _valid_post(corpus, sichtbarkeit="groups", gruppen="")
    )
    assert response.status_code == 200
    assert "Bitte mindestens eine Gruppe angeben." in response.content.decode()


def test_a_custom_bag_error_renders_its_message(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {**_valid_post(corpus), "custom_key": ["title"], "custom_value": ["gekapert"]},
    )
    assert response.status_code == 200
    assert "Bezeichnung ist reserviert." in response.content.decode()


# --- Status: one select in the margin, applied by Speichern ------------------------
#
# Saving is part of publishing (owner decision 2026-08-08): the Status the archivist chose rides the
# form's ONE CAS write with every unsaved edit. Losing those edits, or publishing by accident, is the
# risk this block covers (testing razor).

_PUBLISHED_ULID = "01KX7YT9E3VX0CP3A5Q49RZMWR"


def _published(corpus: _EditCorpus) -> Version:
    return corpus.add_article(
        make_article(
            _PUBLISHED_ULID,
            collection_id="PUB",
            lifecycle=Lifecycle.PUBLISHED,
            title="Veröffentlicht",
        )
    )


class _StatusScanner(HTMLParser):
    """The Status select's options (value, caption) and the selected value, as rendered."""

    def __init__(self) -> None:
        super().__init__()
        self.options: list[tuple[str, str]] = []
        self.selected: list[str] = []
        self._in_select = False
        self._value: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "select" and values.get("name") == "lifecycle":
            self._in_select = True
        elif tag == "option" and self._in_select:
            self._value = values.get("value") or ""
            if "selected" in values:
                self.selected.append(self._value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._in_select = False

    def handle_data(self, data: str) -> None:
        if self._value is not None and data.strip():
            self.options.append((self._value, data.strip()))
            self._value = None


def _status(body: str) -> _StatusScanner:
    scanner = _StatusScanner()
    scanner.feed(body)
    return scanner


def test_the_margin_offers_the_status_seeded_from_the_record(corpus: _EditCorpus) -> None:
    _published(corpus)
    archivist = client_as(Archivist())
    draft = _status(archivist.get(f"/articles/{_ULID}/edit").content.decode())
    assert draft.options == [("published", "Veröffentlicht"), ("draft", "Entwurf (nur Archivare)")]
    assert draft.selected == ["draft"]
    published = _status(archivist.get(f"/articles/{_PUBLISHED_ULID}/edit").content.decode())
    assert published.selected == ["published"]


@pytest.mark.parametrize(
    ("record", "status"),
    [("draft", "draft"), ("published", "published")],
)
def test_an_unchanged_status_is_a_plain_save(corpus: _EditCorpus, record: str, status: str) -> None:
    ulid, version = (
        (_ULID, corpus.version) if record == "draft" else (_PUBLISHED_ULID, _published(corpus))
    )
    response = client_as(Archivist()).post(
        f"/articles/{ulid}/edit",
        {
            **_valid_post(corpus, title="Neu getippt", expected_version=str(version)),
            "lifecycle": status,
        },
    )
    assert response.status_code == 302
    stored = corpus.articles.load(ulid)
    assert stored.article.title == "Neu getippt"
    assert stored.article.lifecycle is Lifecycle(status)


def test_publish_from_the_edit_screen_saves_the_form_first(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {
            **_valid_post(corpus, title="Frisch getippt", creator="Kurt Meyer"),
            "lifecycle": "published",
        },
    )
    assert response.status_code == 302
    assert response["Location"] == f"/articles/{_ULID}"  # same destination as a plain save
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Frisch getippt"  # the edit was NOT discarded
    assert stored.article.creator == "Kurt Meyer"
    assert stored.article.lifecycle is Lifecycle.PUBLISHED
    assert stored.version == corpus.version + 1  # ONE write, not save-then-publish


def test_withdraw_from_the_edit_screen_saves_the_form_first(corpus: _EditCorpus) -> None:
    version = _published(corpus)
    response = client_as(Archivist()).post(
        f"/articles/{_PUBLISHED_ULID}/edit",
        {
            **_valid_post(corpus, title="Doch noch Entwurf", expected_version=str(version)),
            "lifecycle": "draft",
        },
    )
    assert response.status_code == 302
    stored = corpus.articles.load(_PUBLISHED_ULID)
    assert stored.article.title == "Doch noch Entwurf"
    assert stored.article.lifecycle is Lifecycle.DRAFT


def test_publish_with_an_invalid_form_publishes_nothing(corpus: _EditCorpus) -> None:
    # A validation failure must behave EXACTLY like a failed save: re-render, values preserved,
    # nothing published. It does by construction — the parse runs before any save.
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {
            **_valid_post(corpus, title="", creator="Behalten"),
            "lifecycle": "published",
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body
    assert 'value="Behalten"' in body
    assert _status(body).selected == ["published"]  # the chosen Status survives the re-render
    stored = corpus.articles.load(_ULID)
    assert stored.article.lifecycle is Lifecycle.DRAFT  # nothing published
    assert stored.version == corpus.version  # nothing saved either


def test_a_re_render_without_a_valid_status_shows_the_stored_one(corpus: _EditCorpus) -> None:
    # Veröffentlicht is the select's first option, so a re-render whose value matches no option would
    # show it — and the next Speichern would publish a draft nobody chose to publish.
    for posted in ({}, {"lifecycle": "sabotage"}):
        response = client_as(Archivist()).post(
            f"/articles/{_ULID}/edit",
            {**_valid_post(corpus), **posted, "custom_neu": ""},
        )
        assert response.status_code == 200
        assert _status(response.content.decode()).selected == ["draft"], posted


def test_publish_on_a_stale_version_behaves_like_a_save_conflict(corpus: _EditCorpus) -> None:
    archivist = client_as(Archivist())
    archivist.post(f"/articles/{_ULID}/edit", _valid_post(corpus, title="Gewinner"))
    loser = archivist.post(
        f"/articles/{_ULID}/edit",
        {**_valid_post(corpus, title="Verlierer"), "lifecycle": "published"},
    )
    assert loser.status_code == 200
    body = loser.content.decode()
    assert "Inzwischen geändert" in body
    assert ">Verlierer</textarea>" in body  # the loser's input survives the conflict re-render
    assert f'name="expected_version" value="{corpus.version + 1}"' in body  # refreshed
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Gewinner"
    assert stored.article.lifecycle is Lifecycle.DRAFT  # the lost race published nothing


@pytest.mark.parametrize("status", ["sabotage", "", "veroeffentlichen", "PUBLISHED", " draft"])
def test_an_unknown_status_on_the_edit_post_is_404_without_saving(
    corpus: _EditCorpus, status: str
) -> None:
    # Never mutate on a bad value — and here that means the SAVE does not happen either.
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {**_valid_post(corpus, title="Gekapert"), "lifecycle": status},
    )
    assert_denied(response)
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Wanderfahrt 1962"
    assert stored.version == corpus.version
