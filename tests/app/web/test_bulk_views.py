"""Bulk-edit confirm + commit route (Sammelbearbeitung, spec §2/§4/§6).

POST /artikel/sammelbearbeitung: archivist-gated, POST-only. Phase 1 (no bestaetigt) → confirm page;
phase 2 (bestaetigt=1) → apply + result page. The deny suite (spec §6) is the load-bearing part
(mutation-tested): non-archivist → 404 with ZERO writes; GET → 404; feld allowlist;
dependent-pair server-enforced; orphan dokumenttyp_leeren server-enforced. The write path is real;
only index + queue seams are stubbed (conftest.py).
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from django.urls import reverse
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as, make_article, make_collection, page_hrefs

from bundesarchiv.app.web import browse, bulk
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

_A = "01KX7YT9E3VX0CP3A5Q49RZM01"
_B = "01KX7YT9E3VX0CP3A5Q49RZM02"


@pytest.fixture
def two_drafts(make_corpus: Callable[[], Corpus]) -> Corpus:
    """Two DRAFT photos in PUB, plus a second Bestand. Bulk edit needs a multi-article selection
    whose editable fields all start out empty, and a Bestand choice set with more than one entry."""
    corpus = make_corpus()
    corpus.add_collection(
        make_collection("PUB", "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    corpus.add_collection(make_collection("ARCH", "Archiv", audience=Audience(AudienceTier.PUBLIC)))
    corpus.add_article(
        make_article(_A, collection_id="PUB", lifecycle=Lifecycle.DRAFT, title="Foto A")
    )
    corpus.add_article(
        make_article(_B, collection_id="PUB", lifecycle=Lifecycle.DRAFT, title="Foto B")
    )
    return corpus


def _stored(corpus: Corpus, ulid: str) -> Article:
    """The article as it is on disk right now — the oracle every zero-writes assert reads."""
    return corpus.articles.load(ulid).article


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- deny suite (spec §6) — ZERO writes on every deny ------------------------------


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_bulk_denied_is_404_and_writes_nothing(two_drafts: Corpus, viewer: Viewer) -> None:
    response = client_as(viewer).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [_A, _B], "feld": "creator", "wert_text": "Gekapert", "bestaetigt": "1"},
    )
    assert_denied(response)
    # nothing mutated
    assert _stored(two_drafts, _A).creator is None
    assert _stored(two_drafts, _B).creator is None


def test_bulk_get_is_404(two_drafts: Corpus) -> None:
    assert_denied(client_as(Archivist()).get("/artikel/sammelbearbeitung"))


@pytest.mark.parametrize(
    "feld", ["lifecycle", "audience", "ulid", "__class__", "sichtbarkeit", "added_at"]
)
def test_forbidden_feld_writes_nothing(two_drafts: Corpus, feld: str) -> None:
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [_A], "feld": feld, "wert_text": "x", "bestaetigt": "1"},
    )
    assert response.status_code == 200  # re-renders the confirm frame with the field error
    assert "Bitte ein Feld wählen." in response.content.decode()
    # the article is untouched (lifecycle/audience never bulk-editable)
    assert _stored(two_drafts, _A).lifecycle is Lifecycle.DRAFT


def test_validation_error_re_renders_drawer_with_selection_preserved(two_drafts: Corpus) -> None:
    # Design-gate blocker: a validation error must NOT dead-end and drop the selection (spec §2 C).
    # It re-renders the chooser drawer + the verbatim error, carrying every auswahl ulid as a hidden
    # input so the archivist fixes the value and re-submits from here — selection intact.
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [_A, _B], "feld": "", "wert_text": "x", "bestaetigt": "1"},
    )
    body = response.content.decode()
    assert "Bitte ein Feld wählen." in body  # verbatim error
    assert 'name="feld"' in body  # the drawer is re-rendered
    assert 'name="wert_text"' in body  # the value widgets are present
    # both selected ulids survive as hidden inputs (no dead-end, no dropped selection)
    assert f'name="auswahl" value="{_A}"' in body
    assert f'name="auswahl" value="{_B}"' in body


#: One submittable value per value-input widget. A <select> only echoes an option it actually
#: renders, so these are real vocabulary values / a real Bestand ulid from ``two_drafts``. A new
#: ``BulkField.value_input`` fails the echo test here until it names its value.
_ECHOED_VALUE = {
    "wert_text": "Quisenberry-Zephyroth",
    "wert_media_type": "Foto(s)",
    "wert_document_type": "Zeitschrift",
    "wert_collection_id": "ARCH",
}


@pytest.mark.parametrize("feld", [f.target for f in bulk.FIELDS])
def test_every_field_echoes_its_rejected_value(two_drafts: Corpus, feld: str) -> None:
    # Values-preserved-verbatim (spec §2 C) for EVERY bulk field: the rejected submit comes back with
    # the field pre-selected and the value in that field's own widget. The empty auswahl is what
    # rejects, so the field/value pair itself is always well-formed and reaches the re-render.
    widget = bulk.value_input_of(feld)
    wert = _ECHOED_VALUE[widget]
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung", {"feld": feld, widget: wert, "bestaetigt": "1"}
    )
    body = response.content.decode()
    assert "Keine Artikel ausgewählt." in body  # verbatim error
    assert f'<option value="{feld}" selected>' in body  # the chosen Feld stays chosen
    echoed = (
        f'name="{widget}" value="{wert}"'
        if widget == "wert_text"
        else f'<option value="{wert}" selected>'
    )
    assert echoed in body


def test_every_bulk_field_has_exactly_one_value_widget(two_drafts: Corpus) -> None:
    # data-bulk-wert is what layouts.css matches to reveal a widget; hand-typed, it went stale in
    # silence — a new bulk field would offer no way to enter its value. Parsed back out of the
    # rendered chooser: every target from bulk.FIELDS, on exactly one widget, and nothing else.
    body = (
        client_as(Archivist())
        .post(
            "/artikel/sammelbearbeitung", {"feld": "creator", "wert_text": "x", "bestaetigt": "1"}
        )
        .content.decode()
    )
    tokens = [t for attr in re.findall(r'data-bulk-wert="([^"]*)"', body) for t in attr.split()]
    assert sorted(tokens) == sorted(f.target for f in bulk.FIELDS)


def test_placeholder_feld_re_render_preserves_the_typed_value(two_drafts: Corpus) -> None:
    # The commonest slip — value typed, Feld left on "— Feld wählen —" — must be re-echoed like any
    # other rejected submit (spec §2 C: values preserved verbatim), not silently blanked.
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [_A], "feld": "", "wert_text": "Quisenberry-Zephyroth", "bestaetigt": "1"},
    )
    body = response.content.decode()
    assert "Bitte ein Feld wählen." in body
    assert 'name="wert_text" value="Quisenberry-Zephyroth"' in body


def test_collection_value_outside_set_same_as_empty(two_drafts: Corpus) -> None:
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {
            "auswahl": [_A],
            "feld": "collection_id",
            "wert_collection_id": "NOPE",
            "bestaetigt": "1",
        },
    )
    assert "Bitte einen Bestand wählen." in response.content.decode()
    assert _stored(two_drafts, _A).collection_id == "PUB"  # unchanged


# --- confirm phase (no bestaetigt) -------------------------------------------------


@pytest.mark.parametrize("feld", ["creator", ""])
def test_the_check_page_leads_back_to_the_selection(two_drafts: Corpus, feld: str) -> None:
    # both modes (the check, and a refusal): the way back is the list with the selection kept
    body = (
        client_as(Archivist())
        .post("/artikel/sammelbearbeitung", {"auswahl": [_A, _B], "feld": feld, "wert_text": "X"})
        .content.decode()
    )
    back = f"{reverse('workbench')}?{browse.select_page_query({}, [_A, _B], [])}"
    assert back in page_hrefs(body)


def test_the_check_page_shows_the_new_value_and_writes_nothing(two_drafts: Corpus) -> None:
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [_A, _B], "feld": "creator", "wert_text": "K. Meyer"},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "K. Meyer" in body
    assert "Foto A" in body and "Foto B" in body
    assert _stored(two_drafts, _A).creator is None


@pytest.mark.parametrize(
    ("feld", "widget", "wert", "bisher", "saved_as"),
    [
        ("creator", "wert_text", "Neu", "Alt-Autor", {"creator": "Alt-Autor"}),
        ("Quelle", "wert_text", "Neu", "Alt-Quelle", {"custom": (("Quelle", "Alt-Quelle"),)}),
        ("collection_id", "wert_collection_id", "ARCH", "Öffentlich", {}),
    ],
)
def test_the_check_page_shows_each_value_it_replaces(
    two_drafts: Corpus, feld: str, widget: str, wert: str, bisher: str, saved_as: dict[str, object]
) -> None:
    # the value a record loses reaches the page before the commit; a Bestand by its name
    two_drafts.articles.save(
        make_article(
            _A, collection_id="PUB", lifecycle=Lifecycle.DRAFT, title="Foto A", **saved_as
        ),
        two_drafts.articles.load(_A).version,
        changed_by="tester",
    )
    body = (
        client_as(Archivist())
        .post("/artikel/sammelbearbeitung", {"auswahl": [_A], "feld": feld, widget: wert})
        .content.decode()
    )
    assert bisher in body.split("<main", 1)[1]  # the header's panels list every Bestand


# --- commit phase (bestaetigt=1) ---------------------------------------------------


def test_commit_applies_and_shows_result(two_drafts: Corpus) -> None:
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [_A, _B], "feld": "creator", "wert_text": "K. Meyer", "bestaetigt": "1"},
    )
    assert response.status_code == 200
    assert _stored(two_drafts, _A).creator == "K. Meyer"
    assert _stored(two_drafts, _B).creator == "K. Meyer"


def test_the_ticked_head_box_selects_every_row_of_its_page(two_drafts: Corpus) -> None:
    # without JS the ledger's head box carries the rows of the page it sat on; ticked, they join the
    # rows ticked one by one (here: none)
    client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"alle": f"{_A} {_B}", "feld": "creator", "wert_text": "K. Meyer", "bestaetigt": "1"},
    )
    assert _stored(two_drafts, _A).creator == "K. Meyer"
    assert _stored(two_drafts, _B).creator == "K. Meyer"


def test_commit_keeps_the_date_added(two_drafts: Corpus) -> None:
    added_at = datetime(2017, 6, 26, 6, 6, 40, tzinfo=UTC)
    ulid = "01KX7YT9E3VX0CP3A5Q49RZM03"
    two_drafts.add_article(make_article(ulid, collection_id="PUB", added_at=added_at))
    client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [ulid], "feld": "creator", "wert_text": "K. Meyer", "bestaetigt": "1"},
    )
    stored = _stored(two_drafts, ulid)
    assert (stored.creator, stored.added_at) == ("K. Meyer", added_at)


def test_commit_cas_race_loser_value_not_on_disk(
    two_drafts: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CAS honesty (spec §6.7): a bulk apply that loses the race on _A must report _A conflicted and
    # leave _A's value NOT on disk, while _B still saves. Force save_article to conflict for _A.
    from bundesarchiv.app import articles

    real_save = articles.save_article

    def _conflict_a(store_: object, article: Article, version: int, *, changed_by: str) -> object:
        from bundesarchiv.persistence.errors import Conflict

        if article.ulid == _A:
            raise Conflict("raced")
        return real_save(store_, article, version, changed_by=changed_by)  # type: ignore[arg-type]

    monkeypatch.setattr(articles, "save_article", _conflict_a)
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [_A, _B], "feld": "creator", "wert_text": "Bulk", "bestaetigt": "1"},
    )
    # the loser is listed, leading to its edit form, and all losers can be picked again at once
    hrefs = page_hrefs(response.content.decode())
    assert reverse("artikel-bearbeiten", args=[_A]) in hrefs
    assert f"{reverse('workbench')}?{browse.select_page_query({}, [], [_A])}" in hrefs
    assert reverse("artikel-bearbeiten", args=[_B]) not in hrefs
    assert _stored(two_drafts, _A).creator is None  # loser value NOT on disk
    assert _stored(two_drafts, _B).creator == "Bulk"  # winner stands


def test_commit_custom_bag_upsert(two_drafts: Corpus) -> None:
    client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {"auswahl": [_A], "feld": "Quelle", "wert_text": "Nachlass", "bestaetigt": "1"},
    )
    assert dict(_stored(two_drafts, _A).custom)["Quelle"] == "Nachlass"


def test_commit_missing_ulid_bucketed(two_drafts: Corpus) -> None:
    gone = "01KX7YT9E3VX0CP3A5Q49RZMZZ"
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {
            "auswahl": [_A, gone],
            "feld": "creator",
            "wert_text": "X",
            "bestaetigt": "1",
        },
    )
    assert _stored(two_drafts, _A).creator == "X"
    assert gone not in response.content.decode()  # an internal id means nothing to an archivist


# --- dependent pair (spec §3) ------------------------------------------------------


def test_document_type_mismatch_rejects_whole_apply(two_drafts: Corpus) -> None:
    # _A has no media_type, and no Dokumenttyp belongs to a missing Medienart → the whole apply
    # is rejected, zero writes (all-or-nothing, fail-closed).
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {
            "auswahl": [_A],
            "feld": "document_type",
            "wert_document_type": "Zeitschrift",
            "bestaetigt": "1",
        },
    )
    body = response.content.decode()
    assert "gehört nicht zur Medienart aller ausgewählten Artikel" in body
    assert _stored(two_drafts, _A).document_type is None  # unchanged


def _give_a_schriftgut_brief_pair(corpus: Corpus) -> None:
    """Re-save _A with a Schrifttum + Brief pair — "Brief" is not in the vocabulary the archivists
    own, so any Medienart switch orphans it."""
    corpus.articles.save(
        make_article(
            _A,
            collection_id="PUB",
            lifecycle=Lifecycle.DRAFT,
            title="Foto A",
            media_type="Schrifttum",
            document_type="Brief",
        ),
        corpus.articles.load(_A).version,
        changed_by="tester",
    )


def test_media_type_orphan_requires_leeren_flag(two_drafts: Corpus) -> None:
    # A commit WITHOUT dokumenttyp_leeren must NOT write — it re-confirms (server-enforced, spec §3).
    _give_a_schriftgut_brief_pair(two_drafts)
    response = client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {
            "auswahl": [_A],
            "feld": "media_type",
            "wert_media_type": "Foto(s)",
            "bestaetigt": "1",
        },
    )
    body = response.content.decode()
    # re-confirmed: the Dokumenttyp it clears is shown, and the commit now carries the flag
    assert "Brief" in body
    assert 'name="dokumenttyp_leeren" value="1"' in body
    assert _stored(two_drafts, _A).media_type == "Schrifttum"  # NOT written without the flag


def test_media_type_orphan_commits_with_leeren_flag(two_drafts: Corpus) -> None:
    _give_a_schriftgut_brief_pair(two_drafts)
    client_as(Archivist()).post(
        "/artikel/sammelbearbeitung",
        {
            "auswahl": [_A],
            "feld": "media_type",
            "wert_media_type": "Foto(s)",
            "bestaetigt": "1",
            "dokumenttyp_leeren": "1",
        },
    )
    got = _stored(two_drafts, _A)
    assert got.media_type == "Foto(s)"
    assert got.document_type is None  # orphan cleared


# --- dokumenttypen endpoint (ulid-free) --------------------------------------------


def test_bulk_dokumenttypen_archivist(two_drafts: Corpus) -> None:
    response = client_as(Archivist()).get(
        "/artikel/sammelbearbeitung/dokumenttypen?media_type=Foto(s)"
    )
    assert response.status_code == 200
    assert "Zeitschrift" in response.content.decode()


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_bulk_dokumenttypen_denied_never_content(two_drafts: Corpus, viewer: Viewer) -> None:
    response = client_as(viewer).get("/artikel/sammelbearbeitung/dokumenttypen?media_type=Foto(s)")
    assert_denied(response)
    assert b"Zeitschrift" not in response.content


def test_bulk_dokumenttypen_post_is_404(two_drafts: Corpus) -> None:
    assert (
        client_as(Archivist())
        .post("/artikel/sammelbearbeitung/dokumenttypen", {"media_type": "Foto(s)"})
        .status_code
        == 404
    )
