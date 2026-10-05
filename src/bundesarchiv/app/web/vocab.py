"""Controlled vocabulary + the display spellings (Part 4.7, spec §3/§4).

Pure presentation helpers, IO-free and request-free so the form controller and its tests read
one source with no database:

- ``MEDIENART_DOKUMENTTYP`` — the Medienart→Dokumenttyp vocabulary. The words are the ARCHIVISTS'
  data, not a design decision: ``MEDIENARTEN`` and ``DOKUMENTTYPEN`` are the legacy archive's own
  lists, verbatim and in legacy order, so the imported records keep the terms their catalogers
  wrote. Every Medienart offers the whole Dokumenttyp list until the archivists narrow it; the
  mapping, not the accessors, is what changes then. It sits behind ``media_types`` /
  ``document_types_for`` / ``is_valid_pair`` / ``grouped_document_type_options`` — ONE accessor set
  so the dependent-select render (no-JS baseline), the server-side pair re-validation, and the HTMX
  ``/dokumenttypen`` endpoint never derive the vocabulary twice.
- ``datierung_parts`` / ``human_size`` — how the article page spells a date (``<time>`` parts) and
  the edit form a file's size. Display helpers: they never validate, so they cannot be an error surface.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from bundesarchiv.domain.access import VisibilityPreview
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.index.query import FileKind

#: The Medienarten, verbatim and in the legacy archive's order — the words its catalogers used.
MEDIENARTEN: tuple[str, ...] = (
    "Audiodatei",
    "Buch",
    "CD / DVD",
    "Dia(s)",
    "Fahne / Wimpel",
    "Filmspule",
    "Foto(s)",
    "Gegenstand",
    "Kassette",
    "Schallplatte",
    "Schrifttum",
    "Sonstiges",
    "Stempel",
    "Tonband",
    "VHS",
    "Videodatei",
    "Wappen und Zeichen",
)

#: The Dokumenttypen, verbatim and in the legacy lookup table's order.
DOKUMENTTYPEN: tuple[str, ...] = (
    "Adressverzeichnis",
    "Chronik / Dokumentation",
    "Fahrtenbericht",
    "Kalender",
    "Lagerheft",
    "Lebensbericht",
    "Liederbuch",
    "Ordnung",
    "Protokoll",
    "Reden",
    "Schöpferisches (Gedicht, Lieder, ...)",
    "Schriftwechsel",
    "Sonstiges",
    "Zeitschrift",
    "Zeitungsartikel",
    "Urkunde",
)

#: Medienart → the Dokumenttypen it offers. Insertion order is the render order of the Medienart
#: select. Uniform today: narrowing a Medienart is the archivists' call, and until they make it no
#: legacy pair can be refused by a narrowing nobody asked for.
MEDIENART_DOKUMENTTYP: dict[str, tuple[str, ...]] = dict.fromkeys(MEDIENARTEN, DOKUMENTTYPEN)

#: The single optgroup's label while every Medienart shares one Dokumenttyp list.
ALLE_MEDIENARTEN = "Alle Medienarten"


def media_types() -> tuple[str, ...]:
    """The Medienart values the select offers, in vocabulary order (the mapping's keys)."""
    return tuple(MEDIENART_DOKUMENTTYP)


def media_type_options() -> tuple[tuple[str, str], ...]:
    """The Medienart ``<select>`` options: the placeholder first (empty value, server-rejected), then
    the vocabulary in order. The 4.7 edit form, the workbench bulk drawer, and the bulk view all
    render the SAME options from here — one source so the placeholder string never drifts."""
    return (("", "— Medienart wählen —"), *((m, m) for m in media_types()))


def document_types_for(media_type: str) -> tuple[str, ...]:
    """The Dokumenttyp values belonging to ``media_type``, or ``()`` for an unknown/empty one."""
    return MEDIENART_DOKUMENTTYP.get(media_type, ())


def is_valid_pair(media_type: str | None, document_type: str | None) -> bool:
    """Is the (Medienart, Dokumenttyp) pair well-formed? A ``None`` Dokumenttyp is always valid (the
    field is optional). A present Dokumenttyp must belong to a present Medienart's list — the
    server-side re-validation that rejects a mismatched pair even with JS off (spec §5, §8)."""
    if document_type is None:
        return True
    if media_type is None:
        return False
    return document_type in document_types_for(media_type)


def grouped_document_type_options() -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """The dependent Dokumenttyp options as ``(label, ((value, caption), ...))`` tuples — the
    ``<optgroup>``s of the no-JS baseline, which renders every choice so an archivist without JS can
    still pick a valid pair (spec §5); the server re-validates either way.

    While every Medienart offers the same list there is ONE group: 17 identical optgroups would be
    noise, not guidance. Once the archivists narrow a Medienart the grouping is per Medienart again.
    """
    offered = set(MEDIENART_DOKUMENTTYP.values())
    if len(offered) == 1:
        return ((ALLE_MEDIENARTEN, tuple((t, t) for t in offered.pop())),)
    return tuple(
        (media_type, tuple((t, t) for t in types))
        for media_type, types in MEDIENART_DOKUMENTTYP.items()
    )


# --- Sichtbarkeit (audience) German labels -----------------------------------------

#: The German Sichtbarkeit rung captions — the ONE source for the ladder's user-facing words. Every
#: audience-label helper across the web slice (the archivist ledger, the CAS diff, the publish
#: preview, the read-only Bestand row) formats from these, so a wording change is a one-place edit and
#: the strings can never drift between screens. ``SICHTBARKEIT_ERBEN`` is the ADR-0001 inherit default.
SICHTBARKEIT_ERBEN = "Vom Bestand erben"
SICHTBARKEIT_PUBLIC = "Öffentlich"
SICHTBARKEIT_MEMBERS = "Alle Mitglieder"
#: The GROUPS rung's caption where no group NAMES are known yet — the Sichtbarkeit ``<select>``'s own
#: option, chosen together with the Gruppen field. ``groups_label`` spells the same rung once the
#: names exist; both live here so the form's option list is not a second source (law C7).
SICHTBARKEIT_GRUPPEN = "Gruppe(n)"


#: The Sichtbarkeit select options: (value, caption). The empty value is the inherit default (ADR
#: 0001); the rest map to the audience rungs. GROUPS is chosen together with the Gruppen field.
SICHTBARKEIT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", SICHTBARKEIT_ERBEN),
    ("public", SICHTBARKEIT_PUBLIC),
    ("members", SICHTBARKEIT_MEMBERS),
    ("groups", SICHTBARKEIT_GRUPPEN),
)


