"""Suggestions while typing in the search field (``GET /suggestions``): a member route.

The pure core ``build`` groups, caps and spells what the shell ``suggestions`` asked the index
for: the list's own ``search`` for the Artikel and the total, ``values_containing`` for Autor, Ort
and Schlagworte, all with the request's viewer. No query of its own.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from django.http import HttpRequest, HttpResponseBase
from django.urls import reverse

from bundesarchiv.app.web import browse, card, vocab
from bundesarchiv.app.web.browse_views import preset_url
from bundesarchiv.app.web.media_views import not_found
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.viewer import Public
from bundesarchiv.index.query import FacetCount, SearchPage, search, values_containing

#: The most entries a group offers: about eight in all.
_ARTICLES = 3
_VALUES = 2

_LABELS = {field.name: field.label for field in card.FIELDS}


@dataclass(frozen=True, slots=True)
class Entry:
    """One option: its words split around the first match of the text, where a pick leads, and a
    quiet note (an Artikel's date, a value's count)."""

    before: str
    match: str
    after: str
    href: str
    note: str


@dataclass(frozen=True, slots=True)
class Group:
    kind: str
    entries: tuple[Entry, ...]


def _entry(text: str, words: str, href: str, note: str) -> Entry:
    found = re.search(re.escape(text), words, re.IGNORECASE)
    if found is None:
        return Entry(words, "", "", href, note)
    return Entry(words[: found.start()], found[0], words[found.end() :], href, note)


def _values(text: str, counts: Sequence[FacetCount], param: str) -> tuple[Entry, ...]:
    return tuple(
        _entry(text, fc.value, preset_url(param, fc.value), vocab.count(fc.count))
        for fc in counts[:_VALUES]
    )


def build(
    text: str,
    page: SearchPage,
    creators: Sequence[FacetCount],
    places: Sequence[FacetCount],
    tags: Sequence[FacetCount],
) -> tuple[Group, ...]:
    """The groups in their fixed order, each capped, the empty ones left out. A Schlagwort used
    once is dropped (the legacy tree has one per Wartburg-Bote issue)."""
    groups = (
        Group(
            "Artikel",
            tuple(
                _entry(text, h.title, reverse("article-detail", args=[h.ulid]), h.date_edtf or "")
                for h in page.hits[:_ARTICLES]
            ),
        ),
        Group(_LABELS["creator"], _values(text, creators, browse.PARAM_CREATOR)),
        Group(_LABELS["subject_place"], _values(text, places, browse.PARAM_PLACE)),
        Group(_LABELS["tags"], _values(text, [t for t in tags if t.count > 1], browse.PARAM_TAG)),
    )
    return tuple(g for g in groups if g.entries)


def suggestions(request: HttpRequest) -> HttpResponseBase:
    """``GET /suggestions?q=&<the list's filters>`` — the option groups for the search field, and
    how many hits Enter would list (the form's own filters ride along). Members and Archivists
    only, GET only; else the plain 404. Never cached in a shared cache."""
    viewer = viewer_of(request)
    if isinstance(viewer, Public) or request.method != "GET":
        return not_found()
    parsed = browse.parse_query(request.GET)
    text = parsed.text
    groups: tuple[Group, ...] = ()
    total = 0
    if text is not None:
        page = search(viewer, text=text, filters=parsed.filters, page_size=_ARTICLES, facets=())
        total = page.total
        groups = build(
            text,
            page,
            values_containing(viewer, "creator", text),
            values_containing(viewer, "place", text),
            values_containing(viewer, "tags", text),
        )
    response = render_screen(
        request,
        "workbench/_suggestions.html",
        {"groups": groups, "text": text, "total": total, "total_label": vocab.count(total)},
    )
    response["Cache-Control"] = "private"
    return response
