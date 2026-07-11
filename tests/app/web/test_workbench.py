"""The archivist workbench route (Part 4.5-MVP) — DB-backed, viewer-scoped search UI.

Every case drives the real route through Django's test ``Client`` with a dev-viewer cookie, over a
LocalFs-backed corpus that is BOTH indexed (so ``search`` sees it) and readable by the view's
collection-name resolution (same store). The security spine: results are viewer-scoped by ``search``
— an Archivist sees drafts in the results, a Public viewer never does (the Part-4 leak discipline,
carried into the UI).

These need Postgres (they call ``search``); the ``corpus`` fixture indexes once per module and wipes
on teardown (the shared ``indexed_corpus`` isolation mechanism).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from django.core import signing
from django.http import HttpResponse
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-workbench-dev-key"

# Valid ULIDs for the preview-pane articles (the pane resolves via is_valid_ulid, which the corpus's
# mnemonic ids like "PUBFOTO" fail). PANE_PUB is public; PANE_MEM is members-only + floored fields.
PANE_PUB_ULID = "01KX6RHVHG90WHP1PZWP0GSKQQ"
PANE_MEM_ULID = "01KX6RHVHG90WHP1PZWP0GSKQR"
# A valid ULID that is NOT in the corpus — the "absent" pane case (must be byte-identical to denied).
PANE_ABSENT_ULID = "01KX6RHVHG90WHP1PZWP0GSKZZ"


class _Corpus:
    """A LocalFs archive indexed for the workbench tests: a small tiered tree with dates, one
    dateless article, a prefix-recall title, and a draft (archivist-only)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        self._build()
        indexer.rebuild(self.store)

    def _build(self) -> None:
        collections = CollectionRepository(self.store)
        articles = ArticleRepository(self.store)
        collections.save(Collection("ROOT", "Bundesarchiv", None), 0)
        collections.save(
            Collection("FOTOS", "Fotografien", "ROOT", Audience(AudienceTier.PUBLIC)), 0
        )
        collections.save(
            Collection("AKTEN", "Aktenbestand", "ROOT", Audience(AudienceTier.MEMBERS)), 0
        )
        specs = [
            # ulid, title, coll, lifecycle, ref_code, media, doc, tags, date
            (
                "PUBFOTO",
                "Öffentliches Foto der Fahrten",
                "FOTOS",
                Lifecycle.PUBLISHED,
                "B 2",
                "Foto",
                "Fotografie",
                ("fahrten",),
                EdtfDate("1965"),
            ),
            (
                "PUBBERICHT",
                "Fahrtenbericht vom Bundeslager",
                "FOTOS",
                Lifecycle.PUBLISHED,
                "B 3",
                "Foto",
                "Bericht",
                ("lager",),
                EdtfDate("1972"),
            ),
            (
                "PUBUNDATIERT",
                "Undatiertes Liederheft",
                "FOTOS",
                Lifecycle.PUBLISHED,
                "B 4",
                "Schrifttum",
                "Liederheft",
                ("lieder",),
                None,
            ),
            (
                "MEMAKTE",
                "Vertrauliche Mitgliederakte",
                "AKTEN",
                Lifecycle.PUBLISHED,
                "A 5",
                "Akte",
                "Schriftstück",
                ("mitglieder",),
                EdtfDate("1975"),
            ),
            (
                "DRAFT",
                "Entwurf einer Chronik",
                "FOTOS",
                Lifecycle.DRAFT,
                "D 1",
                "Akte",
                "Chronik",
                ("entwurf",),
                EdtfDate("2010"),
            ),
            # Realistic LONG Signaturen — the SIG column must size to content, never truncate these.
            (
                "LONGSIG1",
                "Fahrtenmappe mit Unterakte",
                "FOTOS",
                Lifecycle.PUBLISHED,
                "F 12/3-b",
                "Foto",
                "Fotografie",
                ("fahrten",),
                EdtfDate("1968"),
            ),
            (
                "LONGSIG2",
                "Historischer Bestand 1848",
                "FOTOS",
                Lifecycle.PUBLISHED,
                "BA 1848/II",
                "Druck",
                "Druck",
                ("historisch",),
                EdtfDate("1848"),
            ),
        ]
        for ulid, title, coll, lifecycle, ref, media, doc, tags, date in specs:
            articles.save(
                Article(
                    ulid=ulid,
                    title=title,
                    collection_id=coll,
                    lifecycle=lifecycle,
                    ref_code=ref,
                    media_type=media,
                    document_type=doc,
                    tags=tags,
                    date=date,
                ),
                0,
            )
        # A GROUPS-tier article carrying the floored fields (physical_location + custom) and a
        # named group — the chrome/leak tests probe it: its "Gruppe: vorstand" Sichtbarkeit string
        # and its Geheimregal/Herkunft floored values must never reach a non-archivist body.
        collections.save(
            Collection(
                "VORSTAND", "Vorstandsakten", "AKTEN", Audience(AudienceTier.GROUPS, ("vorstand",))
            ),
            0,
        )
        articles.save(
            Article(
                ulid="GRPPROT",
                title="Protokoll der Vorstandssitzung",
                collection_id="VORSTAND",
                lifecycle=Lifecycle.PUBLISHED,
                ref_code="V 2",
                media_type="Akte",
                document_type="Protokoll",
                tags=("vorstand",),
                date=EdtfDate("1995"),
                physical_location="Geheimregal 7",
                custom=(("herkunft", "Nachlass Schmidt"),),
            ),
            0,
        )
        # Two articles with VALID ULIDs so the preview pane (resolve_visible_article -> is_valid_ulid)
        # can open them. PANE_PUB is public (pane opens for everyone) and carries a captioned media
        # file; PANE_MEM is members-only with the floored fields (pane denied for public -> the
        # workbench renders byte-identically to no ?artikel; floored fields never in a member body).
        pub_ref = articles.add_media(
            PANE_PUB_ULID, "titel.jpg", b"pane-cover-bytes", "image/jpeg", "Titelaufnahme der Fahrt"
        )
        articles.save(
            Article(
                ulid=PANE_PUB_ULID,
                title="Vorschau Sommerfahrt",
                collection_id="FOTOS",
                lifecycle=Lifecycle.PUBLISHED,
                ref_code="P 1",
                media_type="Foto",
                document_type="Fotografie",
                tags=("vorschau",),
                date=EdtfDate("1962"),
                media=(pub_ref,),
            ),
            0,
        )
        articles.save(
            Article(
                ulid=PANE_MEM_ULID,
                title="Vorschau Mitgliederakte",
                collection_id="AKTEN",
                lifecycle=Lifecycle.PUBLISHED,
                ref_code="P 2",
                media_type="Akte",
                document_type="Schriftstück",
                tags=("vorschau",),
                date=EdtfDate("1977"),
                physical_location="Panzerschrank 9",
                custom=(("geheimnis", "Panzernachlass"),),
            ),
            0,
        )


