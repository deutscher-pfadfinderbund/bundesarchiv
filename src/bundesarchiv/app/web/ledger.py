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

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from django.urls import reverse

from bundesarchiv.app.web import browse, vocab
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.index.query import SearchHit


@dataclass(frozen=True, slots=True)
class Column:
    """One column after the Titel: its key (the CSS class and the stored choice), its head, the
    sort label it sorts by (``None``: not sortable), the filter param its cell sets (``None``: the
    cell is plain text), how a hit spells its value, and the value the filter takes when the
    words are not it (a Bestand's name stands for its ulid)."""

    key: str
    label: str
    sort: str | None
    filter: str | None
    value: Callable[[SearchHit, CollectionChooser], str]
    filter_value: Callable[[SearchHit], str] | None = None


COLUMNS: tuple[Column, ...] = (
    Column("date", "Datierung", "datierung", None, lambda hit, _: hit.date_edtf or ""),
    Column("type", "Typ", None, browse.PARAM_DOCUMENT_TYPE, lambda hit, _: hit.document_type or ""),
    Column("digital", "Digital", None, None, lambda hit, _: vocab.file_summary(hit.file_counts)),
    Column("ref-code", "Signatur", "signatur", None, lambda hit, _: hit.ref_code or ""),
    Column(
        "collection",
        "Bestand",
        None,
        browse.PARAM_COLLECTION,
        lambda hit, b: b.name_of(hit.collection_id) or "",
        lambda hit: hit.collection_id,
    ),
)

#: The columns a ledger shows until its viewer chooses (the a2 mock's set).
DEFAULT_COLUMNS: tuple[Column, ...] = tuple(c for c in COLUMNS if c.key != "collection")

#: The cookie keeping a viewer's chosen columns: a per-person preference, so it never enters the
#: URL (ruling 2026-09-29). It holds registry keys only, joined by ``_SEP``; ``_NONE`` is the choice
#: of no column at all, which an empty value could not tell apart from no choice.
COOKIE = "spalten"
COOKIE_MAX_AGE = 365 * 24 * 60 * 60
_SEP = "."
_NONE = "-"


def cookie_value(keys: Iterable[str]) -> str:
    """The cookie value for the posted column keys: the known ones, in registry order."""
    wanted = frozenset(keys)
    return _SEP.join(c.key for c in COLUMNS if c.key in wanted) or _NONE


def chosen(raw: str | None) -> tuple[Column, ...]:
    """The columns a cookie value chose, in registry order. An unknown key is dropped; a value
    naming no known column (absent, empty, garbage) is the default set, never an error."""
    if raw == _NONE:
        return ()
    keys = frozenset((raw or "").split(_SEP))
    return tuple(c for c in COLUMNS if c.key in keys) or DEFAULT_COLUMNS


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
    """One hit as the ledger prints it. ``draft`` and ``gewaehlt`` are the archivist's chrome,
    False for everyone else; ``selected`` marks the row in the pane."""

    ulid: str
    title: str
    href: str
    draft: bool
    selected: bool
    gewaehlt: bool
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class Choice:
    """One entry of the "Spalten …" check list."""

    key: str
    label: str
    chosen: bool


@dataclass(frozen=True, slots=True)
class Ledger:
    """The result table: the heads (Titel first), one row per hit with cells in head order, and
    the column choices the "Spalten …" panel offers."""

    heads: tuple[Head, ...]
    rows: tuple[Row, ...]
    choices: tuple[Choice, ...]


def build(
    hits: Sequence[SearchHit],
    *,
    columns: Sequence[Column],
    parsed: browse.ParsedQuery,
    params: Mapping[str, str],
    selection: Sequence[str],
    is_archivist: bool,
    selected_ulid: str | None,
    chooser: CollectionChooser,
) -> Ledger:
    """The ledger for one page of hits. ``params`` is the search state every link builds from
    (the pane and selected_ulids params already dropped); ``columns`` the chosen ones, printed in
    registry order."""
    shown = tuple(c for c in COLUMNS if c in columns and not _filtered(c, params))
    active = browse.sort_label(parsed.sort)
    heads = (
        _head("title", "Titel", "titel", active, parsed.descending, params),
        *(_head(c.key, c.label, c.sort, active, parsed.descending, params) for c in shown),
    )
    selected_ulids = frozenset(selection) if is_archivist else frozenset()
    mark_drafts = is_archivist and not parsed.filters.drafts_only
    rows = tuple(
        Row(
            ulid=hit.ulid,
            title=hit.title,
            href=reverse("article-detail", args=[hit.ulid]),
            draft=mark_drafts and hit.is_draft,
            selected=hit.ulid == selected_ulid,
            gewaehlt=hit.ulid in selected_ulids,
            cells=tuple(_cell(c, hit, chooser, params) for c in shown),
        )
        for hit in hits
    )
    choices = tuple(Choice(c.key, c.label, c in columns) for c in COLUMNS)
    return Ledger(heads=heads, rows=rows, choices=choices)


def _filtered(column: Column, params: Mapping[str, str]) -> bool:
    return column.filter is not None and bool(params.get(column.filter, "").strip())


def _cell(
    column: Column, hit: SearchHit, chooser: CollectionChooser, params: Mapping[str, str]
) -> Cell:
    text = column.value(hit, chooser)
    if column.filter is None or not text:
        return Cell(column.key, text)
    value = column.filter_value(hit) if column.filter_value else text
    return Cell(column.key, text, browse.with_param(params, column.filter, value))


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
