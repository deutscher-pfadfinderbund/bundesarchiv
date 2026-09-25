"""The legacy database → Article mapping: pure, IO-free, and read exactly once.

The old Django/filer site is exported to CSV (`var/legacy/`, see `docs/design/migration-feasibility.md`)
and imported once (owner ruling, deployment 1). This module turns parsed CSV rows into values the
`import_legacy` command writes; it opens no file, touches no store, and knows no settings, so the
whole mapping is testable as data — which is the point, because after the import the old database
is gone and anything dropped here is dropped for good.

Two rules run through it. Nothing vanishes silently: every legacy column is either in
``MAPPED_COLUMNS`` or named in ``DROPPED_COLUMNS``, and the command refuses an export whose header
is not ``ITEM_COLUMNS``. And precision is neither invented nor thrown away: a date shape the memo
does not automate falls back to the `year`/`month`/`day` columns — exactly as far as they reach —
and the cataloger's own words stay verbatim under ``DATE_TEMPLATE_KEY``.
"""

import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from bundesarchiv.domain import identity
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Article, Lifecycle, Ulid
from bundesarchiv.persistence.repository import cleaned_name

#: One of the edit form's two value lists, as this module sees it: a membership test, nothing
#: more. It is passed in (``unknown_vocabulary``) so the mapping stays below ``app.web``.
type Vocabulary = Collection[str]

#: The Bestand for the rows whose `collection` is empty — a real, visible place, not a null.
UNSORTIERT = "Unsortiert"

#: The custom key under which an unreadable date keeps its original words.
DATE_TEMPLATE_KEY = "Datum (Vorlage)"

#: How many unreadable dates the report shows by example (the count is always exact).
MAX_SAMPLES = 10

#: The `items.csv` header, in export order. The command compares the real header against this and
#: refuses a mismatch, so a column added to the old database cannot slip past the mapping.
ITEM_COLUMNS: tuple[str, ...] = (
    "id",
    "signature",
    "author",
    "title",
    "date",
    "year",
    "month",
    "day",
    "place",
    "medartanalog",
    "doctype",
    "document_type_name",
    "keywords",
    "location",
    "source",
    "notes",
    "collection",
    "amount",
    "crossreference",
    "active",
    "reviewed",
    "owner",
    "pub_date",
    "modified",
    "file_id",
    "file2_id",
    "file3_id",
)

#: The `files.csv` header, in export order.
FILE_COLUMNS: tuple[str, ...] = (
    "item_id",
    "slot",
    "filer_id",
    "path",
    "original_filename",
    "name",
    "mime_type",
    "sha1",
    "size",
    "uploaded_at",
)

#: Columns deliberately NOT carried over, and why (each reason is a fact about the export, checked
#: against it). `id` is not here: it stops being identity (a ULID replaces it) but survives as the
#: `Legacy-ID` custom field, the one thread back to the old database.
DROPPED_COLUMNS: dict[str, str] = {
    "crossreference": "empty in the whole export",
    "active": "true in every row",
    "reviewed": "true in every row",
    "pub_date": "the admin record's creation timestamp, not an archival date",
    "modified": "the admin record's last-edit timestamp",
    "file_id": "the item→file join lives in files.csv",
    "file2_id": "the item→file join lives in files.csv",
    "file3_id": "the item→file join lives in files.csv",
}

#: The columns `map_item` reads, one by one. Spelled out rather than derived as "everything not
#: dropped": derived, the coverage gate would agree with itself whatever the drop list said, and a
#: new legacy column could still arrive unread.
MAPPED_COLUMNS: tuple[str, ...] = (
    "id",
    "signature",
    "author",
    "title",
    "date",
    "year",
    "month",
    "day",
    "place",
    "medartanalog",
    "doctype",
    "document_type_name",
    "keywords",
    "location",
    "source",
    "notes",
    "collection",
    "amount",
    "owner",
)


@dataclass(frozen=True, slots=True)
class MediaFile:
    """One legacy blob to attach, in slot order: where it lies under the media root, the filename
    the archivist typed, and the MIME type the old system recorded."""

    path: str
    filename: str
    media_type: str | None


@dataclass(frozen=True, slots=True)
class MappedItem:
    """One legacy row as the command can write it: the Article (ULID already minted, media still
    empty — the blobs are stored first), the Bestand it belongs to, and its files in slot order."""

    legacy_id: str
    bestand: str
    article: Article
    media: tuple[MediaFile, ...]


