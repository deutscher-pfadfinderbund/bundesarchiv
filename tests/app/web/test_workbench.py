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

import io
import re
from collections.abc import Callable
from html import unescape
from html.parser import HTMLParser
from typing import cast
from urllib.parse import parse_qs, quote, urlparse

import pytest
from django.http import HttpResponse
from tests.app.web._fixtures import Corpus, client_as, draft_mark, make_article, make_collection

from bundesarchiv.app.web import browse, ledger
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
        PANE_PUB_ULID,
        "titel.jpg",
        io.BytesIO(b"pane-cover-bytes"),
        "image/jpeg",
        "Titelaufnahme der Fahrt",
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
    assert "<html" in body and 'role="search"' in body  # full chrome (search form)
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
    # A history restore expects a FULL page (it swaps the whole body) — never the chrome-less
    # _results.html fragment a plain HX-Request gets, even when both headers arrive together.
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


def test_entwurf_mark_and_bearbeiten_only_for_archivist(indexed_corpus: Corpus) -> None:
    arch = _get(Archivist()).content.decode()
    assert draft_mark() in arch
    assert "Bearbeiten" in arch
    for viewer, label in _NON_ARCHIVIST:
        body = _get(viewer).content.decode()
        assert "Bearbeiten" not in body, f"[{label}] Bearbeiten action leaked"
        # The draft ROW is already scope-hidden; this pins the mark is gone too.
        assert draft_mark() not in body, f"[{label}] Entwurf mark leaked"


# --- facets: rendering, name resolution, Ohne Datum ------------------------------


def _sentence_queries(viewer: Viewer, query: str = "") -> list[dict[str, list[str]]]:
    """Every query the search sentence links to, parsed (its slot menus, set slots, "+ Filter")."""
    form_html = _search_form_html(_get(viewer, query).content.decode())
    return [parse_qs(unescape(href)) for href in re.findall(r'href="\?([^"]*)"', form_html)]


def test_the_slots_offer_the_bestand_decade_type_and_dateless_values(
    indexed_corpus: Corpus,
) -> None:
    queries = _sentence_queries(Public())
    for param, value in [
        ("bestand", "FOTOS"),
        ("dokumenttyp", "Lagerheft"),
        ("ohne_datum", "1"),  # Undatiertes Liederheft has no date
    ]:
        assert {param: [value]} in queries
    assert any(set(q) == {"jahrzehnt"} for q in queries)


def test_every_set_filter_stays_removable_from_the_sentence(indexed_corpus: Corpus) -> None:
    # Nothing the URL filters by may be invisible on the page: each set filter, a slot's or not,
    # links to the same search without it, also on a page with no hits (no facet counts it).
    samples = {
        "bestand": "FOTOS",
        "medienart": "Mikrofilm",
        "dokumenttyp": "Lagerheft",
        "schlagwort": "fahrten",
        "jahrzehnt": "1960",
        "ohne_datum": "1",
        "von": "1960-01-01",
        "bis": "1969-12-31",
        "digital": "1",
        "entwuerfe": "1",
    }
    assert set(samples) == set(browse.FILTER_PARAMS)
    for param, value in samples.items():
        queries = _sentence_queries(Public(), f"q=Nirgendwo&{param}={quote(value)}")
        assert {"q": ["Nirgendwo"]} in queries, param


def test_two_set_filters_clear_together_keeping_the_query_and_sort(
    indexed_corpus: Corpus,
) -> None:
    # Each set filter's own link keeps the other, so only the clear-all link leaves none.
    queries = _sentence_queries(
        Public(), "q=Foto&sortierung=titel&bestand=FOTOS&dokumenttyp=Lagerheft&seite=2"
    )
    assert {"q": ["Foto"], "sortierung": ["titel"]} in queries


def test_the_drafts_filter_is_offered_to_the_archivist_only(indexed_corpus: Corpus) -> None:
    assert {"digital": ["1"]} in _sentence_queries(Public())
    assert {"entwuerfe": ["1"]} in _sentence_queries(Archivist())
    assert all("entwuerfe" not in q for q in _sentence_queries(Member(groups=())))


def test_ohne_datum_filter_narrows_to_dateless(indexed_corpus: Corpus) -> None:
    body = _get(Public(), "ohne_datum=1").content.decode()
    assert "Undatiertes Liederheft" in body
    assert "Öffentliches Foto" not in body  # a dated article is excluded