@pytest.fixture(scope="module")
def _corpus_root(
    django_db_setup: None,
    django_db_blocker: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Path]:
    """Build + index the corpus once for the module (search never mutates it), wiping the index on
    teardown so the committed rows never leak into a later module."""
    from bundesarchiv.index.models import ArticleIndex

    root = tmp_path_factory.mktemp("workbench-canonical")
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _Corpus(root)
        yield root
        ArticleIndex.objects.all().delete()


@pytest.fixture
def corpus_root(_corpus_root: Path, db: None) -> Path:
    """Per-test entry: join the module corpus to the ``db`` transaction fixture."""
    return _corpus_root


def _settings(root: Path, **extra: object) -> dict[str, object]:
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(root),
        **extra,
    }


def _client_as(viewer: Viewer) -> Client:
    client = Client()
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def _get(root: Path, viewer: Viewer, query: str = "", *, hx: bool = False) -> HttpResponse:
    path = "/" + (("?" + query) if query else "")
    headers = {"HX-Request": "true"} if hx else None
    with override_settings(**_settings(root)):
        response = _client_as(viewer).get(path, headers=headers)
    return cast(HttpResponse, response)


# --- viewer scoping (the security spine) -----------------------------------------


@pytest.mark.django_db
def test_public_never_sees_draft_in_results(corpus_root: Path) -> None:
    body = _get(corpus_root, Public()).content.decode()
    assert "Öffentliches Foto" in body
    assert "Entwurf einer Chronik" not in body  # draft is archivist-only
    assert "Vertrauliche Mitgliederakte" not in body  # members-only


@pytest.mark.django_db
def test_archivist_sees_draft_in_results(corpus_root: Path) -> None:
    body = _get(corpus_root, Archivist()).content.decode()
    assert "Entwurf einer Chronik" in body
    assert "Vertrauliche Mitgliederakte" in body