@dataclass(frozen=True, slots=True)
class Report:
    """What the archivist must decide about — the dry run's whole output and the post-import
    summary. The last three are filled in by the command, which alone may look at the disk and at
    the edit form's vocabulary."""

    items: int
    without_media: int
    per_bestand: tuple[tuple[str, int], ...]
    unparseable_date_count: int
    unparseable_dates: tuple[tuple[str, str], ...]
    doctype_disagreements: int
    date_conflicts: int
    date_conflict_samples: tuple[tuple[str, str], ...]
    unnamed_files: tuple[str, ...]
    unknown_media_types: tuple[str, ...] = ()
    unknown_document_types: tuple[str, ...] = ()
    missing_blobs: tuple[str, ...] = ()

    def with_missing_blobs(self, paths: Iterable[str]) -> Report:
        return replace(self, missing_blobs=tuple(paths))

    def with_unknown_vocabulary(
        self, media_types: Vocabulary, document_types: Vocabulary
    ) -> Report:
        return replace(
            self,
            unknown_media_types=tuple(media_types),
            unknown_document_types=tuple(document_types),
        )

    def lines(self) -> tuple[str, ...]:
        """The report as scannable lines (German — the archivist reads them)."""
        return (
            f"Artikel: {self.items}",
            f"davon ohne Datei: {self.without_media}",
            "Bestände:",
            *(f"  {name}: {count}" for name, count in self.per_bestand),
            f"Dokumenttyp-Abweichungen (Freitext ≠ Nachschlagetabelle): {self.doctype_disagreements}",
            f"Unlesbare Datumsangaben: {self.unparseable_date_count}",
            *(f"  {legacy_id}: {raw}" for legacy_id, raw in self.unparseable_dates),
            f"Datum widerspricht den Spalten Monat/Tag: {self.date_conflicts}",
            *(f"  {legacy_id}: {detail}" for legacy_id, detail in self.date_conflict_samples),
            f"Medienarten außerhalb des Formular-Vokabulars: {len(self.unknown_media_types)}",
            *(f"  {value}" for value in self.unknown_media_types),
            f"Dokumenttypen außerhalb des Formular-Vokabulars: {len(self.unknown_document_types)}",
            *(f"  {value}" for value in self.unknown_document_types),
            f"Fehlende Dateien: {len(self.missing_blobs)}",
            *(f"  {path}" for path in self.missing_blobs[:MAX_SAMPLES]),
            f"Dateinamen nur aus Punkten oder Leerzeichen: {len(self.unnamed_files)}",
            *(f"  {path}" for path in self.unnamed_files[:MAX_SAMPLES]),
        )


@dataclass(frozen=True, slots=True)
class Plan:
    """The whole import as one value: every mapped row, and the report over them."""

    items: tuple[MappedItem, ...]
    report: Report


def bestand_name(row: Mapping[str, str]) -> str:
    """The Bestand this row belongs to — its `collection`, or ``Unsortiert`` when it has none."""
    return row["collection"].strip() or UNSORTIERT


def bestand_names(rows: Iterable[Mapping[str, str]]) -> tuple[str, ...]:
    """Every Bestand the export needs, in first-seen order with ``Unsortiert`` last — the order the
    command creates them in, so a re-read of the tree reads like the export."""
    names = dict.fromkeys(bestand_name(row) for row in rows)
    names.pop(UNSORTIERT, None)
    return (*names, UNSORTIERT)


def map_item(
    row: Mapping[str, str],
    media_rows: Iterable[Mapping[str, str]],
    *,
    collection_id: Ulid,
) -> MappedItem:
    """Map one legacy row (plus its `files.csv` rows, any order) onto a fresh Article.

    The Article is PUBLISHED with no explicit audience: the legacy site showed all of this, and the
    Bestand chain is where the archivists will narrow it (ADR 0001). Its media is still empty — the
    blobs must be stored before a README may reference them, so the files ride alongside.
    """
    date, date_template = _map_date(row)
    custom = {
        "Quelle": row["source"],
        "Anmerkungen": row["notes"],
        "Besitzer": row["owner"],
        "Anzahl": "" if row["amount"].strip() in ("", "1") else row["amount"],
        DATE_TEMPLATE_KEY: date_template or "",
        "Legacy-ID": row["id"],
    }
    article = identity.create_article(
        title=row["title"].strip(),
        collection_id=collection_id,
        lifecycle=Lifecycle.PUBLISHED,
        ref_code=_text(row["signature"]),
        media_type=_text(row["medartanalog"]),
        document_type=_document_type(row),
        tags=_tags(row["keywords"]),
        physical_location=_text(row["location"]),
        date=date,
        creator=_text(row["author"]),
        subject_place=_place(row["place"]),
        custom=tuple((key, value.strip()) for key, value in custom.items() if value.strip()),
    )
    return MappedItem(
        legacy_id=row["id"],
        bestand=bestand_name(row),
        article=article,
        media=_media(media_rows),
    )


