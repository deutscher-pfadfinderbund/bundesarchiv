"""The full edit form ``/artikel/<ulid>/bearbeiten`` (Part 4.7 Slice B, spec §2/§3/§6.1/§8).

GET seeds the form from the stored Article; POST parses + saves under CAS (ADR 0013) and 302s to the
read view. Both methods are archivist-gated to a 404 for Member / Public / anonymous, and for a
malformed or absent ulid (existence-hiding). Validation re-renders
state F (verbatim error, preserved values). A raced concurrent save re-renders state G — the
"Inzwischen geändert" panel — with the loser's input preserved and a refreshed ``expected_version``.
The whole write path is REAL (repository + README + CAS); only the index + queue seams are stubbed
(see ``conftest.py``).
"""

import io
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest
from django.http import HttpRequest, QueryDict
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    PUB,
    Corpus,
    client_as,
    draft_mark,
    make_article,
    make_collection,
)

from bundesarchiv.app.web.bestand import BestandChooser
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
    from bundesarchiv.app.web.catalog_views import _CardRow

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
    response = client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten")
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
    # the Entwurf mark (draft) sits in the header
    assert "Entwurf" in body
    # the Signatur mark reflects ref_code
    assert "F12/3" in body


def test_edit_header_omits_hollow_sig_slot_when_no_ref_code(corpus: _EditCorpus) -> None:
    # fix-wave (owner finding): the edit header shows the Signatur mark ONLY when a code exists —
    # absence is carried by the Signatur INPUT on the same screen, not a hollow "ohne Signatur" slot
    # (signals-once). The hollow slot stays in the ledger + read view, not here.
    no_sig = "01KX7YT9E3VX0CP3A5Q49RZMWK"
    corpus.add_article(
        make_article(no_sig, collection_id="PUB", lifecycle=Lifecycle.DRAFT, title="Unbetitelt")
    )
    body = client_as(Archivist()).get(f"/artikel/{no_sig}/bearbeiten").content.decode()
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
def test_edit_post_is_404_for_non_archivist(corpus: _EditCorpus, viewer: Viewer) -> None:
    response = client_as(viewer).post(
        f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gekapert")
    )
    assert_denied(response)
    # the non-archivist POST changed nothing
    assert corpus.articles.load(_ULID).article.title == "Wanderfahrt 1962"


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_edit_malformed_or_absent_ulid_is_404(corpus: _EditCorpus, ulid: str) -> None:
    response = client_as(Archivist()).get(f"/artikel/{ulid}/bearbeiten")
    assert_denied(response)


# --- POST: save success + read-view redirect ---------------------------------------


def test_edit_post_saves_and_redirects_to_read_view(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
        _valid_post(corpus, title="Neuer Titel", creator="Kurt Meyer"),
    )
    assert response.status_code == 302
    assert response["Location"] == f"/artikel/{_ULID}"
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
    assert client_as(Archivist()).post(f"/artikel/{ulid}/bearbeiten", post).status_code == 302
    assert corpus.articles.load(ulid).article.added_at == added_at


def test_edit_post_empties_optional_to_none(corpus: _EditCorpus) -> None:
    # Clearing the Signatur field must store None, not "" (the "" -> None boundary, spec §8).
    client_as(Archivist()).post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, ref_code=""))
    assert corpus.articles.load(_ULID).article.ref_code is None


# --- POST: validation state F ------------------------------------------------------


def test_edit_post_missing_title_re_renders_state_f(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="", creator="Behalten")
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body
    assert 'value="Behalten"' in body  # the just-typed value is preserved
    # nothing saved
    assert corpus.articles.load(_ULID).version == corpus.version


def test_edit_post_bad_document_type_pair_re_renders(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
        _valid_post(corpus, media_type="Foto(s)", document_type="Brief"),
    )
    assert response.status_code == 200
    assert "Dieser Dokumenttyp gehört nicht zu „Foto(s)“." in response.content.decode()