def _listed(body: str) -> set[str]:
    """The records a page links to (the corpus ulids are upper case, the create route is not)."""
    return set(re.findall(r'href="/artikel/([0-9A-Z]+)"', body))


def test_the_digital_filter_keeps_the_records_with_files(indexed_corpus: Corpus) -> None:
    assert _listed(_get(Archivist(), "digital=1").content.decode()) == {PANE_PUB_ULID}


def test_the_drafts_filter_answers_the_archivist_and_nobody_else(indexed_corpus: Corpus) -> None:
    assert _listed(_get(Archivist(), "entwuerfe=1").content.decode()) == {"DRAFT"}
    response = _get(Member(groups=()), "entwuerfe=1")
    assert response.status_code == 200
    assert _listed(response.content.decode()) == set()


def test_a_bestand_empty_only_under_another_filter_is_not_an_empty_bestand(
    indexed_corpus: Corpus,
) -> None:
    # "Noch keine Artikel in diesem Bestand" and its create link are for a Bestand with no record at
    # all; AKTEN has records, just none with files.
    body = _get(Archivist(), "bestand=AKTEN&digital=1").content.decode()
    assert _listed(body) == set()
    assert "/artikel/neu?bestand=AKTEN" not in body


# --- facet click → filtered results + removable chip -----------------------------


def test_media_facet_filter_narrows_results(indexed_corpus: Corpus) -> None:
    body = _get(Public(), "medienart=Schrifttum").content.decode()
    assert "Undatiertes Liederheft" in body
    assert "Öffentliches Foto" not in body  # a Foto is excluded


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
    assert "Keine Treffer" in empty
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


def test_pagination_second_page_via_seite(
    indexed_corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browse, "PAGE_SIZE", 2)
    ulids = list(indexed_corpus.articles.list_ulids())

    def rows(query: str) -> set[str]:
        body = _get(Archivist(), query).content.decode()
        return {ulid for ulid in ulids if f'href="/artikel/{ulid}"' in body}

    first, second = rows("seite=1"), rows("seite=2")
    assert first
    assert second
    assert not first & second


def _pager(body: str) -> str:
    return body.split('aria-label="Seiten"', 1)[1].split("</nav>", 1)[0]


_ZURUECK = "\N{SINGLE LEFT-POINTING ANGLE QUOTATION MARK} Zurück"
_WEITER = "Weiter \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}"