def plan(
    rows: Sequence[Mapping[str, str]],
    media_rows: Iterable[Mapping[str, str]],
    collection_ids: Mapping[str, Ulid],
) -> Plan:
    """Map every row against the already-created Bestände and report over the result.

    ``collection_ids`` maps Bestand NAME → ULID (what ``bestand_names`` asked the command to
    create); a name it does not know is a ``KeyError`` here rather than a mis-filed Article.
    """
    by_item: dict[str, list[Mapping[str, str]]] = {}
    for media_row in media_rows:
        by_item.setdefault(media_row["item_id"], []).append(media_row)
    items = tuple(
        map_item(row, by_item.get(row["id"], ()), collection_id=collection_ids[bestand_name(row)])
        for row in rows
    )
    unreadable = tuple(
        (item.legacy_id, template)
        for item in items
        if (template := dict(item.article.custom).get(DATE_TEMPLATE_KEY)) is not None
    )
    conflicts = tuple(
        (item.legacy_id, _conflict_detail(row))
        for row, item in zip(rows, items, strict=True)
        if _conflicts_with_columns(row, item.article.date)
    )
    return Plan(
        items=items,
        report=Report(
            items=len(items),
            without_media=sum(1 for item in items if not item.media),
            per_bestand=tuple(Counter(item.bestand for item in items).items()),
            unparseable_date_count=len(unreadable),
            unparseable_dates=unreadable[:MAX_SAMPLES],
            doctype_disagreements=sum(1 for row in rows if _doctype_disagrees(row)),
            date_conflicts=len(conflicts),
            date_conflict_samples=conflicts[:MAX_SAMPLES],
            unnamed_files=tuple(
                media_file.path
                for item in items
                for media_file in item.media
                if cleaned_name(media_file.filename) is None
            ),
        ),
    )


