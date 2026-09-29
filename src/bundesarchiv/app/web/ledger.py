"""The ledger's columns and rows: one column registry, one typed view-model (debt #8).

``COLUMNS`` is the one list of the columns a ledger may show after the Titel, which every ledger
shows first. The chooser offers exactly these and the ledger prints them in this order, so a new
column is one entry. ``build`` turns a page of ``SearchHit`` s into a ``Ledger`` the templates only
print: every link is a finished query string, every cell finished text.

A column whose filter is set is left out: every row would repeat the one value the filter holds
(round 11; LEARNINGS lesson 16). No visibility logic lives here — the hits are already
viewer-scoped by ``search``; the archivist's chrome (the Entwurf mark, Bearbeiten, the selection)
is a presentation gate on ``is_archivist``.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from django.urls import reverse

from bundesarchiv.app.web import browse, vocab
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.index.query import SearchHit

#: The preview-pane selection param. NOT search state: every search link drops it.
PANE_PARAM = "artikel"


@dataclass(frozen=True, slots=True)
class Column:
    """One column after the Titel: its key (the CSS class and the stored choice), its head, the
    sort label it sorts by (``None``: not sortable), the filter param its cell sets (``None``: the
    cell is plain text) and how a hit spells its value."""

    key: str
    label: str
    sort: str | None
    filter: str | None
    value: Callable[[SearchHit, BestandChooser], str]


COLUMNS: tuple[Column, ...] = (
    Column("datierung", "Datierung", "datierung", None, lambda hit, _: hit.date_edtf or ""),
    Column("typ", "Typ", None, browse.PARAM_DOCUMENT_TYPE, lambda hit, _: hit.document_type or ""),
    Column("digital", "Digital", None, None, lambda hit, _: vocab.file_summary(hit.file_counts)),
    Column("signatur", "Signatur", "signatur", None, lambda hit, _: hit.ref_code or ""),
    Column("bestand", "Bestand", None, None, lambda hit, b: b.name_of(hit.collection_id) or ""),
)

#: The columns a ledger shows until its viewer chooses (the a2 mock's set).
DEFAULT_COLUMNS: tuple[Column, ...] = tuple(c for c in COLUMNS if c.key != "bestand")


@dataclass(frozen=True, slots=True)
class Head:
    """A column head. ``query`` is the link to its NEXT sort state (``None``: not sortable);
    ``sort`` is its ``aria-sort`` value, empty unless it carries the active sort."""

    key: str
    label: str
    query: str | None = None
    sort: str = ""


@dataclass(frozen=True, slots=True)
class Cell:
    """One fact of a row. ``query`` links it (a filter it sets); empty is plain text."""

    key: str
    text: str
    query: str = ""


@dataclass(frozen=True, slots=True)
class Row:
    """One hit as the ledger prints it. ``draft``, ``bearbeiten_href`` and ``gewaehlt`` are the
    archivist's chrome, False / empty for everyone else; ``selected`` marks the row in the pane."""

    ulid: str
    title: str
    href: str
    draft: bool
    bearbeiten_href: str
    vorschau_href: str
    selected: bool
    gewaehlt: bool
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class Ledger:
    """The result table: the heads (Titel first) and one row per hit, cells in head order."""

    heads: tuple[Head, ...]
    rows: tuple[Row, ...]


def build(
    hits: Sequence[SearchHit],
    *,
    columns: Sequence[Column],
    parsed: browse.ParsedQuery,
    params: Mapping[str, str],
    auswahl: Sequence[str],
    is_archivist: bool,
    selected_ulid: str | None,
    bestand: BestandChooser,
) -> Ledger:
    """The ledger for one page of hits. ``params`` is the search state every link builds from
    (the pane and selection params already dropped); ``columns`` the chosen ones, printed in
    registry order."""
    shown = tuple(c for c in COLUMNS if c in columns and not _filtered(c, params))
    active = browse.sort_label(parsed.sort)
    heads = (
        _head("titel", "Titel", "titel", active, parsed.descending, params),
        *(_head(c.key, c.label, c.sort, active, parsed.descending, params) for c in shown),
    )
    # row-invariant: the pane link's search state + selection, encoded once per page. ULIDs are
    # Crockford base32, so the one per-row pair needs no encoding.
    state = browse.pane_query_prefix(params, auswahl)
    prefix = f"{state}&" if state else ""
    chosen = frozenset(auswahl) if is_archivist else frozenset()
    mark_drafts = is_archivist and not parsed.filters.drafts_only
    rows = tuple(
        Row(
            ulid=hit.ulid,
            title=hit.title,
            href=reverse("artikel-detail", args=[hit.ulid]),
            draft=mark_drafts and hit.is_draft,
            bearbeiten_href=(
                reverse("artikel-bearbeiten", args=[hit.ulid]) if is_archivist else ""
            ),
            vorschau_href=f"?{prefix}{PANE_PARAM}={hit.ulid}",
            selected=hit.ulid == selected_ulid,
            gewaehlt=hit.ulid in chosen,
            cells=tuple(_cell(c, hit, bestand, params) for c in shown),
        )
        for hit in hits
    )
    return Ledger(heads=heads, rows=rows)


def _filtered(column: Column, params: Mapping[str, str]) -> bool:
    return column.filter is not None and bool(params.get(column.filter, "").strip())


def _cell(
    column: Column, hit: SearchHit, bestand: BestandChooser, params: Mapping[str, str]
) -> Cell:
    text = column.value(hit, bestand)
    if column.filter is None or not text:
        return Cell(column.key, text)
    return Cell(column.key, text, browse.with_param(params, column.filter, text))


def _head(
    key: str,
    label: str,
    sort: str | None,
    active: str,
    descending: bool,
    params: Mapping[str, str],
) -> Head:
    """A head's link cycles its sort: ascending, then descending, then back to the default."""
    if sort is None:
        return Head(key, label)
    if active != sort:
        return Head(key, label, browse.with_param(params, browse.PARAM_SORT, sort))
    if not descending:
        return Head(
            key, label, browse.with_param(params, browse.PARAM_SORT, f"-{sort}"), "ascending"
        )
    return Head(key, label, browse.without_param(params, browse.PARAM_SORT), "descending")
