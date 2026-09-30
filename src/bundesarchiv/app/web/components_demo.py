"""Dev-only component library page (``/_dev/components/``).

Referenced ONLY from ``dev_urls`` (the switcher pattern): production settings never mount it, so
it is unreachable in prod by absence of a code path, not by a flag. It renders every design-system
component (``templates/components/``), each shown side-by-side in light and dark — the two columns
force ``color-scheme`` per container, and ``light-dark()`` resolves per element, so both modes
render in one document without JS.

ONE theme (owner ruling, 2026-08-06): design iterations happen ON the real components.

Doubles as developer documentation: every sample is annotated with its include path + params, and
a token-swatch section shows the monochrome ink/ground pairs and the lines with role names.
Page chrome is English (development-facing); the SAMPLE CONTENT inside atoms is German (product
UI copy). Sample data below is inert demo fixture data — no store, no index, no viewer.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.templatetags.static import static

from bundesarchiv.app.web import browse, ledger
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.index.query import FileKind, SearchHit

#: Both color-scheme values, in render order — the template's per-sample column loop.
_MODES = ("light", "dark")

_SORT_OPTIONS = (
    ("relevanz", "Relevanz"),
    ("signatur", "Signatur"),
    ("datierung", "Datierung"),
    ("titel", "Titel"),
)

#: Ledger sample hits — the known demo set, printed through the REAL ``ledger.build``. The draft
#: carries a Signatur (the lifecycle rides the title as its mark); one Signatur sits at the domain
#: ceiling (owner 2026-08-07: no spaces, 8 characters); the last three show absence as absence.
_LEDGER_HITS = tuple(
    SearchHit(
        ulid=f"01KDEMQ0000000000000000{n:03d}",
        title=title,
        ref_code=ref or None,
        date_edtf=date or None,
        media_type=None,
        document_type=typ or None,
        is_draft=draft,
        tier="PUBLIC",
        groups=(),
        collection_id="",
        file_counts=files,
    )
    for n, (title, ref, date, typ, draft, files) in enumerate(
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

#: The demo ledger is sorted by Signatur, ascending, so one head shows its direction.
_LEDGER_QUERY = {"sortierung": "signatur"}


def _demo_ledger() -> ledger.Ledger:
    return ledger.build(
        _LEDGER_HITS,
        columns=ledger.DEFAULT_COLUMNS,
        parsed=browse.parse_query(_LEDGER_QUERY),
        params=_LEDGER_QUERY,
        auswahl=(),
        is_archivist=True,
        selected_ulid=None,
        bestand=BestandChooser(lambda: ()),
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
        ("seite=1", "seite=3", 51, "51\N{EN DASH}100", 2506, "2.506"),
        (None, "seite=2", 1, "1\N{EN DASH}50", 2506, "2.506"),
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
    """GET: the component library — the ONE baseline stylesheet (components.css).

    Never mounted in production."""
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
        },
    )
