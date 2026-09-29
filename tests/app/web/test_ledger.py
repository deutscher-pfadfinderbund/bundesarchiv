"""The ledger's column registry and view-model, over plain SearchHits — no database, no request."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs

import pytest
from tests.app.web._fixtures import make_collection

from bundesarchiv.app.web import browse, ledger
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.index.query import FileKind, SearchHit

_ULID = "01KX6RHVHG90WHP1PZWP0GSKQQ"
_BESTAND = "01KX6RHVHG90WHP1PZWP0GSKAA"


def _hit(**overrides: Any) -> SearchHit:
    fields: dict[str, Any] = {
        "ulid": _ULID,
        "title": "Lagerheft Sommer",
        "ref_code": "BA 1842",
        "date_edtf": "1866-11-20",
        "media_type": "Schrifttum",
        "document_type": "Lagerheft",
        "is_draft": False,
        "tier": "PUBLIC",
        "groups": (),
        "collection_id": _BESTAND,
        "file_counts": ((FileKind.PDF, 1),),
    }
    return SearchHit(**(fields | overrides))


def _build(
    *hits: SearchHit,
    params: Mapping[str, str] | None = None,
    columns: tuple[ledger.Column, ...] = ledger.DEFAULT_COLUMNS,
    is_archivist: bool = False,
    drafts_only: bool = False,
) -> ledger.Ledger:
    query = dict(params or {})
    parsed = browse.parse_query(query)
    return ledger.build(
        hits or (_hit(),),
        columns=columns,
        parsed=replace(parsed, filters=replace(parsed.filters, drafts_only=drafts_only)),
        params=query,
        auswahl=(),
        is_archivist=is_archivist,
        selected_ulid=None,
        bestand=BestandChooser(lambda: (make_collection(_BESTAND, "Gau Wartburg"),)),
    )


def _column(key: str) -> ledger.Column:
    return next(c for c in ledger.COLUMNS if c.key == key)


def test_the_title_leads_the_default_columns_and_each_cell_says_its_fact() -> None:
    built = _build()
    assert [h.label for h in built.heads] == ["Titel", "Datierung", "Typ", "Digital", "Signatur"]
    assert [c.text for c in built.rows[0].cells] == ["1866-11-20", "Lagerheft", "PDF", "BA 1842"]


def test_a_typ_cell_sets_its_type_filter_and_a_set_type_filter_hides_the_column() -> None:
    (typ,) = [c for c in _build(params={"q": "sommer"}).rows[0].cells if c.key == "typ"]
    assert parse_qs(typ.query) == {"q": ["sommer"], browse.PARAM_DOCUMENT_TYPE: ["Lagerheft"]}

    filtered = _build(params={browse.PARAM_DOCUMENT_TYPE: "Lagerheft"})
    assert "typ" not in [h.key for h in filtered.heads]
    assert "typ" not in [c.key for c in filtered.rows[0].cells]


def test_the_bestand_cell_names_the_records_bestand_or_nothing() -> None:
    built = _build(_hit(), _hit(collection_id="GONE"), columns=(_column("bestand"),))
    assert [row.cells[0].text for row in built.rows] == ["Gau Wartburg", ""]


@pytest.mark.parametrize(
    ("is_archivist", "drafts_only", "marked"),
    [(True, False, True), (False, False, False), (True, True, False)],
)
def test_the_entwurf_mark_is_archivist_chrome_and_quiet_on_a_list_of_drafts(
    is_archivist: bool, drafts_only: bool, marked: bool
) -> None:
    built = _build(_hit(is_draft=True), is_archivist=is_archivist, drafts_only=drafts_only)
    assert built.rows[0].draft is marked


@pytest.mark.parametrize(
    ("sortierung", "next_sortierung", "aria_sort"),
    [
        (None, "datierung", ""),
        ("datierung", "-datierung", "ascending"),
        ("-datierung", None, "descending"),
    ],
)
def test_a_sortable_head_links_to_its_next_sort_state(
    sortierung: str | None, next_sortierung: str | None, aria_sort: str
) -> None:
    params = {browse.PARAM_SORT: sortierung} if sortierung else {}
    (head,) = [h for h in _build(params=params).heads if h.key == "datierung"]
    assert head.query is not None
    assert parse_qs(head.query).get(browse.PARAM_SORT) == (
        [next_sortierung] if next_sortierung else None
    )
    assert head.sort == aria_sort