def unknown_vocabulary(
    rows: Iterable[Mapping[str, str]],
    *,
    known_media_types: Vocabulary,
    known_document_types: Vocabulary,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The Medienarten and Dokumenttypen in ``rows`` that the two lists do not contain.

    The lists are the EDIT FORM's (``app.web.vocab``), so the caller passes them in and this module
    stays below the web layer. Such a value is imported verbatim — the export is the archive's
    truth — but a record holding one is a record the form refuses to re-save, which is the
    archivist's call and so belongs in the ``Report``.
    """
    rows = list(rows)
    return (
        _strangers((row["medartanalog"] for row in rows), known_media_types),
        _strangers((_document_type(row) or "" for row in rows), known_document_types),
    )


def _strangers(values: Iterable[str], known: Vocabulary) -> tuple[str, ...]:
    """The distinct non-empty values outside ``known``, in first-seen order."""
    stripped = (value.strip() for value in values)
    return tuple(dict.fromkeys(value for value in stripped if value and value not in known))


# --- field rules -------------------------------------------------------------------


def _text(value: str) -> str | None:
    """A legacy text cell as an Article field: stripped, absent when blank (never ``""``)."""
    return value.strip() or None


def _place(value: str) -> str | None:
    """`place`, minus the `(…)` the catalogers wrapped an uncertain place in (memo §2)."""
    stripped = value.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1].strip()
    return stripped or None


def _document_type(row: Mapping[str, str]) -> str | None:
    """The Dokumenttyp: the lookup table's name when the export resolved one, else the free text.

    The two disagree in a handful of rows (`Chronik/Dokumentation` vs `Chronik / Dokumentation`);
    the lookup is the controlled value, so it wins and the report counts the disagreements.
    """
    return _text(row["document_type_name"]) or _text(row["doctype"])


def _doctype_disagrees(row: Mapping[str, str]) -> bool:
    free, looked_up = row["doctype"].strip(), row["document_type_name"].strip()
    return bool(free) and bool(looked_up) and free != looked_up


def _tags(keywords: str) -> tuple[str, ...]:
    """`keywords` → tags: split on `--`, then on whitespace, deduped, first-occurrence order.

    The column mixes both delimiters and carries literal `\\r` from the old admin forms; splitting
    on whitespace after the dashes is the owner's call (one word per tag beats one long pseudo-tag).
    """
    tokens = (token for part in keywords.split("--") for token in part.split())
    return tuple(dict.fromkeys(token.strip() for token in tokens if token.strip()))


def _media(media_rows: Iterable[Mapping[str, str]]) -> tuple[MediaFile, ...]:
    """The item's files in slot order (1, 2, 3) — order is meaning: slot 1 is the cover."""
    return tuple(
        MediaFile(
            path=row["path"],
            filename=row["original_filename"].strip() or row["path"].rsplit("/", 1)[-1],
            media_type=_text(row["mime_type"]),
        )
        for row in sorted(media_rows, key=lambda row: int(row["slot"]))
    )


# --- dates (memo §4) ---------------------------------------------------------------

#: The German month names the catalogers typed, in EDTF month order.
_MONTHS: dict[str, str] = {
    name: f"{number:02d}"
    for number, name in enumerate(
        (
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
        ),
        start=1,
    )
}

_YEAR = re.compile(r"^(\d{4})$")
_MONTH_YEAR = re.compile(r"^([A-Za-zÄÖÜäöü]+)\s+(\d{4})$")
_DAY_MONTH_YEAR = re.compile(r"^(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)\s+(\d{4})$")
_NUMERIC = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_ISO = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _map_date(row: Mapping[str, str]) -> tuple[EdtfDate | None, str | None]:
    """``(date, template)``: the EDTF value, and the original words when they could not be read.

    A shape the memo automates yields EDTF and no template. Anything else falls back to the
    `year`/`month`/`day` columns and keeps its own words: 300 rows carry a month and 62 a day that
    the free-text `date` may not spell (`1.2.63` reads as no date at all), so reading only `year`
    would drop precision the export still holds — while the columns never add any of their own.
    """
    raw = row["date"].strip()
    parsed = _parse(raw) if raw else None
    if parsed is not None:
        return parsed, None
    return _from_columns(row), raw or None


def _from_columns(row: Mapping[str, str]) -> EdtfDate | None:
    """`year`/`month`/`day` as EDTF: the most precise spelling those columns support that is a real
    calendar date (they are sparse and occasionally impossible), or ``None`` when there is no year.
    """
    year = row["year"].strip()
    if not _YEAR.match(year):
        return None
    month, day = _two_digits(row["month"], 12), _two_digits(row["day"], 31)
    candidates = (
        f"{year}-{month}-{day}" if month and day else "",
        f"{year}-{month}" if month else "",
        year,
    )
    return next(
        (date for value in candidates if value and (date := _edtf_or_none(value)) is not None),
        None,
    )


def _two_digits(value: str, highest: int) -> str:
    """A `month`/`day` cell as a zero-padded EDTF component, or ``""`` when it is empty or not a
    number in range — the old admin let both columns hold free text."""
    raw = value.strip()
    return f"{int(raw):02d}" if raw.isdigit() and 1 <= int(raw) <= highest else ""


def _conflicts_with_columns(row: Mapping[str, str], date: EdtfDate | None) -> bool:
    """Does the mapped date contradict the `month`/`day` columns? Only a readable `date` text can —
    the fallback is built FROM those columns — and then one of the two is wrong, which is the
    archivist's call, not the import's."""
    value = date.value if date is not None else ""
    month, day = _two_digits(row["month"], 12), _two_digits(row["day"], 31)
    if month and value[5:7] != month:
        return True
    return bool(day) and value[8:10] != day


def _conflict_detail(row: Mapping[str, str]) -> str:
    return f"date={row['date'].strip()!r} month={row['month'].strip()!r} day={row['day'].strip()!r}"


def _parse(raw: str) -> EdtfDate | None:
    """One legacy date string → EDTF, or ``None`` when it is not one of the automated shapes.

    A `(…)` wrapper is the catalogers' "about" and becomes the EDTF `~` qualifier (memo §4).
    """
    approximate = raw.startswith("(") and raw.endswith(")")
    core = raw[1:-1].strip() if approximate else raw
    value = _edtf_of(core)
    if value is None:
        return None
    # a calendar-impossible date (31.02.) is unreadable, not repairable
    return _edtf_or_none(value + "~" if approximate else value)


def _edtf_or_none(value: str) -> EdtfDate | None:
    try:
        return EdtfDate(value)
    except ValueError:
        return None


def _edtf_of(core: str) -> str | None:
    if _YEAR.match(core) or _ISO.match(core):
        return core
    if (m := _DAY_MONTH_YEAR.match(core)) and (month := _MONTHS.get(m.group(2))):
        return f"{m.group(3)}-{month}-{int(m.group(1)):02d}"
    if (m := _MONTH_YEAR.match(core)) and (month := _MONTHS.get(m.group(1))):
        return f"{m.group(2)}-{month}"
    if m := _NUMERIC.match(core):
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None
