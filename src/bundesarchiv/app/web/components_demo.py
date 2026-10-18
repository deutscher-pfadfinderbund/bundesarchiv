"""Dev-only component library: English chrome, German samples, inert data."""

from pathlib import Path
from typing import NamedTuple

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.templatetags.static import static

from bundesarchiv.app.web import browse, ledger
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.domain.models import ULID
from bundesarchiv.index.query import FileKind, SearchHit, TextPage

DESIGN_SYSTEM = Path(__file__).resolve().parents[4] / "docs" / "design" / "design-system.md"


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


def _cells(heading: str) -> list[list[str]]:
    """The body cells of one table in design-system.md (its ``### heading``)."""
    section = DESIGN_SYSTEM.read_text().split(f"### {heading}\n", 1)[1].split("\n#", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")][2:]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]


def inventory(heading: str) -> tuple[InventoryRow, ...]:
    """The rows of one inventory table (components or layout primitives)."""
    return tuple(InventoryRow(c[0], c[1].strip("`"), c[2], c[3], c[-1]) for c in _cells(heading))


def families() -> tuple[FamilyRow, ...]:
    """The rows of the families table: components sharing one CSS section (component rule 4)."""
    return tuple(
        FamilyRow(c[0], tuple(m.strip(" `") for m in c[1].split(",")), c[2], c[-1])
        for c in _cells("Families")
    )


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
        "noun": "Artikel",
    }
    for prev, nxt, first, shown, total, label in (
        ("page=1", "page=3", 51, "51\N{EN DASH}100", 2506, "2.506"),
        (None, "page=2", 1, "1\N{EN DASH}50", 2506, "2.506"),
        (None, None, 1, "1\N{EN DASH}4", 4, "4"),
    )
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
    family_rows = families()
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
            "status": {
                row.name.lower().replace(" ", "_"): " · ".join(
                    [
                        row.status,
                        *(f"{f.name}: {f.status}" for f in family_rows if row.root in f.members),
                    ]
                )
                for row in inventory("Component inventory")
            },
        },
    )