@pytest.mark.django_db
def test_member_sees_members_not_draft(corpus_root: Path) -> None:
    body = _get(corpus_root, Member(groups=())).content.decode()
    assert "Vertrauliche Mitgliederakte" in body
    assert "Entwurf einer Chronik" not in body


# --- text search + ADR-0011 prefix recall ----------------------------------------


@pytest.mark.django_db
def test_prefix_recall_fahrt_finds_fahrtenbericht(corpus_root: Path) -> None:
    # "Fahrt" (compound head) must reach "Fahrtenbericht" via the :* prefix mitigation (ADR 0011).
    body = _get(corpus_root, Public(), "q=Fahrt").content.decode()
    assert "Fahrtenbericht" in body


# --- URL-as-state: no-JS full GET vs HX-Request partial --------------------------


@pytest.mark.django_db
def test_plain_get_renders_full_page(corpus_root: Path) -> None:
    response = _get(corpus_root, Public())
    body = response.content.decode()
    assert "<html" in body and "Suchen" in body  # full chrome (search form)
    assert 'id="results"' in body


@pytest.mark.django_db
def test_hx_request_renders_only_results_partial(corpus_root: Path) -> None:
    # As Archivist so the "Neuer Artikel" absence below is load-bearing (the button DOES render on
    # the Archivist's full page — its absence here proves the topbar is outside the partial).
    response = _get(corpus_root, Archivist(), "q=Foto", hx=True)
    body = response.content.decode()
    assert 'id="results"' in body  # the swap target
    assert "<html" not in body  # NOT the full page — just the region
    assert "Neuer Artikel" not in body  # topbar is outside the partial


# --- template hygiene + archivist chrome ------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "viewer",
    [Public(), Member(groups=()), Archivist()],
    ids=["public", "member", "archivist"],
)
def test_no_template_comment_syntax_leaks_into_page(corpus_root: Path, viewer: Viewer) -> None:
    # Django's hash-style template comment is SINGLE-LINE only: a multi-line one renders literally
    # into the page. Pin that no comment syntax ever reaches the body, for every tier.
    body = _get(corpus_root, viewer).content.decode()
    assert "{#" not in body


@pytest.mark.django_db
def test_neuer_artikel_chrome_only_for_archivist(corpus_root: Path) -> None:
    # The ROUTE is archivist-gated regardless; this pins the CHROME — Public/Member must not be
    # shown an admin affordance that 404s when clicked (and must not learn it exists).
    assert "Neuer Artikel" in _get(corpus_root, Archivist()).content.decode()
    assert "Neuer Artikel" not in _get(corpus_root, Public()).content.decode()
    assert "Neuer Artikel" not in _get(corpus_root, Member(groups=())).content.decode()


# --- §11 render-path leaks: floored fields + archivist chrome (the reviewer's mutation targets) --

_NON_ARCHIVIST: list[tuple[Viewer, str]] = [
    (Public(), "public"),
    (Member(groups=()), "member"),
    (Member(groups=("vorstand",)), "vorstand-member"),
]


@pytest.mark.django_db
def test_floored_fields_never_in_a_non_archivist_body(corpus_root: Path) -> None:
    # physical_location VALUE and custom KEYS/values are archivist-only (ARCHIVIST_ONLY_FIELDS);
    # they must never appear in any non-archivist rendered page, on ANY row they can otherwise see.
    for viewer, label in _NON_ARCHIVIST:
        body = _get(corpus_root, viewer).content.decode()
        assert "Geheimregal" not in body, f"[{label}] physical_location leaked"
        assert "herkunft" not in body, f"[{label}] custom key leaked"
        assert "Nachlass Schmidt" not in body, f"[{label}] custom value leaked"


@pytest.mark.django_db
def test_floored_fields_present_for_archivist_only_where_intended(corpus_root: Path) -> None:
    # The archivist reaches GRPPROT (a groups row) in results; the floored fields are NOT rendered
    # in the LEDGER either (the ledger shows only member-visible columns + visibility chrome) — the
    # floor holds even for the archivist's ledger. (Full floored content is the 4.6 detail's job.)
    body = _get(corpus_root, Archivist()).content.decode()
    assert "Protokoll der Vorstandssitzung" in body  # the row is present for the archivist
    assert "Geheimregal" not in body  # ...but its floored physical_location is not in the ledger


