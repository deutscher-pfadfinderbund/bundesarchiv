"""The search field's suggestions: the pure grouping (``build``) and the route's shell contract.

What each tier is offered is ``tests/index/test_leaks_suggestions.py``'s.
"""

import re
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as, make_article, make_collection

from bundesarchiv.app.web.suggestions import Entry, Group, build
from bundesarchiv.domain.models import ULID, Audience, AudienceTier
from bundesarchiv.domain.viewer import Member, Public
from bundesarchiv.index import indexer
from bundesarchiv.index.query import FacetCount, SearchHit, SearchPage


def _hit(n: int) -> SearchHit:
    return SearchHit(
        ulid=ULID(f"U{n}"),
        title=f"Königstein {n}",
        ref_code=None,
        date_edtf="1960" if n == 0 else None,
        media_type=None,
        document_type=None,
        is_draft=False,
        collection_id=ULID("ROOT"),
        file_counts=(),
    )


def _page(hits: int) -> SearchPage:
    return SearchPage(
        hits=tuple(_hit(n) for n in range(hits)), total=hits, facets={}, dateless_count=0
    )


def _counts(*pairs: tuple[str, int]) -> tuple[FacetCount, ...]:
    return tuple(FacetCount(value, count) for value, count in pairs)


def test_each_group_is_capped_and_an_empty_one_left_out() -> None:
    groups = build(
        "könig",
        {},
        _page(5),
        {
            "creator": _counts(("Königs Erben", 4), ("Hans König", 2), ("Königin", 1)),
            "tags": _counts(("Königstreffen", 3), ("Königsberg", 2), ("Königslager", 2)),
        },
    )
    assert [(g.kind, len(g.entries)) for g in groups] == [
        ("Einträge", 3),
        ("Autor", 2),
        ("Schlagworte", 2),
    ]


def test_a_tag_used_once_is_dropped() -> None:
    groups = build("könig", {}, _page(0), {"tags": _counts(("Königsheft 3", 1))})
    assert groups == ()


def test_an_entry_marks_the_first_match_and_leads_to_its_pick() -> None:
    article, creator = build("KÖNIG", {}, _page(1), {"creator": _counts(("Hans König", 1_234))})
    assert article == Group(
        "Einträge",
        (Entry("", "König", "stein 0", reverse("article-detail", args=["U0"]), date="1960"),),
    )
    (entry,) = creator.entries
    assert (entry.before, entry.match, entry.after, entry.count) == ("Hans ", "König", "", "1.234")


def test_a_value_pick_keeps_the_filters_and_drops_the_text() -> None:
    within = {"q": "König", "media_type": "Foto(s)", "creator": "Anna", "sort": "date", "page": "2"}
    (creator,) = build("König", within, _page(0), {"creator": _counts(("Hans König", 2))})
    href = urlparse(creator.entries[0].href)
    assert href.path == reverse("workbench")
    assert parse_qs(href.query) == {
        "media_type": ["Foto(s)"],
        "creator": ["Hans König"],
        "sort": ["date"],
    }


def test_a_value_the_text_does_not_spell_is_left_unmarked() -> None:
    (place,) = build("strasse", {}, _page(0), {"place": _counts(("Große Straße", 2))})
    entry = place.entries[0]
    assert (entry.before, entry.match, entry.after) == ("Große Straße", "", "")


def test_a_public_viewer_and_a_post_are_denied(corpus: Corpus) -> None:
    for path in ("/suggestions", "/suggestions/list"):
        assert_denied(client_as(Public()).get(f"{path}?q=wald"), f"GET {path} as Public")
        assert_denied(client_as(Member(())).post(f"{path}?q=wald"), f"POST {path} as a Member")


def test_no_text_offers_nothing_and_is_never_shared_cached(corpus: Corpus) -> None:
    response = client_as(Member(())).get("/suggestions?q=+")
    assert response.status_code == 200
    assert response.context["groups"] == ()
    assert response["Cache-Control"] == "private"
    assert b'role="option"' not in response.content


_BUND = "01KX8A00000000000000000BND"


@pytest.mark.django_db
def test_the_groups_and_the_all_link_stay_within_the_forms_filters(
    make_corpus: Callable[[], Corpus],
) -> None:
    corpus = make_corpus()
    public = Audience(AudienceTier.PUBLIC)
    corpus.add_collection(make_collection(_BUND, "Bund", parent_id=None, audience=public))
    for n, (creator, media_type) in enumerate(
        (("Anna Sommer", "Foto(s)"), ("Bert Sommer", "Buch"))
    ):
        corpus.add_article(
            make_article(
                f"01KX8A00000000000000000AR{n}",
                title=f"Sommerfahrt {n}",
                collection_id=_BUND,
                creator=creator,
                media_type=media_type,
            )
        )
    indexer.rebuild(corpus.store)
    response = client_as(Member(())).get("/suggestions?q=sommer&media_type=Foto(s)&page=3")
    _, creator = response.context["groups"]
    assert [(e.before + e.match + e.after, e.count) for e in creator.entries] == [
        ("Anna Sommer", "1")
    ]
    assert parse_qs(urlparse(response.context["all_href"]).query) == {
        "q": ["sommer"],
        "media_type": ["Foto(s)"],
    }


@pytest.mark.django_db
def test_only_the_start_pages_route_ends_with_the_all_option(
    make_corpus: Callable[[], Corpus],
) -> None:
    corpus = make_corpus()
    public = Audience(AudienceTier.PUBLIC)
    corpus.add_collection(make_collection(_BUND, "Bund", parent_id=None, audience=public))
    corpus.add_article(
        make_article("01KX8A00000000000000000AR0", title="Sommerfahrt", collection_id=_BUND)
    )
    indexer.rebuild(corpus.store)
    start = client_as(Member(())).get("/suggestions?q=sommer").content
    on_list = client_as(Member(())).get("/suggestions/list?q=sommer").content
    # the same options, and on the start page one more: the list Enter submits
    assert on_list.count(b'role="option"') >= 1
    assert start.count(b'role="option"') == on_list.count(b'role="option"') + 1


@pytest.mark.parametrize("path", ["/", "/articles"])
@pytest.mark.parametrize(
    ("viewer", "asks"),
    [(Public(), False), (Member(()), True)],
    ids=["public", "member"],
)
def test_only_a_signed_in_viewers_search_field_asks_for_suggestions(
    db: None, corpus: Corpus, path: str, viewer: Public | Member, asks: bool
) -> None:
    response = client_as(viewer).get(path)
    assert response.status_code == 200
    (field,) = re.findall(r'<input[^>]*id="search-field"[^>]*>', response.content.decode())
    assert ("data-suggest=" in field) is asks
    if asks:
        route = "/suggestions" if path == "/" else "/suggestions/list"
        assert f'data-suggest="{route}"' in field
