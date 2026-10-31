"""Dev-only component library: English chrome, German samples, inert data."""

import re
from pathlib import Path
from typing import NamedTuple

import yaml
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.templatetags.static import static

from bundesarchiv.app.web import browse, ledger, start, vocab
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.start import Tile
from bundesarchiv.domain.models import ULID
from bundesarchiv.index.query import FileKind, SearchHit, TextPage

ROOT = Path(__file__).resolve().parents[4]
DESIGN_SYSTEM = ROOT / "docs" / "design" / "design-system.md"
#: Holds ``components/`` and ``layouts/``: the contracts, which own a linked row's status.
CONTRACTS = ROOT / "design-system"

_LINK = re.compile(r"\[contract\]\(\.\./\.\./design-system/(\w+)/([^/()]+)\.md\)")
_CONTRACT_STATUSES = ("hidden", "discoverable", "deprecated")


class InventoryRow(NamedTuple):
    name: str
    root: str
    where: str
    section: str
    status: str


class FamilyRow(NamedTuple):
    name: str
    members: tuple[str, ...]
    section: str
    status: str


class Contract(NamedTuple):
    id: str
    status: str


def _cells(heading: str, document: Path) -> list[list[str]]:
    """The body cells of one table in the design-system document (its ``### heading``)."""
    section = document.read_text().split(f"### {heading}\n", 1)[1].split("\n#", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")][2:]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]


def inventory(heading: str, document: Path = DESIGN_SYSTEM) -> tuple[InventoryRow, ...]:
    """The rows of one inventory table (components or layout primitives)."""
    return tuple(
        InventoryRow(c[0], c[1].strip("`"), c[2], c[3], c[-1]) for c in _cells(heading, document)
    )


def families(document: Path = DESIGN_SYSTEM) -> tuple[FamilyRow, ...]:
    """The rows of the families table: components sharing one CSS section (component rule 4)."""
    return tuple(
        FamilyRow(c[0], tuple(m.strip(" `") for m in c[1].split(",")), c[2], c[-1])
        for c in _cells("Families", document)
    )


def contract_link(status_cell: str) -> tuple[str, str] | None:
    """The (directory, id) a Status cell links its contract by, or None for any other cell."""
    link = _LINK.fullmatch(status_cell)
    return (link[1], link[2]) if link else None


def parse_contract(text: str) -> Contract:
    """The id and status of a contract's frontmatter; ValueError names what is wrong."""
    parts = text.split("---\n", 2)
    if parts[0] or len(parts) < 3:
        raise ValueError("no frontmatter")
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as error:
        raise ValueError("frontmatter does not parse") from error
    contract_id = meta.get("id") if isinstance(meta, dict) else None
    status = meta.get("status") if isinstance(meta, dict) else None
    if not contract_id:
        raise ValueError("frontmatter has no id")
    if status not in _CONTRACT_STATUSES:
        raise ValueError(f"status {status!r} is not one of {', '.join(_CONTRACT_STATUSES)}")
    return Contract(str(contract_id), status)


def library_status(document: Path = DESIGN_SYSTEM, contracts: Path = CONTRACTS) -> dict[str, str]:
    """Per component, the status line the library shows beside its samples: its own and its
    families'. A linked row shows its contract's status, as is."""

    def shown(cell: str) -> str:
        link = contract_link(cell)
        if link is None:
            return cell
        return (
            "contract: "
            + parse_contract((contracts / link[0] / f"{link[1]}.md").read_text()).status
        )

    family_rows = families(document)
    return {
        row.name.lower().replace(" ", "_"): " \N{MIDDLE DOT} ".join(
            [
                shown(row.status),
                *(f"{f.name}: {shown(f.status)}" for f in family_rows if row.root in f.members),
            ]
        )
        for row in inventory("Component inventory", document)
    }


#: Both color-scheme values, in render order — the template's per-sample column loop.
_MODES = ("light", "dark")

_SORT_OPTIONS = (
    ("relevance", "Relevanz"),
    ("ref_code", "Signatur"),
    ("date", "Datierung"),
    ("title", "Titel"),
)

#: A draft with a Signatur, one Signatur at the owner's 8-character ceiling, and three rows
#: missing facts.
_LEDGER_HITS = tuple(
    SearchHit(
        ulid=ULID(f"01KDEMQ0000000000000000{n:03d}"),
        title=title,
        ref_code=ref or None,
        date_edtf=date or None,
        media_type=None,
        document_type=doc_type or None,
        is_draft=draft,
        collection_id=ULID(""),
        file_counts=files,
    )
    for n, (title, ref, date, doc_type, draft, files) in enumerate(
        (
            ("Sommerfahrt 1962", "F12", "1962", "Fahrtenbericht", False, ((FileKind.IMAGE, 2),)),
            ("Jahresbericht 1974", "B3/1974a", "1974", "Chronik / Dokumentation", False, ()),
            (
                "Vorstandsprotokoll März 1980",
                "V7",
                "1980-03",
                "Protokoll",
                False,
                ((FileKind.PDF, 1),),
            ),
            (
                "Lagerchronik",
                "C5",
                "1984",
                "Lagerheft",
                True,
                ((FileKind.IMAGE, 1), (FileKind.PDF, 1)),
            ),
            ("Undatierter Zugang", "Z1", "1990", "", False, ()),
            ("Lose Notiz", "", "", "Sonstiges", False, ()),
            ("Ohne Datierung und Typ", "", "", "", False, ()),
        )
    )
)

#: A hit that matched on five pages of its PDF: its row prints the capped "Im Volltext" line.
_TEXT_HIT = SearchHit(
    ulid=ULID("01KDEMQ0000000000000000007"),
    title="Gaubrief Herbst 1971",
    ref_code="G4",
    date_edtf="1971",
    media_type=None,
    document_type="Zeitschrift",
    is_draft=False,
    collection_id=ULID(""),
    file_counts=((FileKind.PDF, 1),),
    text_pages=tuple(TextPage("0" * 64, page) for page in (4, 9, 14, 22, 31)),
)

#: The demo ledger is sorted by Signatur, ascending, so one head shows its direction.
_LEDGER_QUERY = {"sort": "ref_code"}


def _demo_ledger() -> ledger.Ledger:
    return ledger.build(
        (_TEXT_HIT, *_LEDGER_HITS),
        columns=ledger.DEFAULT_COLUMNS,
        parsed=browse.parse_query(_LEDGER_QUERY),
        params=_LEDGER_QUERY,
        selection=(),
        is_archivist=True,
        selected_ulid=None,
        chooser=CollectionChooser(lambda: ()),
    )


#: The page-size chooser of a pager sample, keyed like browse_views._PageSize: the default on
#: screen.
_PAGE_SIZES = tuple(
    {"label": str(size), "query": None if size == browse.PAGE_SIZE else f"page_size={size}"}
    for size in browse.PAGE_SIZES
)

#: Pager samples, keyed like browse_views._Pager: page 2 of many, page 1 of many, one page.
_PAGERS = tuple(
    {
        "stepped": nxt is not None,
        "prev_query": prev,
        "next_query": nxt,
        "first": first,
        "shown": shown,
        "total": total,
        "total_label": label,
        "noun": "Einträge",
        "sizes": _PAGE_SIZES,
    }
    for prev, nxt, first, shown, total, label in (
        ("page=1", "page=3", 51, "51\N{EN DASH}100", 2506, "2.506"),
        (None, "page=2", 1, "1\N{EN DASH}50", 2506, "2.506"),
        (None, None, 1, "1\N{EN DASH}4", 4, "4"),
    )
)

#: Medienarten most first, for the expandable list: five rows, so N = 3 folds two.
_EXPANDABLE = tuple(
    Tile(label, count, vocab.count(count), "#demo-expandable")
    for label, count in (
        ("Foto(s)", 1840),
        ("Dokument", 912),
        ("Zeitschrift", 305),
        ("Plakat", 41),
        ("Tonband", 6),
    )
)
#: The samples, each (rows shown, open): closed at N = 3, open at N = 3, and N = 4, which folds
#: nothing.
_EXPANDABLE_SAMPLES = (
    (start.shown(len(_EXPANDABLE), 3), False),
    (start.shown(len(_EXPANDABLE), 3), True),
    (start.shown(len(_EXPANDABLE), 4), False),
)

#: Token swatches: (background role, text role) pairs, then the line roles.
_SWATCH_PAIRS = (
    ("ground", "ink"),
    ("ground", "ink-2"),
    ("ground", "ink-3"),
    ("ink", "ground"),
    ("error", "ground"),
    ("band-ground", "band-ink"),
    ("band-ground", "band-ink-2"),
)
_SWATCH_LINES = ("rule", "edge", "faint")


def component_library(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "components_demo.html",
        {
            "stylesheet": static("components.css"),
            "modes": _MODES,
            "sort_options": _SORT_OPTIONS,
            "swatch_pairs": _SWATCH_PAIRS,
            "swatch_lines": _SWATCH_LINES,
            "ledger": _demo_ledger(),
            "pagers": _PAGERS,
            "expandable": _EXPANDABLE,
            "expandable_samples": _EXPANDABLE_SAMPLES,
            "status": library_status(),
        },
    )