@pytest.mark.django_db
def test_visibility_column_and_strings_only_for_archivist(corpus_root: Path) -> None:
    # The SICHTBARKEIT column header + its strings (incl. the group name) are archivist chrome.
    arch = _get(corpus_root, Archivist()).content.decode()
    assert "Sichtbarkeit" in arch
    assert "Gruppe: vorstand" in arch  # the GROUPS row's visibility string, archivist-only
    assert "Öffentlich" in arch and "Alle Mitglieder" in arch
    for viewer, label in _NON_ARCHIVIST:
        body = _get(corpus_root, viewer).content.decode()
        assert "Sichtbarkeit" not in body, f"[{label}] SICHTBARKEIT column header leaked"
        assert "Gruppe: vorstand" not in body, f"[{label}] group-name visibility string leaked"


@pytest.mark.django_db
def test_entwurf_badge_and_bearbeiten_only_for_archivist(corpus_root: Path) -> None:
    arch = _get(corpus_root, Archivist()).content.decode()
    assert "ENTWURF" in arch or "Entwurf" in arch  # the draft badge (label text is "Entwurf")
    assert "Bearbeiten" in arch
    for viewer, label in _NON_ARCHIVIST:
        body = _get(corpus_root, viewer).content.decode()
        assert "Bearbeiten" not in body, f"[{label}] Bearbeiten action leaked"
        # The draft ROW is already scope-hidden; this pins the BADGE chrome is gone too.
        assert "c-badge--entwurf" not in body, f"[{label}] ENTWURF badge chrome leaked"


# --- facets: rendering, name resolution, Ohne Datum ------------------------------


@pytest.mark.django_db
def test_facets_render_with_headings(corpus_root: Path) -> None:
    body = _get(corpus_root, Public()).content.decode()
    for heading in ("Bestand", "Medienart", "Dokumenttyp", "Schlagworte", "Jahrzehnte"):
        assert heading in body


@pytest.mark.django_db
def test_collection_facet_shows_name_and_no_direkt_label(corpus_root: Path) -> None:
    body = _get(corpus_root, Public()).content.decode()
    assert "Fotografien" in body  # ULID resolved to the Collection NAME (the visible label)
    # The ULID rides in the facet link href (URL-as-state), but the ANCHOR TEXT is the name, not the
    # ULID — the raw ULID never shows as the clickable label.
    assert ">FOTOS</a>" not in body
    assert "direkt:" not in body  # the "direkt:" hedge is gone — counts are subtree counts now


@pytest.mark.django_db
def test_ohne_datum_bucket_present_and_counts(corpus_root: Path) -> None:
    body = _get(corpus_root, Public()).content.decode()
    assert "Ohne Datum" in body  # the dateless bucket (Undatiertes Liederheft has no date)


@pytest.mark.django_db
def test_ohne_datum_filter_narrows_to_dateless(corpus_root: Path) -> None:
    body = _get(corpus_root, Public(), "ohne_datum=1").content.decode()
    assert "Undatiertes Liederheft" in body
    assert "Öffentliches Foto" not in body  # a dated article is excluded


# --- facet click → filtered results + removable chip -----------------------------


@pytest.mark.django_db
def test_media_facet_filter_narrows_results(corpus_root: Path) -> None:
    body = _get(corpus_root, Public(), "medienart=Schrifttum").content.decode()
    assert "Undatiertes Liederheft" in body
    assert "Öffentliches Foto" not in body  # a Foto is excluded


@pytest.mark.django_db
def test_active_filter_removal_lives_in_the_sidebar_not_chips(corpus_root: Path) -> None:
    # The chips row died: active-filter state + removal live ONLY in the sidebar. An active facet row
    # gets the inversion marking + an inline ✕ (the remove affordance). No separate chips row.
    body = _get(corpus_root, Public(), "medienart=Foto").content.decode()
    assert "c-facet-row--aktiv" in body  # the active facet row is marked
    assert "entfernen" in body  # the ✕ remove affordance (aria-label "... entfernen")
    assert 'aria-label="Aktive Filter"' not in body  # no chips row


@pytest.mark.django_db
def test_active_date_range_removable_in_datum_group(corpus_root: Path) -> None:
    # von/bis removal moved into the DATUM group (chips are gone). An active range shows as a
    # removable row there.
    body = _get(corpus_root, Public(), "von=1960-01-01").content.decode()
    assert "von: 1960-01-01" in body  # the active bound, in the sidebar DATUM group
    assert "entfernen" in body


# --- long Signaturen: the SIG mark sizes to content, never truncates --------------


@pytest.mark.django_db
def test_long_signaturen_render_in_full(corpus_root: Path) -> None:
    # An identity mark must never truncate at realistic lengths (owner correction 3).
    body = _get(corpus_root, Public()).content.decode()
    assert "F 12/3-b" in body
    assert "BA 1848/II" in body