# --- POST: CAS conflict state G (two racing clients through the real form) ---------


def test_raced_save_shows_conflict_panel_with_preserved_input(corpus: _EditCorpus) -> None:
    archivist = client_as(Archivist())
    # Both clients load the form at the same version (corpus.version). The FIRST save wins.
    winner = archivist.post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gewinner"))
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
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Gewinner"
    assert stored.version == corpus.version + 1


def test_conflict_refreshes_expected_version_so_next_save_wins(corpus: _EditCorpus) -> None:
    archivist = client_as(Archivist())
    archivist.post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gewinner"))
    loser = archivist.post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Verlierer"))
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
    assert corpus.articles.load(_ULID).article.title == "Verlierer"


# --- POST: stale save against a hard-deleted article -------------------------------


def test_stale_save_against_deleted_article_is_404(
    corpus: _EditCorpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hard-deleted, media and all, between the gate's load and this POST's save: the save refuses
    # as stale before it checks media, and the re-load's NotFound is the plain 404, never a 500.
    from bundesarchiv.app.web import catalog_views

    stored = corpus.articles.load(_ULID)
    scan = corpus.articles.add_media(_ULID, "scan.pdf", io.BytesIO(b"scan"))
    version = corpus.articles.save(
        replace(stored.article, media=(scan,)), stored.version, changed_by="tester"
    )

    real_gated = catalog_views._load_gated

    def _delete_then_gate(request: HttpRequest, ulid: str) -> tuple[object, object, object] | None:
        gated = real_gated(request, ulid)
        corpus.articles.hard_delete(_ULID)
        return gated

    monkeypatch.setattr(catalog_views, "_load_gated", _delete_then_gate)
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, expected_version=str(version))
    )
    assert_denied(response)


# --- no-JS custom-row removal ------------------------------------------------------


