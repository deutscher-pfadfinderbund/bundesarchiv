"""The archivist workbench route (Part 4.5-MVP) — DB-backed, viewer-scoped search UI.

Every case drives the real route through Django's test ``Client`` with a dev-viewer cookie, over a
LocalFs-backed corpus that is BOTH indexed (so ``search`` sees it) and readable by the view's
collection-name resolution (same store). The security spine: results are viewer-scoped by ``search``
— an Archivist sees drafts in the results, a Public viewer never does (the Part-4 leak discipline,
carried into the UI).

These need Postgres (they call ``search``). The corpus is bespoke — a tiered tree, a dateless
article, Signaturen at the domain ceiling, two valid-ULID pane articles — so it is built on
``make_corpus`` rather than the frozen standard shape, and re-indexed per test inside the test's own
transaction: the rollback IS the index isolation.
"""

import re
from collections.abc import Callable
from typing import cast
from urllib.parse import quote

import pytest
from django.http import HttpResponse
from tests.app.web._fixtures import Corpus, client_as, make_article, make_collection

from bundesarchiv.app.web import browse
from bundesarchiv.app.web.browse_views import _FORM_FILTER_PARAMS
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer

# Valid ULIDs for the preview-pane articles (the pane resolves via is_valid_ulid, which the corpus's
# mnemonic ids like "PUBFOTO" fail). PANE_PUB is public; PANE_MEM is members-only + floored fields.
PANE_PUB_ULID = "01KX6RHVHG90WHP1PZWP0GSKQQ"
PANE_MEM_ULID = "01KX6RHVHG90WHP1PZWP0GSKQR"
# A valid ULID that is NOT in the corpus — the "absent" pane case (must render no pane, like denied).
PANE_ABSENT_ULID = "01KX6RHVHG90WHP1PZWP0GSKZZ"