@pytest.mark.django_db
def test_sort_headers_cycle_asc_desc_default(corpus_root: Path) -> None:
    # The header sort cycle (the select is gone): a plain click sets ascending; the active-ascending
    # header links to descending (-signatur); the active-descending header links back to default
    # (no sortierung). Assert the link algebra the headers emit.
    asc = _get(corpus_root, Public(), "sortierung=signatur").content.decode()
    assert "sortierung=-signatur" in asc  # active-asc header now offers descending
    desc = _get(corpus_root, Public(), "sortierung=-signatur").content.decode()
    # active-desc header offers clearing the sort (default/Relevanz) — no sortierung in its href.
    assert "▼" in desc  # the descending glyph is shown on the active column
    # and there is no sort <select> anywhere (headers are the only sort control)
    assert 'name="sortierung"' not in desc


# --- param injection: garbage → 200 defaults, never 500 --------------------------


@pytest.mark.django_db
def test_garbage_params_yield_200_defaults(corpus_root: Path) -> None:
    response = _get(
        corpus_root,
        Public(),
        "jahrzehnt=abc&seite=-9&von=fruehjahr&sortierung=nonsense&ohne_datum=maybe",
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Öffentliches Foto" in body  # a normal, all-defaults result set


# --- pagination -------------------------------------------------------------------


@pytest.mark.django_db
def test_pagination_second_page_via_seite(corpus_root: Path) -> None:
    # page_size is 50 by default; force a tiny page via the URL is not supported, so assert the
    # pager is absent for a small corpus and page 1 is honest. (Pagination link algebra is unit-
    # tested in test_browse_links; here we pin that seite is honored without crashing.)
    response = _get(corpus_root, Archivist(), "seite=2")
    assert response.status_code == 200


# --- ledger row href: canonical detail baseline + pane progressive-enhancement hook -----


@pytest.mark.django_db
def test_ledger_row_href_is_the_canonical_detail_route(corpus_root: Path) -> None:
    # BASELINE (no-JS, every viewport): a row title links to /artikel/<ulid>, the canonical detail
    # route — NOT ?artikel (below 1280px the pane is CSS-hidden, so ?artikel would be a dead click).
    body = _get(corpus_root, Public(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert f'href="/artikel/{PANE_PUB_ULID}"' in body
    # ...and the enhancement hook rides alongside: ledger_pane.js upgrades the click to the pane on
    # wide viewports via this data attribute (no-JS still gets the detail link above).
    assert f'data-artikel="{PANE_PUB_ULID}"' in body
    # The old ?artikel row-href baseline is gone (it now lives only in the JS enhancement + the pane
    # close/media links, never as a row title href).
    assert f'href="?artikel={PANE_PUB_ULID}"' not in body


@pytest.mark.django_db
def test_ledger_pane_enhancement_script_is_loaded_and_served(corpus_root: Path) -> None:
    # The enhancement is a deferred static script (same mechanism as htmx); the no-JS baseline works
    # without it, so it degrades cleanly if unavailable.
    body = _get(corpus_root, Public()).content.decode()
    assert '<script src="/static/ledger_pane.js" defer></script>' in body
    with override_settings(**_settings(corpus_root)):
        served = _client_as(Public()).get("/static/ledger_pane.js")
    assert served.status_code == 200
    assert served["Content-Type"] == "application/javascript"


# --- absence renders as absence: no em-dash placeholders in the ledger ------------------


@pytest.mark.django_db
def test_absent_datierung_typ_render_nothing_not_an_em_dash(corpus_root: Path) -> None:
    # "Undatiertes Liederheft" has no date (date=None). Absence must render as ABSENCE — the old
    # `default:"—"` placeholder is gone: a dateless/typeless value renders NOTHING, so no em-dash
    # ever appears inside a ledger cell (the "—" in the <title> separator is legitimate and stays).
    body = _get(corpus_root, Public()).content.decode()
    assert "Undatiertes Liederheft" in body  # the dateless row is present
    # No em-dash as a rendered ledger cell value (the removed placeholder would show as ">—<").
    assert ">—<" not in body


# --- preview pane (?artikel): fail-closed, byte-identical, leak-safe ----------------


@pytest.mark.django_db
def test_pane_opens_for_a_viewable_article(corpus_root: Path) -> None:
    # A public article's pane opens for the public viewer: its title + Signatur + Öffnen appear, and
    # the row is marked selected.
    body = _get(corpus_root, Public(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert 'class="wb-pane"' in body
    assert "Vorschau Sommerfahrt" in body
    assert "Titelaufnahme der Fahrt" in body  # the media caption
    assert "Öffnen" in body
    assert "c-ledger-row--aktiv" in body  # the selected row is marked


@pytest.mark.django_db
def test_pane_absent_denied_malformed_are_byte_identical_to_no_pane(corpus_root: Path) -> None:
    # The existence-hiding invariant: for a viewer, a DENIED artikel (members-only, as public), an
    # ABSENT one (valid ULID not in the corpus), and a MALFORMED one all render the byte-identical
    # response as no ?artikel at all — no pane, no oracle distinguishing the three.
    base = _get(corpus_root, Public()).content
    denied = _get(corpus_root, Public(), f"artikel={PANE_MEM_ULID}").content
    absent = _get(corpus_root, Public(), f"artikel={PANE_ABSENT_ULID}").content
    malformed = _get(corpus_root, Public(), "artikel=not-a-ulid").content
    assert denied == base, "a denied artikel must be byte-identical to no pane"
    assert absent == base, "an absent artikel must be byte-identical to no pane"
    assert malformed == base, "a malformed artikel must be byte-identical to no pane"


@pytest.mark.django_db
def test_pane_denied_for_member_only_article_as_public(corpus_root: Path) -> None:
    # Public cannot open the members-only article's pane at all (no pane markup, no title, no floored
    # fields) — the deny is total.
    body = _get(corpus_root, Public(), f"artikel={PANE_MEM_ULID}").content.decode()
    assert 'class="wb-pane"' not in body
    assert "Vorschau Mitgliederakte" not in body
    assert "Panzerschrank" not in body  # floored physical_location never appears
    assert "geheimnis" not in body  # floored custom key never appears


@pytest.mark.django_db
def test_pane_floored_fields_absent_even_for_member_who_can_view(corpus_root: Path) -> None:
    # A member CAN open the members-only article's pane, but its floored fields are projected away
    # (visible() = can_view + project) — the pane view-model is built from the floored copy.
    body = _get(corpus_root, Member(groups=()), f"artikel={PANE_MEM_ULID}").content.decode()
    assert 'class="wb-pane"' in body
    assert "Vorschau Mitgliederakte" in body  # the member sees the article
    assert "Panzerschrank" not in body  # ...but never its physical_location
    assert "Panzernachlass" not in body  # ...nor its custom value
    assert "geheimnis" not in body  # ...nor its custom key


@pytest.mark.django_db
def test_pane_bearbeiten_only_for_archivist(corpus_root: Path) -> None:
    # The pane's Bearbeiten is archivist chrome; Öffnen is for everyone who can see the article.
    pub = _get(corpus_root, Public(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert "Öffnen" in pub
    assert "Bearbeiten" not in pub  # public gets no edit affordance
    arch = _get(corpus_root, Archivist(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert "Bearbeiten" in arch and "Öffnen" in arch


@pytest.mark.django_db
def test_pane_close_link_preserves_query_drops_only_artikel(corpus_root: Path) -> None:
    # The pane-close ✕ must return to the SAME search (text + facets + sort + page), dropping only
    # the pane selection (artikel). A bare href="?" would blow away the whole query — regression.
    body = _get(
        corpus_root,
        Public(),
        f"q=Vorschau&medienart=Foto&artikel={PANE_PUB_ULID}",
    ).content.decode()
    assert 'class="wb-pane"' in body  # the pane is open
    # the close link carries the active search params...
    assert "q=Vorschau" in body
    assert "medienart=Foto" in body
    # ...but never the artikel selection (it is pane state, stripped from the close href)
    close_href = body.split('class="wb-pane-schliessen" href="', 1)[1].split('"', 1)[0]
    assert "artikel" not in close_href, f"close href must drop artikel: {close_href}"
    assert "q=Vorschau" in close_href and "medienart=Foto" in close_href


@pytest.mark.django_db
def test_pane_open_folds_the_ledger_narrow(corpus_root: Path) -> None:
    # Opening the pane puts the frame in the vorschau state (the split-narrow fold is CSS-driven off
    # this body class; the <1280px query unfolds + hides the pane).
    body = _get(corpus_root, Public(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert "wb--vorschau" in body
    closed = _get(corpus_root, Public()).content.decode()
    assert "wb--vorschau" not in closed