def sichtbarkeit_value(audience: Audience | None) -> str:
    """The Sichtbarkeit select value for a stored audience: empty (inherit) for ``None``, else the
    rung's value."""
    if audience is None:
        return ""
    match audience.tier:
        case AudienceTier.PUBLIC:
            return "public"
        case AudienceTier.MEMBERS:
            return "members"
        case AudienceTier.GROUPS:
            return "groups"


def exposure_label(result: VisibilityPreview) -> str:
    """Who gains sight once the record is published (spec §6.2): the widest rung ``preview()``
    reports, as its rung caption."""
    if result.public:
        return SICHTBARKEIT_PUBLIC
    if result.groups:
        return groups_label(result.groups)
    if result.members:
        return SICHTBARKEIT_MEMBERS
    return "Niemand (kein Bestand-Zugriff)"


def publish_statement(result: VisibilityPreview) -> str:
    """The Veröffentlichen confirmation (a3 round 7): who sees the record once published, from the
    same ``preview()`` as ``exposure_label``."""
    if result.public:
        return "Nach dem Veröffentlichen ist dieser Artikel öffentlich."
    if result.groups:
        gruppe = "Gruppe" if len(result.groups) == 1 else "Gruppen"
        return (
            f"Nach dem Veröffentlichen sehen nur Mitglieder der {gruppe} "
            f"{', '.join(result.groups)} diesen Artikel."
        )
    if result.members:
        return "Nach dem Veröffentlichen sehen alle Mitglieder diesen Artikel."
    return "Nach dem Veröffentlichen sieht niemand außer dem Archiv diesen Artikel."