def _fill(corpus: Corpus) -> None:
    """Fill ``corpus`` with the workbench tree: tiered collections, dates, one dateless article, a
    prefix-recall title, a draft (archivist-only), the floored-fields group row and the two
    valid-ULID pane articles."""
    corpus.add_collection(
        make_collection("FOTOS", "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    corpus.add_collection(
        make_collection("AKTEN", "Aktenbestand", audience=Audience(AudienceTier.MEMBERS))
    )
    specs = [
        # ulid, title, coll, lifecycle, ref_code, media, doc, tags, date
        (
            "PUBFOTO",
            "Öffentliches Foto der Fahrten",
            "FOTOS",
            Lifecycle.PUBLISHED,
            "B2",
            "Foto",
            "Lagerheft",
            ("fahrten",),
            EdtfDate("1965"),
        ),
        (
            "PUBBERICHT",
            "Fahrtenbericht vom Bundeslager",
            "FOTOS",
            Lifecycle.PUBLISHED,
            "B3",
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
            "B4",
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
            "A5",
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
            "D1",
            "Akte",
            "Chronik",
            ("entwurf",),
            EdtfDate("2010"),
        ),
        # Signaturen at the DOMAIN CEILING (owner 2026-08-07: no spaces, 8 characters is the
        # practical top) — the SIG column must size to content and render these in full.
        (
            "LONGSIG1",
            "Fahrtenmappe mit Unterakte",
            "FOTOS",
            Lifecycle.PUBLISHED,
            "F12/3-b",
            "Foto",
            "Lagerheft",
            ("fahrten",),
            EdtfDate("1968"),
        ),
        (
            "LONGSIG2",
            "Historischer Bestand 1848",
            "FOTOS",
            Lifecycle.PUBLISHED,
            "BA1848/2",
            "Druck",
            "Druck",
            ("historisch",),
            EdtfDate("1848"),
        ),
    ]
    for ulid, title, coll, lifecycle, ref, media, doc, tags, date in specs:
        corpus.add_article(
            make_article(
                ulid,
                collection_id=coll,
                lifecycle=lifecycle,
                title=title,
                ref_code=ref,
                media_type=media,
                document_type=doc,
                tags=tags,
                date=date,
            )
        )
    # A GROUPS-tier article carrying the floored fields (physical_location + custom) and a
    # named group — the chrome/leak tests probe it: its "Gruppe: vorstand" Sichtbarkeit string
    # and its Geheimregal/Herkunft floored values must never reach a non-archivist body.
    corpus.add_collection(
        make_collection(
            "VORSTAND", "Vorstandsakten", "AKTEN", Audience(AudienceTier.GROUPS, ("vorstand",))
        )
    )
    corpus.add_article(
        make_article(
            "GRPPROT",
            collection_id="VORSTAND",
            title="Protokoll der Vorstandssitzung",
            ref_code="V2",
            media_type="Akte",
            document_type="Protokoll",
            tags=("vorstand",),
            date=EdtfDate("1995"),
            physical_location="Geheimregal 7",
            custom=(("herkunft", "Nachlass Schmidt"),),
        )
    )
    # Two articles with VALID ULIDs so the preview pane (resolve_visible_article -> is_valid_ulid)
    # can open them. PANE_PUB is public (pane opens for everyone) and carries a captioned media
    # file; PANE_MEM is members-only with the floored fields (pane denied for public -> the
    # workbench renders no pane at all; floored fields never in a member body).
    pub_ref = corpus.articles.add_media(
        PANE_PUB_ULID, "titel.jpg", b"pane-cover-bytes", "image/jpeg", "Titelaufnahme der Fahrt"
    )
    corpus.add_article(
        make_article(
            PANE_PUB_ULID,
            collection_id="FOTOS",
            title="Vorschau Sommerfahrt",
            ref_code="P1",
            media_type="Foto",
            document_type="Lagerheft",
            tags=("vorschau",),
            date=EdtfDate("1962"),
            media=(pub_ref,),
        )
    )
    corpus.add_article(
        make_article(
            PANE_MEM_ULID,
            collection_id="AKTEN",
            title="Vorschau Mitgliederakte",
            ref_code="P2",
            media_type="Akte",
            document_type="Schriftstück",
            tags=("vorschau",),
            date=EdtfDate("1977"),
            physical_location="Panzerschrank 9",
            custom=(("geheimnis", "Panzernachlass"),),
        )
    )


@pytest.fixture
def indexed_corpus(db: None, make_corpus: Callable[[], Corpus]) -> Corpus:
    """The workbench corpus, indexed so ``search`` sees it. ``db`` comes first so the rebuild runs
    inside the test transaction — the rollback removes every ``ArticleIndex`` row it wrote, so the
    committed rows can never leak into a later module."""
    corpus = make_corpus()
    _fill(corpus)
    indexer.rebuild(corpus.store)
    return corpus


def _get(
    viewer: Viewer,
    query: str = "",
    *,
    hx: bool = False,
    history_restore: bool = False,
) -> HttpResponse:
    path = "/" + (("?" + query) if query else "")
    headers: dict[str, str] | None = None
    if hx or history_restore:
        headers = {}
        if hx:
            headers["HX-Request"] = "true"
        if history_restore:
            headers["HX-History-Restore-Request"] = "true"
    return cast(HttpResponse, client_as(viewer).get(path, headers=headers))


# --- viewer scoping (the security spine) -----------------------------------------


def test_public_never_sees_draft_in_results(indexed_corpus: Corpus) -> None:
    body = _get(Public()).content.decode()
    assert "Öffentliches Foto" in body
    assert "Entwurf einer Chronik" not in body  # draft is archivist-only
    assert "Vertrauliche Mitgliederakte" not in body  # members-only


def test_archivist_sees_draft_in_results(indexed_corpus: Corpus) -> None:
    body = _get(Archivist()).content.decode()
    assert "Entwurf einer Chronik" in body
    assert "Vertrauliche Mitgliederakte" in body


def test_member_sees_members_not_draft(indexed_corpus: Corpus) -> None:
    body = _get(Member(groups=())).content.decode()
    assert "Vertrauliche Mitgliederakte" in body
    assert "Entwurf einer Chronik" not in body


# --- text search + ADR-0011 prefix recall ----------------------------------------


def test_prefix_recall_fahrt_finds_fahrtenbericht(indexed_corpus: Corpus) -> None:
    # "Fahrt" (compound head) must reach "Fahrtenbericht" via the :* prefix mitigation (ADR 0011).
    body = _get(Public(), "q=Fahrt").content.decode()
    assert "Fahrtenbericht" in body


# --- URL-as-state: no-JS full GET vs HX-Request partial --------------------------


def test_plain_get_renders_full_page(indexed_corpus: Corpus) -> None:
    response = _get(Public())
    body = response.content.decode()
    assert "<html" in body and "Suchen" in body  # full chrome (search form)
    assert 'id="results"' in body


def test_hx_request_renders_only_results_partial(indexed_corpus: Corpus) -> None:
    # As Archivist so the "Neuer Artikel" absence below is load-bearing (the button DOES render on
    # the Archivist's full page — its absence here proves the topbar is outside the partial).
    response = _get(Archivist(), "q=Foto", hx=True)
    body = response.content.decode()
    assert 'id="results"' in body  # the swap target
    assert "<html" not in body  # NOT the full page — just the region
    assert "Neuer Artikel" not in body  # topbar is outside the partial


def test_history_restore_request_renders_full_page(indexed_corpus: Corpus) -> None:
    # htmx history restoration sends BOTH HX-Request AND HX-History-Restore-Request, and expects a
    # FULL page (it replaces the whole document) — not the chrome-less _results.html fragment a
    # plain HX-Request gets. Without the fix, this response body starts at <main id="results"> and
    # never renders <html lang="de">, leaving a Back-button restore chrome-less.
    response = _get(Public(), "q=Foto", hx=True, history_restore=True)
    body = response.content.decode()
    assert '<html lang="de">' in body  # full page, not the bare fragment
    assert not body.lstrip().startswith("<main")  # NOT the bare _results.html fragment


# --- template hygiene + archivist chrome ------------------------------------------


def test_no_template_comment_syntax_leaks_into_page(indexed_corpus: Corpus) -> None:
    # Django's hash-style template comment is SINGLE-LINE only: a multi-line one renders literally
    # into the page. Pin that no comment syntax ever reaches the body (archivist sees the most
    # template surface).
    body = _get(Archivist()).content.decode()
    assert "{#" not in body


def test_neuer_artikel_chrome_only_for_archivist(indexed_corpus: Corpus) -> None:
    # The ROUTE is archivist-gated regardless; this pins the CHROME — Public/Member must not be
    # shown an admin affordance that 404s when clicked (and must not learn it exists).
    assert "Neuer Artikel" in _get(Archivist()).content.decode()
    assert "Neuer Artikel" not in _get(Public()).content.decode()
    assert "Neuer Artikel" not in _get(Member(groups=())).content.decode()


@pytest.mark.parametrize("viewer", [Archivist(), Member(groups=())])
def test_abmelden_is_offered_to_everyone_who_is_signed_in(
    indexed_corpus: Corpus, viewer: Viewer
) -> None:
    # NOT archivist chrome: a Member's cookie lives 30 days (the longest of the two tiers), and this
    # header is the only screen they reach — gating the sign-out on is_archivist would leave them no
    # way off a shared workstation, the case ADR 0018 calls normal. The German label IS the contract.
    assert "Abmelden" in _get(viewer).content.decode()


def test_abmelden_is_not_offered_to_an_anonymous_visitor(indexed_corpus: Corpus) -> None:
    # Nothing to sign out of, and offering it would say somebody could be signed in here.
    assert "Abmelden" not in _get(Public()).content.decode()


# --- §11 render-path leaks: floored fields + archivist chrome (the reviewer's mutation targets) --

_NON_ARCHIVIST: list[tuple[Viewer, str]] = [
    (Public(), "public"),
    (Member(groups=()), "member"),
    (Member(groups=("vorstand",)), "vorstand-member"),
]


def test_floored_fields_never_in_a_non_archivist_body(indexed_corpus: Corpus) -> None:
    # physical_location VALUE and custom KEYS/values are archivist-only (ARCHIVIST_ONLY_FIELDS);
    # they must never appear in any non-archivist rendered page, on ANY row they can otherwise see.
    for viewer, label in _NON_ARCHIVIST:
        body = _get(viewer).content.decode()
        assert "Geheimregal" not in body, f"[{label}] physical_location leaked"
        assert "herkunft" not in body, f"[{label}] custom key leaked"
        assert "Nachlass Schmidt" not in body, f"[{label}] custom value leaked"


def test_floored_fields_present_for_archivist_only_where_intended(indexed_corpus: Corpus) -> None:
    # The archivist reaches GRPPROT (a groups row) in results; the floored fields are NOT rendered
    # in the LEDGER either (the ledger shows only member-visible columns + visibility chrome) — the
    # floor holds even for the archivist's ledger. (Full floored content is the 4.6 detail's job.)
    body = _get(Archivist()).content.decode()
    assert "Protokoll der Vorstandssitzung" in body  # the row is present for the archivist
    assert "Geheimregal" not in body  # ...but its floored physical_location is not in the ledger


def test_visibility_column_renders_for_nobody(indexed_corpus: Corpus) -> None:
    # The SICHTBARKEIT column died entirely (owner 2026-08-07): no header, no cells, no badges —
    # for ANY viewer. Quiet default: ÖFFENTLICH renders nothing anywhere in the ledger. The leak
    # half of the old contract still holds a fortiori: group names never reach a non-archivist.
    arch = _get(Archivist()).content.decode()
    assert "Sichtbarkeit" not in arch
    assert "Gruppe: vorstand" not in arch
    assert "Alle Mitglieder" not in arch
    # the quiet default: no ÖFFENTLICH badge string in the ledger (">Öffentlich<" as a text node;
    # the corpus title "Öffentliches Foto…" legitimately contains the bare substring)
    assert ">Öffentlich<" not in arch
    for viewer, label in _NON_ARCHIVIST:
        body = _get(viewer).content.decode()
        assert "Sichtbarkeit" not in body, f"[{label}] SICHTBARKEIT column header leaked"
        assert "Gruppe: vorstand" not in body, f"[{label}] group-name visibility string leaked"


def test_entwurf_badge_and_bearbeiten_only_for_archivist(indexed_corpus: Corpus) -> None:
    arch = _get(Archivist()).content.decode()
    assert "ENTWURF" in arch or "Entwurf" in arch  # the draft badge (label text is "Entwurf")
    assert "Bearbeiten" in arch
    for viewer, label in _NON_ARCHIVIST:
        body = _get(viewer).content.decode()
        assert "Bearbeiten" not in body, f"[{label}] Bearbeiten action leaked"
        # The draft ROW is already scope-hidden; this pins the BADGE chrome is gone too.
        assert 'class="badge entwurf"' not in body, f"[{label}] ENTWURF badge chrome leaked"


# --- facets: rendering, name resolution, Ohne Datum ------------------------------


def test_facets_render_with_headings(indexed_corpus: Corpus) -> None:
    body = _get(Public()).content.decode()
    for heading in ("Bestand", "Medienart", "Dokumenttyp", "Schlagworte", "Jahrzehnte"):
        assert heading in body


def test_ohne_datum_bucket_present_and_counts(indexed_corpus: Corpus) -> None:
    body = _get(Public()).content.decode()
    assert "Ohne Datum" in body  # the dateless bucket (Undatiertes Liederheft has no date)


def test_ohne_datum_filter_narrows_to_dateless(indexed_corpus: Corpus) -> None:
    body = _get(Public(), "ohne_datum=1").content.decode()
    assert "Undatiertes Liederheft" in body
    assert "Öffentliches Foto" not in body  # a dated article is excluded


# --- facet click → filtered results + removable chip -----------------------------


def test_media_facet_filter_narrows_results(indexed_corpus: Corpus) -> None:
    body = _get(Public(), "medienart=Schrifttum").content.decode()
    assert "Undatiertes Liederheft" in body
    assert "Öffentliches Foto" not in body  # a Foto is excluded


def test_active_filter_renders_rail_chip_with_labeled_remove(indexed_corpus: Corpus) -> None:
    # The filter rail (owner 2026-08-07: the PRIMARY filter interaction): every active filter
    # renders as a chip whose remove link carries the German accessible name — the user contract
    # (tests/CLAUDE.md: verbatim UI strings are assertable; the styling is design-gate territory).
    body = _get(Public(), "medienart=Schrifttum").content.decode()
    assert 'aria-label="Filter entfernen: Schrifttum"' in body
    # no active filter → no chip remove link at all
    bare = _get(Public()).content.decode()
    assert "Filter entfernen:" not in bare
    # ZERO-HIT filter: the value vanishes from the recomputed facet counts (no active dropdown
    # row), but the chip derives from the URL state — the empty state says "Entferne einzelne
    # Filter", so the removal affordance must survive exactly there.
    empty = _get(Public(), "medienart=Mikrofilm").content.decode()
    assert "0 Treffer" in empty
    assert 'aria-label="Filter entfernen: Mikrofilm"' in empty


def test_clear_all_link_only_with_active_filter_chips(indexed_corpus: Corpus) -> None:
    # "Alle Filter entfernen" (owner 2026-08-07, rail round 2): a quiet link at the END of the
    # chip row, present exactly when ≥1 filter chip is — its href drops every filter param but
    # keeps the text query (chip semantics: remove filters, keep q).
    body = _get(Public(), "q=Foto&medienart=Foto&schlagwort=fahrten").content.decode()
    match = re.search(r'<a href="\?([^"]*)">Alle Filter entfernen</a>', body)
    assert match is not None
    from urllib.parse import parse_qsl

    cleared = dict(parse_qsl(match.group(1)))
    assert cleared == {"q": "Foto"}
    # no active filter → no clear-all link (q alone is not a filter)
    bare = _get(Public(), "q=Foto").content.decode()
    assert "Alle Filter entfernen" not in bare


# --- search form keeps active facet filters (GH #21) ------------------------------


def _search_form_html(body: str) -> str:
    """The header search form's own markup (``<form role="search">``), isolated from the rail/
    ledger — so an assertion here can never accidentally match a facet link or pagination href
    that happens to carry the same param/value elsewhere on the page."""
    return body.split('<form role="search"', 1)[1].split("</form>", 1)[0]


def test_search_form_echoes_every_active_filter_as_hidden_input(indexed_corpus: Corpus) -> None:
    # Typing a NEW q must refine WITHIN the active filter scope: the form carries every active
    # filter param as a hidden input, with its exact current value. seite is the one deliberate
    # exception (a new search resets to page 1); q stays the single live input, never also hidden.
    query = (
        "q=Fahrt&bestand=FOTOS&medienart=Foto&dokumenttyp=Lagerheft&schlagwort=fahrten"
        "&jahrzehnt=1960&ohne_datum=1&von=1960-01-01&bis=1969-12-31&sortierung=-signatur&seite=2"
    )
    form_html = _search_form_html(_get(Public(), query).content.decode())
    assert form_html.count('name="q"') == 1  # the live input only — never duplicated as hidden
    for name, value in [
        ("bestand", "FOTOS"),
        ("medienart", "Foto"),
        ("dokumenttyp", "Lagerheft"),
        ("schlagwort", "fahrten"),
        ("jahrzehnt", "1960"),
        ("ohne_datum", "1"),
        ("von", "1960-01-01"),
        ("bis", "1969-12-31"),
        ("sortierung", "-signatur"),
    ]:
        assert f'type="hidden" name="{name}" value="{value}"' in form_html
    assert (
        'name="seite"' not in form_html
    )  # deliberately NOT echoed — a new search resets to page 1


def test_form_filter_params_track_every_browse_search_param() -> None:
    # Drift pin: the form's echo list must stay exactly browse's search-state vocabulary minus q
    # (the live input) and seite (a new search resets to page 1). A search param added to
    # browse._SEARCH_PARAMS but forgotten in _FORM_FILTER_PARAMS would silently reintroduce
    # GH #21 (the form dropping that filter) with every markup test still green.
    assert set(_FORM_FILTER_PARAMS) == browse._SEARCH_PARAMS - {browse.PARAM_Q, browse.PARAM_PAGE}
    assert len(_FORM_FILTER_PARAMS) == len(set(_FORM_FILTER_PARAMS))  # no duplicate hidden inputs


def test_search_form_has_no_hidden_inputs_when_no_filter_is_active(indexed_corpus: Corpus) -> None:
    # No active filter → zero hidden inputs (today's markup, unchanged) — q alone never adds one.
    form_html = _search_form_html(_get(Public(), "q=Fahrt").content.decode())
    assert 'type="hidden"' not in form_html


def test_search_form_hidden_input_values_are_html_escaped(indexed_corpus: Corpus) -> None:
    # A filter value rides straight from the query string into an HTML attribute — Django's default
    # auto-escape (not `|safe`) must hold: &, " and an umlaut all render safely, one pinned value.
    raw_value = 'Bär & "Söhne"'
    body = _get(Public(), "schlagwort=" + quote(raw_value)).content.decode()
    form_html = _search_form_html(body)
    assert 'name="schlagwort" value="Bär &amp; &quot;Söhne&quot;"' in form_html
    assert raw_value not in form_html  # the raw, unescaped value never appears


def test_round_trip_q_and_bestand_both_filter_results(indexed_corpus: Corpus) -> None:
    # The server side of the loop the form now closes: a GET carrying BOTH q and an active filter
    # narrows by both together (not just markup) — proves the request the completed form emits
    # actually works. "Fahrt" matches only FOTOS-collection articles; AKTEN has none.
    empty = _get(Public(), "q=Fahrt&bestand=AKTEN").content.decode()
    assert "0 Treffer" in empty
    both = _get(Public(), "q=Fahrt&bestand=FOTOS").content.decode()
    assert "Fahrtenbericht" in both


# --- long Signaturen: the SIG mark sizes to content, never truncates --------------


def test_long_signaturen_render_in_full(indexed_corpus: Corpus) -> None:
    # An identity mark must never truncate at realistic lengths (owner correction 3) — realistic
    # being the 8-character, space-free ceiling (owner 2026-08-07), not an invented long code.
    body = _get(Public()).content.decode()
    assert "F12/3-b" in body
    assert "BA1848/2" in body


# --- param injection: garbage → 200 defaults, never 500 --------------------------


def test_garbage_params_yield_200_defaults(indexed_corpus: Corpus) -> None:
    response = _get(
        Public(),
        "jahrzehnt=abc&seite=-9&von=fruehjahr&sortierung=nonsense&ohne_datum=maybe",
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Öffentliches Foto" in body  # a normal, all-defaults result set


# --- pagination -------------------------------------------------------------------


def test_pagination_second_page_via_seite(indexed_corpus: Corpus) -> None:
    # page_size is 50 by default; force a tiny page via the URL is not supported, so assert the
    # pager is absent for a small corpus and page 1 is honest. (Pagination link algebra is unit-
    # tested in test_browse_links; here we pin that seite is honored without crashing.)
    response = _get(Archivist(), "seite=2")
    assert response.status_code == 200


# --- one-click entry: Titel = detail navigation; the pane opens via the Vorschau action -----


def test_titel_navigates_and_vorschau_link_opens_pane(indexed_corpus: Corpus) -> None:
    # ONE-CLICK ENTRY (owner 2026-08-07): the Titel link is plain navigation to the canonical
    # detail route — no pane interception, no data-artikel JS hook. The pane opens via the
    # explicit per-row Vorschau action: a plain GET link to ?artikel=<ulid> (URL-borne pane
    # state; the no-JS baseline IS this link).
    body = _get(Public()).content.decode()
    assert f'href="/artikel/{PANE_PUB_ULID}"' in body  # the Titel's detail navigation
    assert "data-artikel" not in body  # the JS upgrade hook died with ledger_pane.js
    # the href value and the accessible name, pinned separately (no attribute-order pin)
    assert f'href="?artikel={PANE_PUB_ULID}"' in body
    assert 'aria-label="Vorschau"' in body


def test_vorschau_link_preserves_search_state(indexed_corpus: Corpus) -> None:
    # The Vorschau link carries the CURRENT search (q + facets), so opening the pane never drops
    # the filter scope; artikel rides last. The contract is "all pairs present, artikel last" —
    # NOT one exact param ordering (a Mapping-iteration change is no behavior change).
    body = _get(Public(), "q=Vorschau&medienart=Foto").content.decode()
    match = re.search(rf'href="\?([^"]*artikel={PANE_PUB_ULID})"', body)
    assert match, "no Vorschau link found"
    pairs = match.group(1).replace("&amp;", "&").split("&")
    assert "q=Vorschau" in pairs and "medienart=Foto" in pairs
    assert pairs[-1] == f"artikel={PANE_PUB_ULID}"


def test_row_toolbar_bearbeiten_is_archivist_chrome(indexed_corpus: Corpus) -> None:
    # The row toolbar's Bearbeiten (pencil → the edit form) is archivist-only; the Vorschau
    # affordance exists for every viewer (the pane itself re-authorizes fail-closed).
    arch = _get(Archivist()).content.decode()
    assert f'href="/artikel/{PANE_PUB_ULID}/bearbeiten"' in arch
    assert 'aria-label="Bearbeiten"' in arch
    for viewer, label in _NON_ARCHIVIST:
        body = _get(viewer).content.decode()
        assert 'aria-label="Bearbeiten"' not in body, f"[{label}] Bearbeiten control leaked"
        assert 'aria-label="Vorschau"' in body, f"[{label}] Vorschau affordance missing"


# --- preview pane (?artikel): fail-closed, leak-safe ----------------


def test_pane_opens_for_a_viewable_article(indexed_corpus: Corpus) -> None:
    # A public article's pane opens for the public viewer: its title + Signatur + Öffnen appear, and
    # the row is marked selected.
    body = _get(Public(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert 'class="pane"' in body
    assert "Vorschau Sommerfahrt" in body
    assert "Titelaufnahme der Fahrt" in body  # the media caption
    assert "Öffnen" in body
    assert '<div role="row" aria-current="true">' in body  # the selected row is marked


def test_pane_absent_or_malformed_artikel_renders_no_pane(indexed_corpus: Corpus) -> None:
    # An ABSENT artikel (valid ULID not in the corpus) or a MALFORMED one renders the workbench
    # without a pane — a plain 200, no pane markup. (The denied case is pinned below.)
    for query in (f"artikel={PANE_ABSENT_ULID}", "artikel=not-a-ulid"):
        response = _get(Public(), query)
        assert response.status_code == 200
        assert 'class="pane"' not in response.content.decode()


def test_pane_denied_for_member_only_article_as_public(indexed_corpus: Corpus) -> None:
    # Public cannot open the members-only article's pane at all (no pane markup, no title, no floored
    # fields) — the deny is total.
    body = _get(Public(), f"artikel={PANE_MEM_ULID}").content.decode()
    assert 'class="pane"' not in body
    assert "Vorschau Mitgliederakte" not in body
    assert "Panzerschrank" not in body  # floored physical_location never appears
    assert "geheimnis" not in body  # floored custom key never appears


def test_pane_floored_fields_absent_even_for_member_who_can_view(indexed_corpus: Corpus) -> None:
    # A member CAN open the members-only article's pane, but its floored fields are projected away
    # (visible() = can_view + project) — the pane view-model is built from the floored copy.
    body = _get(Member(groups=()), f"artikel={PANE_MEM_ULID}").content.decode()
    assert 'class="pane"' in body
    assert "Vorschau Mitgliederakte" in body  # the member sees the article
    assert "Panzerschrank" not in body  # ...but never its physical_location
    assert "Panzernachlass" not in body  # ...nor its custom value
    assert "geheimnis" not in body  # ...nor its custom key


def test_pane_bearbeiten_only_for_archivist(indexed_corpus: Corpus) -> None:
    # The pane's Bearbeiten is archivist chrome; Öffnen is for everyone who can see the article.
    pub = _get(Public(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert "Öffnen" in pub
    assert "Bearbeiten" not in pub  # public gets no edit affordance
    arch = _get(Archivist(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert "Bearbeiten" in arch and "Öffnen" in arch


def test_pane_close_link_preserves_query_drops_only_artikel(indexed_corpus: Corpus) -> None:
    # The pane-close ✕ must return to the SAME search (text + facets + sort + page), dropping only
    # the pane selection (artikel). A bare href="?" would blow away the whole query — regression.
    body = _get(
        Public(),
        f"q=Vorschau&medienart=Foto&artikel={PANE_PUB_ULID}",
    ).content.decode()
    assert 'class="pane"' in body  # the pane is open
    # the close link carries the active search params...
    assert "q=Vorschau" in body
    assert "medienart=Foto" in body
    # ...but never the artikel selection (it is pane state, stripped from the close href)
    close_href = body.split(' aria-label="Vorschau schließen"', 1)[0].rsplit('href="', 1)[1]
    assert "artikel" not in close_href, f"close href must drop artikel: {close_href}"
    assert "q=Vorschau" in close_href and "medienart=Foto" in close_href


def test_pane_open_marks_the_vorschau_state(indexed_corpus: Corpus) -> None:
    # Opening the pane puts the body in the vorschau state (the pane frame column is CSS-driven off
    # this body class ≥1280px; the ledger re-densifies by itself — it is a size container).
    body = _get(Public(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert '<body class="workbench vorschau">' in body
    closed = _get(Public()).content.decode()
    assert '<body class="workbench">' in closed


# --- bulk edit: selection column + bar (Sammelbearbeitung, spec §2) ----------------


def test_archivist_sees_bulk_checkbox_column(indexed_corpus: Corpus) -> None:
    body = _get(Archivist()).content.decode()
    assert 'class="ledger bulk"' in body
    assert 'name="auswahl"' in body  # row checkboxes
    assert '<span class="visually-hidden">Auswahl</span>' in body  # the sr-only column header


def test_public_never_gets_bulk_column(indexed_corpus: Corpus) -> None:
    body = _get(Public()).content.decode()
    assert 'class="ledger bulk"' not in body
    assert 'name="auswahl"' not in body
    assert "Sammelbearbeitung" not in body


def test_bulk_bar_affordances_present_when_empty(indexed_corpus: Corpus) -> None:
    # The progressive pattern's SERVER half (owner 2026-08-07, reverses the #16 cold-start
    # ruling): with an EMPTY selection the disclosure still renders VISIBLE for an archivist-
    # with-results — the no-JS baseline must reach "Alle auf dieser Seite" and the "Änderung
    # prüfen" submit; catalog_bulk.js (not the server) hides it at count 0 and reveals it on the
    # first tick (pinned by the e2e journeys). Signals-once still holds: NO "0 ausgewählt" count
    # and NO "Auswahl aufheben" until a selection exists.
    body = _get(Archivist()).content.decode()
    # the collapsed disclosure (cold = summary only); the open tag also carries the
    # data-bulk-offpage hook the enhancement counts with, so match the prefix only
    assert '<details class="bulk"' in body
    assert "Sammelbearbeitung" in body
    assert "Änderung prüfen" in body
    assert "Alle auf dieser Seite" in body
    assert "ausgewählt" not in body  # no status filler
    assert "Auswahl aufheben" not in body


def test_bulk_bar_shows_with_selection_and_count(indexed_corpus: Corpus) -> None:
    body = _get(Archivist(), f"auswahl={PANE_PUB_ULID}").content.decode()
    assert '<details class="bulk"' in body
    # the selected article IS on this page, so nothing is off-page — the enhancement adds its own
    # live checkbox count to this number and must not double-count what it can already see (G.25)
    assert 'data-bulk-offpage="0"' in body
    assert "1 ausgewählt" in body  # the count rides the always-visible summary line
    assert "Änderung prüfen" in body
    assert "Feld" in body  # the chooser Feld select
    # the selected row's checkbox is checked — the checked box IS the selection mark
    # (owner 2026-08-07: no inversion bar; unchecked boxes reveal on hover)
    assert f'value="{PANE_PUB_ULID}" checked' in body


def test_selection_survives_pagination_links(indexed_corpus: Corpus) -> None:
    # the next/prev pagination links carry the ?auswahl= selection (no-JS persistence)
    body = _get(Archivist(), f"auswahl={PANE_PUB_ULID}&seite=1").content.decode()
    assert f"auswahl={PANE_PUB_ULID}" in body


def test_non_archivist_auswahl_param_is_ignored(indexed_corpus: Corpus) -> None:
    # a Public viewer hand-crafting ?auswahl= gets no bar/column (defence-in-depth; the POST route
    # is independently gated too)
    body = _get(Public(), f"auswahl={PANE_PUB_ULID}").content.decode()
    assert "Sammelbearbeitung" not in body
    assert "ausgewählt" not in body


def test_auswahl_aufheben_preserves_active_search(indexed_corpus: Corpus) -> None:
    # Design-gate MED: "Auswahl aufheben" drops the selection but must KEEP the active search — a
    # bare "?" would wipe the filter. The clear link carries the filters, not auswahl.
    body = _get(Archivist(), f"q=fahrt&auswahl={PANE_PUB_ULID}").content.decode()
    clear = body.split(">Auswahl aufheben<", 1)[0].rsplit('href="?', 1)[1].split('"', 1)[0]
    assert "q=fahrt" in clear  # the search survives
    assert "auswahl" not in clear  # the selection is dropped
