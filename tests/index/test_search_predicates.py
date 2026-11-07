"""A search's filter predicate and its facet plans, as ``Q`` trees: no database."""

import datetime

import pytest
from django.db.models import Q

from bundesarchiv.index.query import Facet, SearchFilters, dateless_plan, facet_plan, where

_FROM = datetime.date(1950, 1, 1)
_TO = datetime.date(1959, 12, 31)


def _conjuncts(predicate: Q) -> list[object]:
    """The terms ``predicate`` ANDs, in a fixed order: ``Q`` equality depends on child order."""
    assert predicate.connector == Q.AND
    assert not predicate.negated
    return sorted(predicate.children, key=repr)


def test_filters_combine_as_a_conjunction() -> None:
    filters = SearchFilters(place="Berlin", tag="Lager", templates_only=True, date_to=_TO)
    assert _conjuncts(where(filters)) == _conjuncts(
        Q(subject_place="Berlin")
        & Q(tags__contains=["Lager"])
        & Q(is_template=True)
        & Q(date_earliest__isnull=False)
        & Q(date_earliest__lte=_TO)
    )


_FILTERS = SearchFilters(media_type="Foto", document_type="Brief", tag="Lager", decade=1950)
_FOTO, _BRIEF = Q(media_type="Foto"), Q(document_type="Brief")
_LAGER, _FIFTIES = Q(tags__contains=["Lager"]), Q(decades__contains=[1950])


@pytest.mark.parametrize(
    ("facet", "predicate"),
    [
        ("media_type", _LAGER & _FIFTIES),
        ("document_type", _FOTO & _LAGER & _FIFTIES),
        ("tags", _FOTO & _BRIEF & _FIFTIES),
        ("decades", _FOTO & _BRIEF & _LAGER),
        ("creator", _FOTO & _BRIEF & _LAGER & _FIFTIES),
        ("collection", _FOTO & _BRIEF & _LAGER & _FIFTIES),
        ("file_kind", _FOTO & _BRIEF & _LAGER & _FIFTIES),
    ],
)
def test_a_facet_counts_under_every_filter_but_its_own_and_those_nested_under_it(
    facet: Facet, predicate: Q
) -> None:
    (planned,) = facet_plan(_FILTERS, (facet,)).values()
    assert _conjuncts(planned) == _conjuncts(predicate)


def test_a_facet_plan_has_one_predicate_per_wanted_facet() -> None:
    assert facet_plan(SearchFilters(place="Berlin"), ("place", "creator")) == {
        "place": Q(),
        "creator": Q(subject_place="Berlin"),
    }


def test_the_dateless_bucket_counts_under_every_filter_but_the_date_window() -> None:
    filters = SearchFilters(place="Berlin", date_from=_FROM, date_to=_TO)
    assert _conjuncts(dateless_plan(filters)) == _conjuncts(
        Q(subject_place="Berlin") & Q(date_earliest__isnull=True)
    )
