"""The search field's suggestions: the pure grouping (``build``) and the route's shell contract.

What each tier is offered is ``tests/index/test_leaks_suggestions.py``'s.
"""

from django.urls import reverse
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as

from bundesarchiv.app.web.browse_views import preset_url
from bundesarchiv.app.web.suggestions import Entry, Group, build
from bundesarchiv.domain.viewer import Member, Public
from bundesarchiv.index.query import FacetCount, SearchHit, SearchPage


def _hit(n: int) -> SearchHit:
    return SearchHit(
        ulid=f"U{n}",
        title=f"Königstein {n}",
        ref_code=None,
        date_edtf="1960" if n == 0 else None,
        media_type=None,
        document_type=None,
        is_draft=False,
        collection_id="ROOT",
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
        _page(5),
        _counts(("Königs Erben", 4), ("Hans König", 2), ("Königin", 1)),
        (),
        _counts(("Königstreffen", 3), ("Königsberg", 2), ("Königslager", 2)),
    )
    assert [(g.kind, len(g.entries)) for g in groups] == [
        ("Artikel", 3),
        ("Autor", 2),
        ("Schlagworte", 2),
    ]


def test_a_tag_used_once_is_dropped() -> None:
    groups = build("könig", _page(0), (), (), _counts(("Königsheft 3", 1)))
    assert groups == ()


def test_an_entry_marks_the_first_match_and_leads_to_its_pick() -> None:
    article, creator = build("KÖNIG", _page(1), _counts(("Hans König", 1_234)), (), ())
    assert article == Group(
        "Artikel",
        (Entry("", "König", "stein 0", reverse("article-detail", args=["U0"]), "1960"),),
    )
    assert creator.entries == (
        Entry("Hans ", "König", "", preset_url("creator", "Hans König"), "1.234"),
    )


def test_a_value_the_text_does_not_spell_is_left_unmarked() -> None:
    (place,) = build("strasse", _page(0), (), _counts(("Große Straße", 2)), ())
    entry = place.entries[0]
    assert (entry.before, entry.match, entry.after) == ("Große Straße", "", "")


def test_a_public_viewer_and_a_post_are_denied(corpus: Corpus) -> None:
    assert_denied(client_as(Public()).get("/suggestions?q=wald"), "GET as Public")
    assert_denied(client_as(Member(())).post("/suggestions?q=wald"), "POST as a Member")


def test_no_text_offers_nothing_and_is_never_shared_cached(corpus: Corpus) -> None:
    response = client_as(Member(())).get("/suggestions?q=+")
    assert response.status_code == 200
    assert response.context["groups"] == ()
    assert response["Cache-Control"] == "private"
    assert b'role="option"' not in response.content
