"""The Lesesaal: a search's hits as rows to read, the reading view of the same search as the ledger.

A row is the title, the why line (the field the query matched in, unless the title already shows
the word), the matching pages and one line of facts in place of the ledger's columns. ``rows`` turns
a page of ``SearchHit`` s into rows the template only prints. No visibility logic lives here: the
hits are viewer-scoped by ``search``, and their headlines read only member-searchable fields.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from django.urls import reverse

from bundesarchiv.app.web import card, ledger
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.index.query import Headline, HeadlineField, SearchFilters, SearchHit

#: The fields a why line may name, heaviest first (the ADR 0011 weights: Schlagworte B, Autor and
#: Ort C, Beschreibung D). The title never: a title holding the word needs no why line.
_WHY_ORDER: tuple[HeadlineField, ...] = ("tags", "creator", "subject_place", "body")
_LABELS = {f.name: f.label for f in card.FIELDS}

#: The ledger columns the facts line prints, in its order.
_FACTS = tuple(
    next(c for c in ledger.COLUMNS if c.key == key)
    for key in ("date", "type", "collection", "digital", "ref-code")
)


@dataclass(frozen=True, slots=True)
class Why:
    """Where a hit matched: the field's label and its excerpt as runs, ``True`` on a matched word,
    with "…" where the excerpt leaves out its field's start or end."""

    label: str
    runs: tuple[tuple[str, bool], ...]


@dataclass(frozen=True, slots=True)
class Row:
    """One hit as the Lesesaal prints it. ``draft`` and ``template`` are the archivist's marks."""

    title: str
    href: str
    draft: bool
    template: bool
    why: Why | None
    text_hits: ledger.TextHits | None
    facts: tuple[str, ...]


def why(headlines: Sequence[Headline]) -> Why | None:
    """The why line for a hit's headlines: none when its title holds the word, else the heaviest
    field that does (``None`` when the query matched no field, only a page or the Signatur)."""
    by_field = {h.field: h for h in headlines}
    if "title" in by_field:
        return None
    found = next((by_field[f] for f in _WHY_ORDER if f in by_field), None)
    if found is None:
        return None
    start = (("… ", False),) if found.cut_start else ()
    end = ((" …", False),) if found.cut_end else ()
    return Why(_LABELS[found.field], (*start, *found.runs, *end))


def rows(
    hits: Sequence[SearchHit],
    *,
    filters: SearchFilters,
    params: Mapping[str, str],
    is_archivist: bool,
    chooser: CollectionChooser,
) -> tuple[Row, ...]:
    """The rows for one page of hits; ``params`` is the search state, which leaves out the facts
    its filters already say (as the ledger leaves out their columns)."""
    facts = ledger.unfiltered(_FACTS, params)
    return tuple(
        Row(
            title=hit.title,
            href=reverse("article-detail", args=[hit.ulid]),
            draft=ledger.draft_mark(hit, filters, is_archivist=is_archivist),
            template=ledger.template_mark(hit, filters, is_archivist=is_archivist),
            why=why(hit.headlines),
            text_hits=ledger.text_hits(hit),
            facts=tuple(text for c in facts if (text := c.value(hit, chooser))),
        )
        for hit in hits
    )