def test_custom_entfernen_drops_the_row_without_saving(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
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
    assert corpus.articles.load(_ULID).version == corpus.version
    assert _fold(body, "Weitere Angaben").is_open, "the bag folded under the row just removed"


def test_the_bag_renders_no_empty_pair_until_one_is_added(corpus: _EditCorpus) -> None:
    body = client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten").content.decode()
    assert 'name="custom_key"' not in body
    assert "+ Angabe hinzufügen" in body


def test_angabe_hinzufuegen_adds_one_empty_pair_without_saving(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
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
    scan = _scan(body)
    assert scan.autofocused == "custom_key"
    assert _fold(body, "Weitere Angaben").is_open
    assert corpus.articles.load(_ULID).version == corpus.version


def test_custom_entfernen_index_survives_an_earlier_row_blanked_in_browser(
    corpus: _EditCorpus,
) -> None:
    # A blanked-out earlier row shifts positions once `_post_to_form_values` drops it — but
    # `custom_entfernen` names a position in the RAW POST lists (what the row's remove cross
    # actually submitted), not in that filtered result. Rows A/B/C, A blanked, the cross on B (raw
    # index 1) must drop B and keep C — not drop C because the filtered list only has two left.
    response = client_as(Archivist()).post(
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
    assert corpus.articles.load(_ULID).version == corpus.version


# --- POST re-render fidelity: lifecycle + custom-row accumulation ------------------


def test_published_article_invalid_post_re_render_omits_entwurf_mark(corpus: _EditCorpus) -> None:
    # fix-wave: `_post_to_form_values` hardcoded is_draft=True, so a PUBLISHED article's
    # validation-error re-render wrongly showed the Entwurf mark.
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
        f"/artikel/{published}/bearbeiten",
        {
            **_valid_post(corpus, expected_version="0"),
            "title": "",  # invalid -> validation error re-render (state F)
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body  # confirms we hit the error re-render
    assert draft_mark() not in body


def test_repeated_invalid_post_does_not_accumulate_blank_custom_rows(corpus: _EditCorpus) -> None:
    # fix-wave: unconditionally appending a blank add-row produced +1 blank row per error re-render.
    first = client_as(Archivist()).post(
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
    assert first_blank_pairs == 0  # the blank row is dropped, never re-added

    # re-send the same hand-built payload (the first assertion pinned it equivalent to the
    # re-rendered form) — the blank-row count must not grow
    second = client_as(Archivist()).post(
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
    assert second_blank_pairs == 0


# --- folded sections: a fold may hide neither a message nor the focus -------------
#
# Owner ruling 4 folds the rare sections WITH their values in the summary — folding may never hide
# data. The form wave left two ways for it to hide something else: a validation error rendered inside
# a folded section is invisible (Sichtbarkeit=Gruppe(n) with an empty Gruppen field; errors.custom in
# the bag), and `autofocus` on a field inside a fold focuses nothing at all, because a closed
# <details> has no focusable contents (the field registry holds three such fields). Both are now
# decided server-side from the same context that renders the message — catalog_views._open_sections.
#
# DELIBERATE LAYERING, not duplication (do not collapse): these prove the SERVER's decision — which
# fold carries [open], which field carries `autofocus` — while the e2e pair
# (test_a_fold_hides_neither_the_error_nor_the_focus / test_a_fold_never_swallows_the_autofocus)
# proves what only a browser can answer: is the message on screen, is the input actually focused.


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

    Scoped to ``.karte`` STRUCTURALLY: a ``<details>`` outside the card is not a fold. Hidden inputs are still skipped: they are plumbing
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
        if tag == "details" and self._karte_depth is not None:
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
            if self._karte_depth == self._depth:
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


def test_folded_sections_own_every_field_they_hold(corpus: _EditCorpus) -> None:
    # The drift guard for the mechanism above: the field registry is the ONE declaration of which
    # fields live behind which fold, so a field moved into a fold without a `section` would silently
    # lose the open-on-error/open-on-focus behaviour. Walk the real render instead of trusting the map.
    #
    # A field maps to AT MOST ONE section BY CONSTRUCTION now — the registry gives each field one
    # `section` string, where the old shape was three frozensets that could overlap — so the three
    # lines that used to rule out that impossibility went with it.
    from bundesarchiv.app.web.catalog_views import _SECTION_FIELDS

    with_bag = "01KX7YT9E3VX0CP3A5Q49RZMWR"  # the bag renders its fields only once it holds a row
    corpus.add_article(make_article(with_bag, collection_id="PUB", custom=(("Fotograf", "Meyer"),)))
    body = client_as(Archivist()).get(f"/artikel/{with_bag}/bearbeiten").content.decode()
    folds = _folds(body)
    assert len(folds) == 3, (
        f"the scanner found {[f.label for f in folds]} — the guard proves nothing"
    )
    for fold in folds:
        owners = [name for name, fields in _SECTION_FIELDS.items() if fold.fields & fields]
        assert owners, f"„{fold.label}“ ({sorted(fold.fields)}) belongs to no declared section"
        unowned = fold.fields - _SECTION_FIELDS[owners[0]]
        assert not unowned, f"„{fold.label}“ holds {sorted(unowned)}, absent from the registry"


# --- the field registry's OTHER columns ---------------------------------------------
#
# `section` had the walk above and the other columns had nothing: dropping `scanned=True`, dropping
# `focusable=True`, or deleting a whole `_Field` row left the fast suite AND the e2e suite green.
# The consequential column is `diff`: `_conflict_rows` derives the CAS "Inzwischen geändert" table
# from it, so a dropped `diff=` means a racing archivist is silently not told that field changed under
# them — loss-adjacent, on the surface tests/CLAUDE.md calls load-bearing. Each guard below joins the
# registry to the REAL render or the real behaviour, never to a second hand-written list.


def _card_rows(*, autofocus: str = "", errors: dict[str, str] | None = None) -> list[_CardRow]:
    """Every record-card row the registry renders, in DOM order, for a blank form."""
    from bundesarchiv.app.web.catalog_views import _card_fields

    sections = _card_fields(
        {"ulid": _ULID}, BestandChooser(lambda: ()), errors=errors or {}, autofocus=autofocus
    )
    return [row for group in sections.values() for row in group]


def test_the_card_renders_every_field_the_registry_declares(corpus: _EditCorpus) -> None:
    # The card's sections are `{% for %}` loops over `_card_fields`, so the template can no longer
    # render a field the registry does not declare — that direction is closed by construction, and the
    # HTML scanner that used to prove it went with the hand-written blocks. The open direction is a
    # section whose loop was never wired: walk the real render for each declared control.
    from bundesarchiv.app.web.catalog_views import _FIELDS

    body = client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten").content.decode()
    declared = [f.name for f in _FIELDS if f.control]
    assert len(declared) >= 13, f"the registry declares {declared} — the guard proves nothing"
    for name in declared:
        assert f'name="{name}"' in body, f"the card renders no control for {name}"


def test_only_a_focusable_field_can_carry_the_autofocus() -> None:
    # `focusable` is what `_first_error_field` scans, so a field marked focusable whose control never
    # receives `autofocus` focuses NOTHING on a validation re-render — silent, and in source it looks
    # exactly like a working one. One partial wires the attribute now, off `row.autofocus`, so the
    # relation is the registry's: every focusable field can take the caret, nothing else can.
    from bundesarchiv.app.web.catalog_views import _FIELDS

    focusable = [f.name for f in _FIELDS if f.focusable]
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
        "collection_id": PUB,
        "ref_code": "F12/3",
        "media_type": "Foto(s)",
        "document_type": "Zeitschrift",
        "tags": "sommer, fahrt",
        "date": "1962-07",
        "creator": "Kurt Meyer",
        "subject_place": "Bonn",
        "physical_location": "Regal 3",
        "body": "Ein Text.",
        "sichtbarkeit": "groups",
        "gruppen": "vorstand, archiv",
        "custom_rows": [("Fotograf", "Meyer")],
        "is_draft": True,
    }


def test_every_card_field_echoes_the_post_verbatim() -> None:
    # The re-render echo: a field the echo forgets comes back BLANK, and the archivist's next save
    # writes that blank over the stored value. Data loss, so the whole table is walked, not sampled.
    from bundesarchiv.app.web.catalog_views import _FIELDS, _post_to_form_values

    typed = {f.name: f"getippt {f.name}" for f in _FIELDS if f.control}
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
    assert [(r.label, r.mine, r.theirs) for r in audience] == [
        ("Sichtbarkeit", "Öffentlich", "Alle Mitglieder")
    ]
    state = _conflict_rows(
        make_article(_ULID, lifecycle=Lifecycle.DRAFT),
        make_article(_ULID, lifecycle=Lifecycle.PUBLISHED),
    )
    assert [(r.label, r.mine, r.theirs) for r in state] == [("Status", "Entwurf", "Veröffentlicht")]


def test_scanned_is_the_focusable_spine_minus_the_one_declared_exception() -> None:
    # `scanned` is the GET autofocus spine: the fields walked for the first EMPTY one. It is the
    # focusable set minus exactly ONE declared exception — Gruppen, which is empty on almost every
    # record by design (it means something only at the GROUPS rung), so scanning it would park the
    # caret there on every fully catalogued record and pop the Zugriff fold open with it. Pinning the
    # relation rather than the membership means a dropped `scanned=True` fails here, and a SECOND
    # exception has to be argued for rather than typed.
    from bundesarchiv.app.web.catalog_views import _FIELDS

    scanned = {f.name for f in _FIELDS if f.scanned}
    focusable = {f.name for f in _FIELDS if f.focusable}
    assert scanned == focusable - {"gruppen"}, f"spine {sorted(scanned)} vs {sorted(focusable)}"


def test_every_scanned_field_is_reachable_as_the_first_empty_one() -> None:
    # ...and the spine BEHAVES: for each scanned field, a record whose earlier spine fields are all
    # filled and this one empty must autofocus exactly it. A walker over the spine, so a field dropped
    # from it (or reordered out of DOM order) is caught for every field, not just for `creator` — the
    # one instance an existing e2e journey happens to pin.
    from bundesarchiv.app.web.catalog_views import _FIELDS, _first_empty_field

    spine = [f.name for f in _FIELDS if f.scanned]
    assert len(spine) >= 8, f"the spine is {spine} — the walk proves nothing"
    for name in spine:
        values: dict[str, object] = {f: "gefüllt" for f in spine if f != name}
        assert _first_empty_field(values) == name, (
            f"with only {name} empty the autofocus went to {_first_empty_field(values)}"
        )


class _RequiredScanner(HTMLParser):
    """The names of the controls a render announces as required."""

    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("aria-required") == "true" and values.get("name"):
            self.names.add(str(values["name"]))


def test_the_card_marks_required_exactly_the_fields_the_save_rejects_blank(
    corpus: _EditCorpus,
) -> None:
    # The "*" is a promise about the save: a field it marks must be refused blank, and a field the
    # save refuses blank must carry it. Both sides are read back: the markers from the render, the
    # refusals from the parse.
    from bundesarchiv.app.web import catalog
    from bundesarchiv.app.web.catalog_views import _FIELDS

    scanner = _RequiredScanner()
    scanner.feed(client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten").content.decode())
    chooser = BestandChooser(lambda: (make_collection("PUB"),))
    refused = {
        registered.name
        for registered in _FIELDS
        if registered.control
        and registered.name
        in catalog.parse_edit_form(
            {**_valid_post(corpus), registered.name: ""}, ulid=_ULID, bestand=chooser, added_at=None
        ).errors
    }
    assert refused, "no field is refused blank — the guard proves nothing"
    assert scanner.names == refused


#: Every row the CAS "Inzwischen geändert" table shows when all of them changed, in the order it shows
#: them — the archivist's contract on the loss-adjacent surface, so it is pinned VERBATIM rather than
#: derived from the registry it guards (an expectation read off `_FIELDS` moves with a dropped `diff=`
#: and asserts nothing: dropping `diff="Ort"` was green against it).
#: Bestand is deliberately absent: a diff of collection MOVES is its own surface, not this one.
_CAS_DIFF_ROWS = (
    "Titel",
    "Signatur",
    "Medienart",
    "Dokumenttyp",
    "Schlagworte",
    "Datierung",
    "Autor",
    "Ort",
    "Standort",
    "Beschreibung",
    "Sichtbarkeit",
    "Status",
)


def test_the_cas_diff_lists_every_registry_field_that_changed(corpus: _EditCorpus) -> None:
    # `diff` drives the "Inzwischen geändert" table, and a dropped label means a racing archivist is
    # silently not told that field changed under them. Force a conflict in which EVERY diffable field
    # differs and compare the table against the pinned row list — so a dropped `diff=`, a reordered
    # registry and a label the table cannot render all fail here.
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
    winner = archivist.post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, **changed))
    assert winner.status_code == 302
    # The loser submits the ORIGINAL values at the now-stale version, so every field differs — and
    # publishes, which is the only way to make the STATUS row differ too (the loser's own lifecycle
    # is otherwise read from the article on disk, i.e. the winner's).
    loser = archivist.post(
        f"/artikel/{_ULID}/bearbeiten",
        _valid_post(corpus, lebenszyklus="veroeffentlichen"),
    )
    assert loser.status_code == 200
    rows = _diff_labels(loser.content.decode())
    assert rows == list(_CAS_DIFF_ROWS), f"the CAS diff listed {rows}, not {list(_CAS_DIFF_ROWS)}"


class _DiffLabelScanner(HTMLParser):
    """The first ``<td>`` of every row of the conflict panel's diff table — the German field labels, in
    render order (the registry's own field order, which the table must not reshuffle)."""

    def __init__(self) -> None:
        super().__init__()
        self.labels: list[str] = []
        self._in_diff = False
        self._cell = 0
        self._capture = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if "diff" in (values.get("class") or "").split():
            self._in_diff = True
        elif tag == "tr" and self._in_diff:
            self._cell = 0
        elif tag == "td" and self._in_diff:
            self._cell += 1
            self._capture = self._cell == 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._capture = False
        elif tag == "div" and self._in_diff:
            self._in_diff = False

    def handle_data(self, data: str) -> None:
        if self._capture and data.strip():
            self.labels.append(data.strip())


def _diff_labels(body: str) -> list[str]:
    scanner = _DiffLabelScanner()
    scanner.feed(body)
    return scanner.labels


def test_error_inside_a_folded_section_renders_it_open(corpus: _EditCorpus) -> None:
    # Sichtbarkeit=Gruppe(n) with an empty Gruppen field: the message and the errored input both live
    # in the folded Zugriff section. Folded, the archivist saw a form that simply refused to save.
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, sichtbarkeit="groups", gruppen="")
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Bitte mindestens eine Gruppe angeben." in body
    assert _fold(body, "Zugriff").is_open, "the errored Zugriff section rendered folded"
    assert not _fold(body, "Herkunft").is_open  # the clean folds stay folded (ruling 4)


def test_custom_bag_error_renders_the_bag_open(corpus: _EditCorpus) -> None:
    # errors.custom is the same class: it renders as a <p class="error"> inside #custom-bag.
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
        {**_valid_post(corpus), "custom_key": ["title"], "custom_value": ["gekapert"]},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Bezeichnung ist reserviert." in body
    assert _fold(body, "Weitere Angaben").is_open, "the errored custom bag rendered folded"


def test_autofocus_target_inside_a_folded_section_renders_it_open(corpus: _EditCorpus) -> None:
    # The GET autofocus scans the cataloguing spine for the first EMPTY field, and three of its
    # fields (Autor, Ort, Standort) sit
    # behind the Herkunft fold — so on a record whose earlier fields are all filled the autofocus
    # landed on an input inside a closed <details>, focusing nothing at all.
    filled = "01KX7YT9E3VX0CP3A5Q49RZMWQ"
    corpus.add_article(
        make_article(
            filled,
            collection_id="PUB",
            lifecycle=Lifecycle.DRAFT,
            title="Vollständig",
            ref_code="F1",
            media_type="Foto(s)",
            document_type="Positiv",
            tags=("sommer",),
            date=EdtfDate("1962"),
        )
    )
    body = client_as(Archivist()).get(f"/artikel/{filled}/bearbeiten").content.decode()
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


def test_publish_from_the_edit_screen_saves_the_form_first(corpus: _EditCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
        {
            **_valid_post(corpus, title="Frisch getippt", creator="Kurt Meyer"),
            "lebenszyklus": "veroeffentlichen",
        },
    )
    assert response.status_code == 302
    assert response["Location"] == f"/artikel/{_ULID}"  # same destination as a plain save
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Frisch getippt"  # the edit was NOT discarded
    assert stored.article.creator == "Kurt Meyer"
    assert stored.article.lifecycle is Lifecycle.PUBLISHED
    assert stored.version == corpus.version + 1  # ONE write, not save-then-publish


def test_withdraw_from_the_edit_screen_saves_the_form_first(corpus: _EditCorpus) -> None:
    published = "01KX7YT9E3VX0CP3A5Q49RZMWR"
    version = corpus.add_article(
        make_article(
            published,
            collection_id="PUB",
            lifecycle=Lifecycle.PUBLISHED,
            title="Veröffentlicht",
        )
    )
    response = client_as(Archivist()).post(
        f"/artikel/{published}/bearbeiten",
        {
            **_valid_post(corpus, title="Doch noch Entwurf", expected_version=str(version)),
            "lebenszyklus": "zurueckziehen",
        },
    )
    assert response.status_code == 302
    stored = corpus.articles.load(published)
    assert stored.article.title == "Doch noch Entwurf"
    assert stored.article.lifecycle is Lifecycle.DRAFT


def test_publish_with_an_invalid_form_publishes_nothing(corpus: _EditCorpus) -> None:
    # A validation failure must behave EXACTLY like a failed save: re-render, values preserved,
    # nothing published. It does by construction — the parse runs before any save.
    response = client_as(Archivist()).post(
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
    stored = corpus.articles.load(_ULID)
    assert stored.article.lifecycle is Lifecycle.DRAFT  # nothing published
    assert stored.version == corpus.version  # nothing saved either


def test_publish_on_a_stale_version_behaves_like_a_save_conflict(corpus: _EditCorpus) -> None:
    archivist = client_as(Archivist())
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
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Gewinner"
    assert stored.article.lifecycle is Lifecycle.DRAFT  # the lost race published nothing


def test_unknown_lifecycle_verb_on_the_edit_post_is_404_without_saving(corpus: _EditCorpus) -> None:
    # Same rule as the standalone lifecycle route: never mutate on a bad verb — and here that means
    # the SAVE does not happen either.
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
        {**_valid_post(corpus, title="Gekapert"), "lebenszyklus": "sabotage"},
    )
    assert_denied(response)
    stored = corpus.articles.load(_ULID)
    assert stored.article.title == "Wanderfahrt 1962"
    assert stored.version == corpus.version


# --- the reader's sheet on a RE-RENDER ---------------------------------------------


def _lesesicht(body: str) -> str:
    """The reader's-sheet region of a rendered edit form: ``<aside id="lesesicht">`` to its close."""
    start = body.index('id="lesesicht"')
    return body[body.rindex("<aside", 0, start) : body.index("</aside>", start)]


def test_every_re_render_shows_the_saved_record_in_the_readers_sheet(
    corpus: _EditCorpus,
) -> None:
    """A box labelled „Leseansicht“ shows the record as SAVED on every state, never the keystrokes."""
    # It carries the exposure statement (owner ruling 5), so keystrokes in it would answer "who sees
    # this?" about a record that does not exist yet. The three states that re-seed the form from the
    # POST are the ones where the two can diverge; each used to argue it separately at its own call
    # site, and the GET-only sheet tests (test_catalog_actions) could not see any of them.
    archivist = client_as(Archivist())
    typed = "Nur getippt, nie gespeichert"

    invalid = archivist.post(
        f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title=typed, media_type="")
    ).content.decode()
    removed = archivist.post(
        f"/artikel/{_ULID}/bearbeiten",
        {
            **_valid_post(corpus, title=typed),
            "custom_key": "Fotograf",
            "custom_value": "Meyer",
            "custom_entfernen": "0",
        },
    ).content.decode()
    archivist.post(f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title="Gewinner"))
    raced = archivist.post(
        f"/artikel/{_ULID}/bearbeiten", _valid_post(corpus, title=typed)
    ).content.decode()

    for state, body, saved in (
        ("Validierungsfehler", invalid, "Wanderfahrt 1962"),
        ("Zeile entfernt", removed, "Wanderfahrt 1962"),
        ("Konflikt", raced, "Gewinner"),
    ):
        assert f'value="{typed}"' in body, f"{state}: the card lost the archivist's input"
        sheet = _lesesicht(body)
        assert typed not in sheet, f"{state}: the sheet shows unsaved keystrokes"
        assert saved in sheet, f"{state}: the sheet does not show the saved record"