def test_the_pager_holds_the_range_between_its_steps(
    indexed_corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a2 round 10: the count lives in the range, between the two steps. On page 1 Zurück stays,
    # disabled: it becomes active one click later (LEARNINGS lesson 9).
    monkeypatch.setattr(browse, "PAGE_SIZE", 2)
    total = len(list(indexed_corpus.articles.list_ulids()))  # the archivist sees every record
    pager = _pager(_get(Archivist()).content.decode())
    assert f'1\N{EN DASH}2</data> von <data value="{total}">{total}</data>' in pager
    assert f'<a role="link" aria-disabled="true">{_ZURUECK}</a>' in pager
    assert re.search(rf'<a href="\?[^"]*seite=2[^"]*" rel="next">{_WEITER}</a>', pager)


def test_a_one_page_list_shows_its_count_and_no_steps(indexed_corpus: Corpus) -> None:
    # a2 round 9: neither step can become active on a one-page list, so neither shows.
    total = len(list(indexed_corpus.articles.list_ulids()))
    body = _get(Archivist()).content.decode()
    assert f'<data value="{total}">{total}</data> Artikel</span></p>' in body
    assert 'aria-label="Seiten"' not in body


def _heads(body: str) -> list[str]:
    return re.findall(r'<th scope="col" class="([a-z]+)"', body)


def test_the_ledger_prints_the_columns_its_viewers_cookie_chose(indexed_corpus: Corpus) -> None:
    # The "Spalten …" choice is a per-person cookie (ruling 2026-09-29): it reaches the ledger, and
    # the Bestand column names the record's own Bestand — for a member too, whose rows it scopes.
    client = client_as(Member(groups=()))
    client.cookies[ledger.COOKIE] = ledger.cookie_value(["bestand", "datierung"])
    body = client.get("/").content.decode()
    assert _heads(body) == ["titel", "datierung", "bestand"]
    assert '<td class="bestand">Fotografien</td>' in body
    assert '<td class="bestand">Aktenbestand</td>' in body


@pytest.mark.parametrize("raw", ["", "gibt.es.nicht", "\u00e4", ledger.cookie_value(())])
def test_a_garbage_cookie_prints_the_default_columns_and_no_column_is_a_choice(
    indexed_corpus: Corpus, raw: str
) -> None:
    client = client_as(Public())
    client.cookies[ledger.COOKIE] = raw
    body = client.get("/").content.decode()
    expected = [] if raw == ledger.cookie_value(()) else [c.key for c in ledger.DEFAULT_COLUMNS]
    assert _heads(body) == ["titel", *expected]


# --- one-click entry: the Titel navigates; the paused pane has no way in from the list -------


@pytest.mark.parametrize("viewer", [Public(), Archivist()], ids=["public", "archivist"])
def test_titel_navigates_and_no_list_link_opens_the_pane(
    indexed_corpus: Corpus, viewer: Viewer
) -> None:
    # The Titel is plain navigation to the detail route (owner 2026-08-07). The preview is paused
    # (owner 2026-09-30): the pane opens only from its address, so no link on the list sets artikel.
    body = _get(viewer).content.decode()
    hrefs = [unescape(h) for h in re.findall(r'href="([^"]*)"', body)]
    assert f"/artikel/{PANE_PUB_ULID}" in hrefs
    assert [h for h in hrefs if "artikel" in parse_qs(urlparse(h).query)] == []


def test_row_bearbeiten_is_archivist_chrome(indexed_corpus: Corpus) -> None:
    # The row's Bearbeiten (→ the edit form) is archivist-only.
    arch = _get(Archivist()).content.decode()
    assert f'href="/artikel/{PANE_PUB_ULID}/bearbeiten"' in arch
    assert ">Bearbeiten<" in arch
    for viewer, label in _NON_ARCHIVIST:
        body = _get(viewer).content.decode()
        assert ">Bearbeiten<" not in body, f"[{label}] Bearbeiten control leaked"


# --- preview pane (?artikel): fail-closed, leak-safe ----------------


def test_pane_opens_for_a_viewable_article(indexed_corpus: Corpus) -> None:
    # A public article's pane opens for the public viewer: its title + Signatur + Öffnen appear, and
    # the row is marked selected.
    body = _get(Public(), f"artikel={PANE_PUB_ULID}").content.decode()
    assert 'class="pane"' in body
    assert "Vorschau Sommerfahrt" in body
    assert "Titelaufnahme der Fahrt" in body  # the media caption
    assert "Öffnen" in body
    assert '<tr aria-current="true">' in body  # the selected row is marked


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


# --- bulk edit: the selection and the tool row (Sammelbearbeitung, spec §2) ----------------


class _FormFields(HTMLParser):
    """Which form each named control submits with, as a browser resolves it: its ``form=`` owner,
    else the open ``<form>`` around it. A ``<form>`` opened inside another is dropped, as the HTML
    parser drops it, and counted in ``nested``."""

    def __init__(self) -> None:
        super().__init__()
        self.actions: dict[str, str] = {}
        self.open: list[str] = []
        self.nested = 0
        self.by_id: list[tuple[str, str]] = []
        self.fields: dict[str, set[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            if self.open:
                self.nested += 1
                return
            self.open.append(a.get("action", ""))
            if "id" in a:
                self.actions[a["id"]] = a.get("action", "")
        elif tag in {"input", "select", "textarea", "button"} and a.get("name"):
            if "form" in a:
                self.by_id.append((a["form"], a["name"]))
            elif self.open:
                self.fields.setdefault(self.open[-1], set()).add(a["name"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self.open:
            self.open.pop()


def _form_fields(body: str) -> tuple[dict[str, set[str]], int]:
    """Each form's action mapped to the names it submits, plus the count of nested forms."""
    parser = _FormFields()
    parser.feed(body)
    for form_id, name in parser.by_id:
        parser.fields.setdefault(parser.actions[form_id], set()).add(name)
    return parser.fields, parser.nested


def _queries(body: str) -> list[dict[str, list[str]]]:
    """Every in-page link's query, blank values kept: ``auswahl=`` alone is selection mode."""
    hrefs = re.findall(r'href="\?([^"]*)"', body)
    return [parse_qs(unescape(q), keep_blank_values=True) for q in hrefs]


def test_the_archivist_list_has_no_selection_until_auswaehlen(indexed_corpus: Corpus) -> None:
    body = _get(Archivist(), "q=fahrt").content.decode()
    assert 'name="auswahl"' not in body
    # "Auswählen" is the same search in selection mode
    assert {"q": ["fahrt"], "auswahl": [""]} in _queries(body)


def test_selection_mode_shows_the_selection_column(indexed_corpus: Corpus) -> None:
    body = _get(Archivist(), "auswahl=").content.decode()
    assert 'name="auswahl"' in body
    assert "/artikel/sammelbearbeitung" in _form_fields(body)[0]


@pytest.mark.parametrize("viewer", [Public(), Member(groups=())])
@pytest.mark.parametrize("query", ["", "auswahl=", f"auswahl={PANE_PUB_ULID}"])
def test_non_archivists_never_get_the_selection(
    indexed_corpus: Corpus, monkeypatch: pytest.MonkeyPatch, viewer: Viewer, query: str
) -> None:
    # no column, no bulk form, no link into selection mode — a hand-crafted ?auswahl= included;
    # one hit per page, so the pager's links are there to carry it
    monkeypatch.setattr(browse, "PAGE_SIZE", 1)
    body = _get(viewer, query).content.decode()
    assert 'name="auswahl"' not in body
    assert "/artikel/sammelbearbeitung" not in _form_fields(body)[0]
    assert not [q for q in _queries(body) if "auswahl" in q]


@pytest.mark.parametrize("query", ["auswahl=", f"auswahl={PANE_PUB_ULID}"])
def test_the_ticks_the_feld_chooser_and_the_columns_each_submit_with_their_own_form(
    indexed_corpus: Corpus, query: str
) -> None:
    # The no-JS contract: with or without a selection the bulk form carries the row ticks and the
    # Feld chooser, and "Spalten …" posts only its own choice, although both sit in one tool row.
    fields, nested = _form_fields(_get(Archivist(), query).content.decode())
    assert nested == 0
    assert {"auswahl", "feld", "csrfmiddlewaretoken"} <= fields["/artikel/sammelbearbeitung"]
    assert "spalte" not in fields["/artikel/sammelbearbeitung"]
    assert {"spalte", "zurueck", "csrfmiddlewaretoken"} <= fields["/spalten"]
    assert not {"auswahl", "feld"} & fields["/spalten"]


def test_the_head_box_submits_the_rows_of_its_page(indexed_corpus: Corpus) -> None:
    # without JS a ticked head box means "every row on this page" (bulk_views reads it)
    body = _get(Archivist(), "auswahl=").content.decode()
    rows = re.findall(r'name="auswahl" value="([^"]+)"', body)
    [alle] = re.findall(r'name="alle" value="([^"]*)"', body)
    assert rows and alle.split() == rows


def test_a_url_selection_ticks_its_row(indexed_corpus: Corpus) -> None:
    body = _get(Archivist(), f"auswahl={PANE_PUB_ULID}").content.decode()
    # the selected article IS on this page, so nothing is off-page — the enhancement adds its own
    # live checkbox count to this number and must not double-count what it can already see (G.25)
    assert 'data-bulk-offpage="0"' in body
    assert f'value="{PANE_PUB_ULID}" checked' in body


def test_selection_survives_pagination_links(
    indexed_corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the next/prev pagination links carry the ?auswahl= selection (no-JS persistence)
    monkeypatch.setattr(browse, "PAGE_SIZE", 2)
    body = _get(Archivist(), f"auswahl={PANE_PUB_ULID}&seite=2").content.decode()
    pager = body.split('aria-label="Seiten"', 1)[1].split("</nav>", 1)[0]
    queries = [parse_qs(unescape(q)) for q in re.findall(r'href="\?([^"]*)"', pager)]
    assert [q.get("seite") for q in queries] == [["1"], ["3"]]
    assert [q.get("auswahl") for q in queries] == [[PANE_PUB_ULID]] * 2


def test_paging_keeps_selection_mode_with_nothing_ticked(
    indexed_corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browse, "PAGE_SIZE", 2)
    body = _get(Archivist(), "auswahl=&seite=2").content.decode()
    pager = body.split('aria-label="Seiten"', 1)[1].split("</nav>", 1)[0]
    assert [q.get("auswahl") for q in _queries(pager)] == [[""]] * 2


def test_abbrechen_leaves_selection_mode_and_keeps_the_search(indexed_corpus: Corpus) -> None:
    # a bare "?" would wipe the search: "Abbrechen" is the same search without the selection
    body = _get(Archivist(), f"q=fahrt&auswahl={PANE_PUB_ULID}").content.decode()
    assert {"q": ["fahrt"]} in _queries(body)