@dataclass(frozen=True, slots=True)
class DeleteConfirm:
    """A delete confirm's words (a3 ``loeschen.html``): the question, what happens, and the one
    button, which names all of it."""

    question: str
    consequence: str
    button: str


#: The state-H hinweis (ADR 0014), shown when a save's index update lagged.
INDEX_LAG = "Gespeichert. Die Suche zeigt die Änderung in Kürze."
BULK_INDEX_LAG = "Die Suche zeigt einige Änderungen in Kürze."


#: "Löschen" puts the record in the Papierkorb, so its confirm says where it goes (ADR 0022).
TRASH_CONFIRM = DeleteConfirm(
    question="Artikel löschen?",
    consequence="Er kommt in den Papierkorb. Dort kannst du ihn wiederherstellen.",
    button="In den Papierkorb",
)


def delete_permanently_confirm(files: int) -> DeleteConfirm:
    """The Papierkorb's final confirm for a record with ``files`` files."""
    dateien = numbered(files, *_FILE_WORDS[FileKind.OTHER])
    gone = (
        "Gelöscht werden der Katalogeintrag mit allen Angaben und seine "
        f"{_files(FileKind.OTHER, files)}."
        if files
        else "Gelöscht wird der Katalogeintrag mit allen Angaben."
    )
    return DeleteConfirm(
        question="Endgültig löschen?",
        consequence=f"{gone} Das lässt sich nicht rückgängig machen.",
        button=f"Artikel und {dateien} endgültig löschen" if files else "Artikel endgültig löschen",
    )


def day(at: datetime) -> str:
    """The day of a UTC timestamp as the archive lives it (Berlin): ``01.10.2026``."""
    return f"{at.astimezone(_BERLIN):%d.%m.%Y}"


_BERLIN = ZoneInfo("Europe/Berlin")


def groups_label(groups: tuple[str, ...]) -> str:
    """The GROUPS-rung caption: ``Gruppe: <name>, <name>``. The one place the group list is joined."""
    return "Gruppe: " + ", ".join(groups)


def sichtbarkeit_label(audience: Audience | None) -> str:
    """An ``Audience`` (or ``None`` = inherit) as its human-German Sichtbarkeit caption. Shared by the
    4.7 CAS diff and the 4.8 read-only Bestand row (both hold an ``Audience | None``); the ledger and
    the publish preview, which start from other shapes, reuse the same rung strings above."""
    if audience is None:
        return SICHTBARKEIT_ERBEN
    match audience.tier:
        case AudienceTier.PUBLIC:
            return SICHTBARKEIT_PUBLIC
        case AudienceTier.MEMBERS:
            return SICHTBARKEIT_MEMBERS
        case AudienceTier.GROUPS:
            return groups_label(audience.groups)


# --- EDTF: the two spellings, one renderer each (law C7) ---------------------------


def datierung_mono(date: EdtfDate | None) -> str:
    """The MACHINE date: the EDTF value verbatim, or ``""`` when absent. The ONE renderer for the
    mono machine spelling — the ledger's date column, the preview pane's meta line, the CAS diff and
    the Datierung field's own value all print it, so a single spelling of the fact cannot fork into
    inline copies of ``date.value if date is not None else ""``. Its sibling is ``datierung_parts``,
    the same text split for ``<time>``."""
    return date.value if date is not None else ""


# --- the article page's spellings ---------------------------------------------------

#: A token HTML can date: a year, a month or a day (``<time datetime>``).
_HTML_DATE = re.compile(r"\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?")


@dataclass(frozen=True, slots=True)
class DatePart:
    """One EDTF token of a date as the page prints it: ``text`` the human German spelling ("Juli
    1962", "um 1963"), ``datetime`` the machine value HTML understands, or ``""`` where there is
    none (a decade, a season, an open end)."""

    text: str
    datetime: str


def datierung_parts(date: EdtfDate | None) -> tuple[DatePart, ...]:
    """The date as ``<time>`` parts: one, or two for an interval. No date → ``()``."""
    if date is None:
        return ()
    return tuple(DatePart(_spoken(token), _html_date(token)) for token in date.value.split("/"))


_MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
_SEASONS = {"21": "Frühling", "22": "Sommer", "23": "Herbst", "24": "Winter"}
_TOKEN = re.compile(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def _spoken(token: str) -> str:
    """One EDTF token in words: "5. Juli 1962", "Sommer 1962", "1970er", "um 1963", "1963?". A
    token this does not know reads verbatim."""
    core = token.rstrip("?~%")
    qualifier = token[len(core) :]
    if core == "..":
        return "…"
    if core.endswith("XX"):
        words = f"{core[:2]}00\N{EN DASH}{core[:2]}99"
    elif core.endswith("X"):
        words = f"{core[:3]}0er"
    elif (m := _TOKEN.fullmatch(core)) is None:
        return token
    elif (part := m.group(2)) in _SEASONS:
        words = f"{_SEASONS[part]} {m.group(1)}"
    else:
        year, month, day = m.groups()
        words = " ".join(
            w
            for w in (f"{int(day)}." if day else "", _MONTHS[int(month) - 1] if month else "", year)
            if w
        )
    approx = "um " if set(qualifier) & {"~", "%"} else ""
    uncertain = "?" if set(qualifier) & {"?", "%"} else ""
    return f"{approx}{words}{uncertain}"


def _html_date(token: str) -> str:
    core = token.rstrip("?~%")
    return core if _HTML_DATE.fullmatch(core) else ""


#: Each file kind as the Digital column spells it: (one, several). One file carries no number.
_FILE_WORDS: dict[FileKind, tuple[str, str]] = {
    FileKind.IMAGE: ("Foto", "Fotos"),
    FileKind.PDF: ("PDF", "PDF"),
    FileKind.VIDEO: ("Video", "Videos"),
    FileKind.AUDIO: ("Audio", "Audios"),
    FileKind.OTHER: ("Datei", "Dateien"),
}


#: Each file kind as the "+ Filter" panel and the search sentence name the filter.
FILE_FILTER_LABELS: dict[FileKind, str] = {
    FileKind.IMAGE: "mit Fotos",
    FileKind.PDF: "mit PDF",
    FileKind.VIDEO: "mit Video",
    FileKind.AUDIO: "mit Audio",
    FileKind.OTHER: "mit anderen Dateien",
}


def file_summary(counts: tuple[tuple[FileKind, int], ...]) -> str:
    """What files a record has, as the Digital column says it ("Foto, PDF", "2 Fotos"). ``()`` →
    empty. ``counts`` is ``SearchHit.file_counts``: kinds in summary order, zero kinds left out."""
    return ", ".join(_files(kind, n) for kind, n in counts)


#: The article page's plate register, headed by what it holds.
#: The undated Articles' word: the start page's Zeitleiste row and the list's decade slot.
UNDATED = "Unbekannt"

FURTHER_IMAGES = "Weitere Aufnahmen"
FURTHER_FILES = "Weitere Dateien"


def file_word(kind: FileKind) -> str:
    """One file of ``kind``, as a tile names it: "PDF", "Foto"."""
    return _FILE_WORDS[kind][0]


def _files(kind: FileKind, n: int) -> str:
    """``n`` files of ``kind``, one without its number: "Foto", "2 Fotos"."""
    singular, plural = _FILE_WORDS[kind]
    return singular if n == 1 else numbered(n, singular, plural)


def numbered(n: int, singular: str, plural: str) -> str:
    """``n`` of a thing, spelled out: "1 Datei", "3 Dateien"."""
    return f"{n} {singular if n == 1 else plural}"


def count(number: int) -> str:
    """A count in German spelling, thousands grouped by a dot ("2.506")."""
    return f"{number:,}".replace(",", ".")


def human_size(byte_size: int | None) -> str:
    """A file size in German spelling ("1,2 GB"). Absent → empty."""
    if byte_size is None:
        return ""
    size, unit = float(byte_size), "B"
    for bigger in ("KB", "MB", "GB"):
        if size < 1024:
            break
        size, unit = size / 1024, bigger
    return f"{byte_size} B" if unit == "B" else f"{size:.1f} {unit}".replace(".", ",")
