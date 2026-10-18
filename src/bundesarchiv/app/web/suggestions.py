"""Suggestions while typing in the search field (``GET /suggestions``): a member route.

The pure core ``build`` groups, caps and spells what the shell ``suggestions`` asked the index
for: the list's own ``search`` for the Artikel and the total, ``values_containing`` for Autor, Ort
and Schlagworte, all with the request's viewer and the form's filters. No query of its own.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from django.http import HttpRequest, HttpResponseBase
from django.urls import reverse

from bundesarchiv.app.web import browse, card, vocab
from bundesarchiv.app.web.browse_views import preset_url
from bundesarchiv.app.web.media_views import not_found
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.viewer import Public
from bundesarchiv.index.query import (
    FacetCount,
    SearchPage,
    Suggested,
    search,
    values_containing,
)

#: The most entries a group offers: about eight in all.
_ARTICLES = 3
_VALUES = 2


@dataclass(frozen=True, slots=True)
class Entry:
    """One option: its words split around the first match of the text, where a pick leads, and what
    it adds (an Artikel's date, a value's count)."""

    before: str
    match: str
    after: str
    href: str
    date: str = ""
    count: str = ""


@dataclass(frozen=True, slots=True)
class Group:
    kind: str
    entries: tuple[Entry, ...]


def _entry(text: str, words: str, href: str, *, date: str = "", count: str = "") -> Entry:
    found = re.search(re.escape(text), words, re.IGNORECASE)
    if found is None:
        return Entry(words, "", "", href, date, count)
    return Entry(words[: found.start()], found[0], words[found.end() :], href, date, count)


#: The value groups in their order: the field asked for, its label and the param a pick sets.
_VALUE_GROUPS: tuple[tuple[Suggested, str, str], ...] = (
    ("creator", card.LABELS["creator"], browse.PARAM_CREATOR),
    ("place", card.LABELS["subject_place"], browse.PARAM_PLACE),
    ("tags", card.LABELS["tags"], browse.PARAM_TAG),
)


def _kept(field: Suggested, counts: Sequence[FacetCount]) -> Sequence[FacetCount]:
    """A Schlagwort used once is dropped (the legacy tree has one per Wartburg-Bote issue)."""
    return [fc for fc in counts if fc.count > 1] if field == "tags" else counts


def _values(
    text: str, within: Mapping[str, str], counts: Sequence[FacetCount], param: str
) -> tuple[Entry, ...]:
    return tuple(
        _entry(text, fc.value, preset_url(param, fc.value, within), count=vocab.count(fc.count))
        for fc in counts[:_VALUES]
    )


def build(
    text: str,
    within: Mapping[str, str],
    page: SearchPage,
    values: Mapping[Suggested, Sequence[FacetCount]],
) -> tuple[Group, ...]:
    """The groups in their fixed order, each capped, the empty ones left out. A value's pick is the
    list ``within`` (the form's params) leads to, with that value set and without the text
    (ruling 2)."""
    articles = tuple(
        _entry(text, h.title, reverse("article-detail", args=[h.ulid]), date=h.date_edtf or "")
        for h in page.hits[:_ARTICLES]
    )
    groups = (
        Group("Artikel", articles),
        *(
            Group(label, _values(text, within, _kept(field, values.get(field, ())), param))
            for field, label, param in _VALUE_GROUPS
        ),
    )
    return tuple(g for g in groups if g.entries)


def suggestions(request: HttpRequest, *, all_option: bool = True) -> HttpResponseBase:
    """``GET /suggestions?q=&<the list's filters>`` — the option groups for the search field, and
    the list Enter would submit, with its count. The start page's field asks ``/suggestions``,
    where that list is the last option; the list page's ``/suggestions/list`` (``all_option``
    off) leaves it out, since the page already shows it. Members and Archivists only, GET only;
    else the plain 404. Never cached in a shared cache."""
    viewer = viewer_of(request)
    if isinstance(viewer, Public) or request.method != "GET":
        return not_found()
    parsed = browse.parse_query(request.GET)
    text, filters = parsed.text, parsed.filters
    groups: tuple[Group, ...] = ()
    total = 0
    all_href = None
    if text is not None:
        page = search(viewer, text=text, filters=filters, page_size=_ARTICLES, facets=())
        total = page.total
        groups = build(
            text,
            request.GET,
            page,
            {f: values_containing(viewer, f, text, filters) for f, _, _ in _VALUE_GROUPS},
        )
        all_href = preset_url(browse.PARAM_Q, text, request.GET)
    response = render_screen(
        request,
        "workbench/_suggestions.html",
        {
            "groups": groups,
            "text": text,
            "total": total,
            "total_label": vocab.count(total),
            "all_href": all_href,
            "all_option": all_option,
        },
    )
    response["Cache-Control"] = "private"
    return response
