"""The legacy→Article mapping (`app.legacy`), the loss-critical half of the one-time import.

This is the data-loss class of the testing razor: the old database is being read once and thrown
away, so anything this module silently drops is gone. Hence the column-coverage gate (every legacy
column is either mapped or named as dropped), a case per date shape the memo automates, and the
keyword/custom/Signatur rules that carry an archivist's typing verbatim.

The rows here are SYNTHETIC — shaped like the real export, never copied from it.
"""

import csv
import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from PIL import Image

from bundesarchiv.app import legacy
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.management.commands.import_legacy import CHANGED_BY
from bundesarchiv.app.thumbnails import thumbnail_path
from bundesarchiv.app.web import vocab
from bundesarchiv.domain.models import Lifecycle
from bundesarchiv.persistence._layout import COLLECTIONS

#: Stand-ins for the edit form's two lists: `unknown_vocabulary` only ever tests membership, and
#: which lists the real import measures against is the command's business, not this module's.
_KNOWN_MEDIENARTEN = ("Schrifttum", "Foto(s)")
_KNOWN_DOKUMENTTYPEN = ("Zeitschrift", "Lagerheft", "Chronik / Dokumentation", "Sonstiges")

_COLLECTIONS = {
    "Bund": "01BUND0000000000000000000",
    "Orden St. Georg": "01ORDEN000000000000000000",
    legacy.UNSORTED: "01UNSORTIERT00000000000000"[:26],
}


def _row(**overrides: str) -> dict[str, str]:
    """A synthetic items.csv row: every legacy column present, empty unless overridden."""
    row = dict.fromkeys(legacy.ITEM_COLUMNS, "")
    row.update(
        {
            "id": "982",
            "signature": "BA 1",
            "title": "Verfassung des Ordens",
            "collection": "Bund",
            "amount": "1",
            "active": "t",
            "reviewed": "t",
            "pub_date": "2017-06-26 06:06:40.957434+00",
        }
    )
    row.update(overrides)
    return row


def _file(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(legacy.FILE_COLUMNS, "")
    row.update(
        {
            "item_id": "982",
            "slot": "1",
            "path": "filer_public/aa/bb/eins.pdf",
            "original_filename": "Eins.pdf",
            "mime_type": "application/pdf",
        }
    )
    row.update(overrides)
    return row


def _map(row: dict[str, str], *files: dict[str, str]) -> legacy.MappedItem:
    return legacy.map_item(row, files, collection_id=_COLLECTIONS[legacy.collection_name(row)])


def _plan_of(rows: list[dict[str, str]], files: list[dict[str, str]] | None = None) -> legacy.Plan:
    return legacy.plan(rows, files or [], _COLLECTIONS)


def _edtf(**overrides: str) -> str | None:
    """The EDTF value a row maps to, or ``None`` when it maps to no date."""
    date = _map(_row(**overrides)).article.date
    return date.value if date is not None else None


# --- column coverage: nothing vanishes silently ------------------------------------


def test_every_legacy_column_is_either_mapped_or_named_as_dropped() -> None:
    assert set(legacy.MAPPED_COLUMNS) | set(legacy.DROPPED_COLUMNS) == set(legacy.ITEM_COLUMNS)
    assert not set(legacy.MAPPED_COLUMNS) & set(legacy.DROPPED_COLUMNS)


def test_the_dropped_columns_are_exactly_the_ones_the_owner_agreed_to_lose() -> None:
    # Pinned so a column cannot join the drop list without this test saying so out loud.
    assert set(legacy.DROPPED_COLUMNS) == {
        "active",
        "reviewed",
        "modified",
        "crossreference",
        "file_id",
        "file2_id",
        "file3_id",
    }


#: One probe per mapped column: the row cells that carry a sentinel (plus the companions a column
#: needs to mean anything) and the text the mapped Article must then show. This is what makes the
#: coverage gate above bite — "mapped" has to mean READ, not merely "not on the drop list".
_PROBES: dict[str, tuple[dict[str, str], str]] = {
    "id": ({"id": "4711"}, "4711"),
    "signature": ({"signature": "BA 99"}, "BA 99"),
    "author": ({"author": "Gau Franken"}, "Gau Franken"),
    "title": ({"title": "Fränkischer Rechen"}, "Fränkischer Rechen"),
    "date": ({"date": "Pfingsten"}, "Pfingsten"),
    "year": ({"year": "1963"}, "1963"),
    "month": ({"year": "1963", "month": "7"}, "1963-07"),
    "day": ({"year": "1963", "month": "7", "day": "4"}, "1963-07-04"),
    "place": ({"place": "Mainz"}, "Mainz"),
    "medartanalog": ({"medartanalog": "Schrifttum"}, "Schrifttum"),
    "doctype": ({"doctype": "Lagerheft"}, "Lagerheft"),
    "document_type_name": ({"document_type_name": "Zeitschrift"}, "Zeitschrift"),
    "keywords": ({"keywords": "Jugendbewegung"}, "Jugendbewegung"),
    "location": ({"location": "Regal 4"}, "Regal 4"),
    "source": ({"source": "bolko"}, "bolko"),
    "notes": ({"notes": "inkl. Beilage"}, "inkl. Beilage"),
    "collection": ({"collection": "Orden St. Georg"}, "Orden St. Georg"),
    "amount": ({"amount": "12"}, "12"),
    "owner": ({"owner": "Nachlass Schäder"}, "Nachlass Schäder"),
    "pub_date": ({"pub_date": "2019-03-04 05:06:07.8+00"}, "2019-03-04 05:06:07+00:00"),
}


def _rendered(mapped: legacy.MappedItem) -> str:
    """Everything the mapping produced from one row, as one string a sentinel can be found in."""
    article = mapped.article
    return " | ".join(
        (
            mapped.collection,
            article.title,
            article.ref_code or "",
            article.creator or "",
            article.subject_place or "",
            article.physical_location or "",
            article.media_type or "",
            article.document_type or "",
            article.date.value if article.date is not None else "",
            *article.tags,
            *(f"{key}={value}" for key, value in article.custom),
            str(article.added_at),
        )
    )


def test_every_mapped_column_actually_reaches_the_article() -> None:
    assert set(_PROBES) == set(legacy.MAPPED_COLUMNS)
    for column, (row, expected) in _PROBES.items():
        assert expected in _rendered(_map(_row(**row))), column


def test_the_legacy_id_survives_as_a_custom_field() -> None:
    # `id` is dropped as identity (a ULID replaces it) but kept as provenance — the one thread back
    # to the old database after it is gone.
    assert dict(_map(_row(id="4711")).article.custom)["Legacy-ID"] == "4711"


# --- the plain fields --------------------------------------------------------------


@pytest.mark.parametrize(
    "pub_date",
    ["2017-06-26 06:06:40.957434+00", "2017-06-26 08:06:40+02", " 2017-06-26 06:06:40+00:00 "],
)
def test_pub_date_becomes_the_date_added_in_utc_whole_seconds(pub_date: str) -> None:
    added_at = _map(_row(pub_date=pub_date)).article.added_at
    assert added_at == datetime(2017, 6, 26, 6, 6, 40, tzinfo=UTC)


def test_the_signatur_keeps_its_inner_space_verbatim() -> None:
    assert _map(_row(signature="BA 1074")).article.ref_code == "BA 1074"


def test_an_empty_signatur_is_absent_not_blank() -> None:
    assert _map(_row(signature="  ")).article.ref_code is None


def test_author_title_place_and_location_carry_over() -> None:
    article = _map(
        _row(
            author="Gau Franken",
            title="Fränkischer Rechen Nummer 6",
            place="Mainz",
            location="Gruppen des DPB -- Gau Franken",
            medartanalog="Schrifttum",
        )
    ).article
    assert article.creator == "Gau Franken"
    assert article.title == "Fränkischer Rechen Nummer 6"
    assert article.subject_place == "Mainz"
    assert article.physical_location == "Gruppen des DPB -- Gau Franken"
    assert article.media_type == "Schrifttum"


def test_a_parenthesised_place_loses_only_its_uncertainty_wrapper() -> None:
    # memo §2: `(Berlin)` is the cataloger's uncertainty marker around the place itself.
    assert _map(_row(place="(Berlin)")).article.subject_place == "Berlin"


def test_every_imported_article_is_published_and_inherits_its_audience() -> None:
    article = _map(_row()).article
    assert article.lifecycle is Lifecycle.PUBLISHED
    assert article.audience is None  # inherit from the Bestand chain (ADR 0001)


# --- Dokumenttyp: the lookup wins --------------------------------------------------


def test_the_document_type_lookup_wins_over_the_free_text() -> None:
    article = _map(
        _row(doctype="Chronik/Dokumentation", document_type_name="Chronik / Dokumentation")
    ).article
    assert article.document_type == "Chronik / Dokumentation"


def test_the_free_text_document_type_is_used_when_the_lookup_is_empty() -> None:
    assert _map(_row(doctype="Lagerheft")).article.document_type == "Lagerheft"


def test_no_document_type_at_all_is_absent() -> None:
    assert _map(_row()).article.document_type is None


# --- Bestand ------------------------------------------------------------------------


def test_an_empty_collection_lands_in_unsortiert() -> None:
    assert legacy.collection_name(_row(collection="")) == legacy.UNSORTED


def test_the_bestand_names_are_the_legacy_ones_plus_unsortiert() -> None:
    rows = [_row(collection="Bund"), _row(collection=""), _row(collection="Orden St. Georg")]
    assert legacy.collection_names(rows) == ("Bund", "Orden St. Georg", legacy.UNSORTED)


# --- keywords -> tags ---------------------------------------------------------------


def _tags(keywords: str) -> tuple[str, ...]:
    return _map(_row(keywords=keywords)).article.tags


def test_a_line_is_one_tag_however_many_words_it_has() -> None:
    assert _tags("Foto auf Holzplatte als Wandbild\nMotiv: Tony Wirtz") == (
        "Foto auf Holzplatte als Wandbild",
        "Motiv: Tony Wirtz",
    )
    assert _tags("Pilgerpfad Heft 1") == ("Pilgerpfad Heft 1",)


def test_dashes_separate_tags_within_a_line() -> None:
    assert _tags("Lieder -- Volkslieder -- Wanderlieder\nBilder -- Wandervogel") == (
        "Lieder",
        "Volkslieder",
        "Wanderlieder",
        "Bilder",
        "Wandervogel",
    )


@pytest.mark.parametrize("newline", ["\r\n", "\r", "\n"])
def test_every_legacy_line_break_separates_tags(newline: str) -> None:
    assert _tags(f"Blätter St. Georg 18{newline}Gaubrief der Franken") == (
        "Blätter St. Georg 18",
        "Gaubrief der Franken",
    )


def test_a_table_of_contents_loses_its_bullets_but_keeps_each_line() -> None:
    toc = "Inhalt:\r\n•\tTermine im Gau\r\n- Fahrtenbericht\r\n\N{EN DASH} Lieder zur Klampfe"
    assert _tags(toc) == ("Inhalt:", "Termine im Gau", "Fahrtenbericht", "Lieder zur Klampfe")


def test_empty_pieces_are_no_tags() -> None:
    assert _tags("•\t\r\n-- Lager\n\n  \nFahrt --\n--") == ("Lager", "Fahrt")


def test_duplicates_go_case_sensitively_and_first_occurrence_order_stays() -> None:
    assert _tags("Lager\nlager -- Bund\n• Lager\nBund") == ("Lager", "lager", "Bund")


def test_no_keywords_is_no_tags() -> None:
    assert _map(_row(keywords="   ")).article.tags == ()


# --- the custom bag ------------------------------------------------------------------


def test_the_sparse_columns_land_in_the_custom_bag() -> None:
    custom = dict(
        _map(_row(source="bolko", notes="inkl. Beilage", owner="Nachlass Schäder")).article.custom
    )
    assert custom["Quelle"] == "bolko"
    assert custom["Anmerkungen"] == "inkl. Beilage"
    assert custom["Besitzer"] == "Nachlass Schäder"


def test_an_empty_custom_value_is_omitted_never_written_as_blank() -> None:
    custom = dict(_map(_row(source="", notes="   ")).article.custom)
    assert "Quelle" not in custom
    assert "Anmerkungen" not in custom


@pytest.mark.parametrize("amount", ["", "1"])
def test_the_default_amount_is_not_worth_a_custom_field(amount: str) -> None:
    assert "Anzahl" not in dict(_map(_row(amount=amount)).article.custom)


def test_a_real_amount_is_kept() -> None:
    assert dict(_map(_row(amount="12")).article.custom)["Anzahl"] == "12"


# --- dates ---------------------------------------------------------------------------

_DATE_SHAPES = [
    ("1984", "", "1984"),
    ("Dezember 1979", "", "1979-12"),
    ("(1974)", "", "1974~"),
    ("(Mai 1994)", "", "1994-05~"),
    ("1. April 1961", "", "1961-04-01"),
    ("12.05.1979", "", "1979-05-12"),
    ("1979-05", "", "1979-05"),
    ("1979-05-12", "", "1979-05-12"),
    ("", "1970", "1970"),
]


@pytest.mark.parametrize(("date", "year", "edtf"), _DATE_SHAPES)
def test_the_unambiguous_date_shapes_become_edtf(date: str, year: str, edtf: str) -> None:
    article = _map(_row(date=date, year=year)).article
    assert article.date is not None
    assert article.date.value == edtf
    assert "Datum (Vorlage)" not in dict(article.custom)


def test_no_date_and_no_year_is_no_date() -> None:
    assert _map(_row(date="", year="")).article.date is None


@pytest.mark.parametrize("date", ["Herbst 1997", "nonen zit 1958", "(1969) oder später", "0"])
def test_an_unreadable_date_keeps_its_own_words_and_falls_back_to_the_year(date: str) -> None:
    # Never invent precision: the year is all we know, and the cataloger's own string survives for
    # the archivist who will read it later.
    article = _map(_row(date=date, year="1958")).article
    assert article.date is not None
    assert article.date.value == "1958"
    assert dict(article.custom)["Datum (Vorlage)"] == date


def test_an_unreadable_date_falls_back_to_the_month_and_day_columns() -> None:
    # 300 rows of the real export carry a month and 62 a day; `1.2.63` is not a shape the memo
    # automates, so reading only `year` would throw away precision the export still holds.
    article = _map(_row(date="1.2.63", year="1963", month="2", day="1")).article
    assert article.date is not None
    assert article.date.value == "1963-02-01"
    assert dict(article.custom)["Datum (Vorlage)"] == "1.2.63"  # and the words stay, verbatim


def test_the_columns_add_only_the_precision_they_carry() -> None:
    assert _edtf(date="", year="1963") == "1963"
    assert _edtf(date="", year="1963", month="7") == "1963-07"
    assert _edtf(date="", year="1963", month="7", day="4") == "1963-07-04"
    assert _edtf(date="", year="", month="7") is None  # a month without a year is not a date


@pytest.mark.parametrize("month", ["0", "13", "Mai", "  "])
def test_a_column_that_is_not_a_calendar_number_is_ignored(month: str) -> None:
    assert _edtf(date="", year="1963", month=month) == "1963"


def test_an_impossible_column_pair_falls_back_to_what_is_still_a_date() -> None:
    # 31.02. is not a date; the year and month it sits in still are.
    assert _edtf(date="", year="1963", month="2", day="31") == "1963-02"


def test_a_readable_date_wins_over_the_columns_and_the_disagreement_is_reported() -> None:
    # The text is the cataloger's own sentence; the columns are the old admin's parse of it. When
    # they differ one of the two is wrong, which is the archivist's call — so it is counted.
    report = _plan_of([_row(id="7", date="Dezember 1979", year="1979", month="5")]).report
    assert _edtf(date="Dezember 1979", year="1979", month="5") == "1979-12"
    assert report.date_conflicts == 1
    assert report.date_conflict_samples[0][0] == "7"


def test_a_date_the_columns_agree_with_is_no_conflict() -> None:
    row = _row(date="12.05.1979", year="1979", month="5", day="12")
    assert _plan_of([row]).report.date_conflicts == 0


def test_an_unreadable_date_without_a_year_leaves_no_date_but_keeps_the_words() -> None:
    article = _map(_row(date="Pfingsten", year="")).article
    assert article.date is None
    assert dict(article.custom)["Datum (Vorlage)"] == "Pfingsten"


def test_an_impossible_calendar_date_is_unreadable_not_invented() -> None:
    article = _map(_row(date="31.02.1979", year="1979")).article
    assert article.date is not None
    assert article.date.value == "1979"
    assert dict(article.custom)["Datum (Vorlage)"] == "31.02.1979"


# --- media ---------------------------------------------------------------------------


def test_an_item_without_files_gets_no_media() -> None:
    assert _map(_row()).media == ()


def test_three_files_arrive_in_slot_order() -> None:
    mapped = _map(
        _row(),
        _file(slot="3", path="c.jpg", original_filename="C.jpg", mime_type="image/jpeg"),
        _file(slot="1", path="a.pdf", original_filename="A.pdf"),
        _file(slot="2", path="b.pdf", original_filename="B.pdf"),
    )
    assert [m.path for m in mapped.media] == ["a.pdf", "b.pdf", "c.jpg"]
    assert [m.filename for m in mapped.media] == ["A.pdf", "B.pdf", "C.jpg"]
    assert mapped.media[2].media_type == "image/jpeg"


def test_a_file_without_an_original_filename_falls_back_to_its_path() -> None:
    mapped = _map(_row(), _file(path="filer_public/aa/bb/eins.pdf", original_filename=""))
    assert mapped.media[0].filename == "eins.pdf"


def test_the_article_itself_carries_no_media_yet() -> None:
    # The blobs are stored by the command; the mapping only says WHICH files, in which order.
    assert _map(_row(), _file()).article.media == ()


# --- the report -----------------------------------------------------------------------


def _plan() -> legacy.Plan:
    rows = [
        _row(id="1", collection="Bund", date="1984"),
        _row(id="2", collection="", date="Pfingsten 1985", year="1985"),
        _row(id="3", collection="Bund", doctype="Sonstiges", document_type_name="Zeitschrift"),
    ]
    return _plan_of(rows, [_file(item_id="1")])


def test_the_report_counts_what_the_archivist_must_decide_about() -> None:
    report = _plan().report
    assert report.items == 3
    assert report.without_media == 2
    assert dict(report.per_collection) == {"Bund": 2, legacy.UNSORTED: 1}
    assert report.doctype_disagreements == 1
    assert report.unparseable_dates == (("2", "Pfingsten 1985"),)


def test_the_report_names_the_values_the_edit_form_would_refuse() -> None:
    # The form validates against a fixed vocabulary, so a value outside it produces a record the
    # archivist cannot re-save. The import still writes it verbatim — and says so.
    rows = [
        _row(id="1", medartanalog="Schrifttum", document_type_name="Zeitschrift"),
        _row(id="2", medartanalog="Papier", document_type_name="Brief"),
        _row(id="3", medartanalog="Papier"),
    ]
    media_types, document_types = legacy.unknown_vocabulary(
        rows,
        known_media_types=_KNOWN_MEDIENARTEN,
        known_document_types=_KNOWN_DOKUMENTTYPEN,
    )
    assert media_types == ("Papier",)  # distinct, first-seen order
    assert document_types == ("Brief",)
    report = _plan_of(rows).report.with_unknown_vocabulary(media_types, document_types)
    assert any("Papier" in line for line in report.lines())


def test_the_report_samples_at_most_ten_unreadable_dates() -> None:
    rows = [_row(id=str(i), date="Pfingsten", year="1985") for i in range(25)]
    report = _plan_of(rows).report
    assert report.unparseable_date_count == 25
    assert len(report.unparseable_dates) == legacy.MAX_SAMPLES


@pytest.mark.parametrize("pub_date", ["", "gestern", "2017-06-26 06:06:40", "2017-06-26"])
def test_an_unreadable_pub_date_leaves_the_date_added_unknown_and_is_reported(
    pub_date: str,
) -> None:
    plan = _plan_of([_row(id="7", pub_date=pub_date), _row(id="8")])
    assert [item.article.added_at is None for item in plan.items] == [True, False]
    assert plan.report.unreadable_added_count == 1
    assert plan.report.unreadable_added == (("7", pub_date),)


def test_missing_blobs_join_the_report_without_rebuilding_it() -> None:
    # Whether a blob is actually on disk is the command's knowledge (IO); the report shape is this
    # module's, so the command hands the paths back rather than growing a report of its own.
    report = _plan().report.with_missing_blobs(("filer_public/aa/bb/eins.pdf",))
    assert report.missing_blobs == ("filer_public/aa/bb/eins.pdf",)
    assert report.items == 3
    assert any("fehlend" in line.lower() or "missing" in line.lower() for line in report.lines())


def test_the_plan_maps_every_row_once() -> None:
    plan = _plan()
    assert [item.legacy_id for item in plan.items] == ["1", "2", "3"]
    assert [len(item.media) for item in plan.items] == [1, 0, 0]


# --- the command: one smoke over a temp root (razor: thin on IO) ---------------------


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (50, 100, 150)).save(buffer, format="PNG")
    return buffer.getvalue()


def _write_export(csv_dir: Path, media_root: Path, *extra: dict[str, str]) -> None:
    """A synthetic export plus its blobs: one item with a PDF, one with an image (the thumbnail
    path), one with no file at all — and whatever extra rows a test needs."""
    csv_dir.mkdir(parents=True)
    media_root.mkdir(parents=True)
    (media_root / "eins.pdf").write_bytes(b"%PDF-1.4 eins")
    (media_root / "zwei.png").write_bytes(_png_bytes())
    with (csv_dir / "items.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=legacy.ITEM_COLUMNS)
        writer.writeheader()
        writer.writerow(
            _row(id="1", collection="Bund", title="Mit Datei", date="1984", medartanalog="Buch")
        )
        writer.writerow(_row(id="2", collection="", title="Ohne Datei"))
        writer.writerow(_row(id="3", collection="Bund", title="Mit Bild", medartanalog="Foto(s)"))
        writer.writerows(extra)
    with (csv_dir / "files.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=legacy.FILE_COLUMNS)
        writer.writeheader()
        writer.writerow(_file(item_id="1", path="eins.pdf", original_filename="Eins.pdf"))
        writer.writerow(
            _file(item_id="3", path="zwei.png", original_filename="Zwei.png", mime_type="image/png")
        )


def _roots(tmp_path: Path) -> override_settings:
    """Both write destinations under this test's tmp dir: the canonical tree and the thumbnail
    cache (which the import fills itself — no worker runs during a one-shot batch)."""
    return override_settings(
        BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical"),
        BUNDESARCHIV_THUMBNAIL_ROOT=str(tmp_path / "thumbnails"),
    )


def _run(csv_dir: Path, media_root: Path, *flags: str) -> str:
    out = io.StringIO()
    call_command(
        "import_legacy",
        "--csv-dir",
        str(csv_dir),
        "--media-root",
        str(media_root),
        *flags,
        stdout=out,
    )
    return out.getvalue()


@pytest.mark.django_db
def test_the_import_is_a_dry_run_a_real_run_and_then_a_refusal(tmp_path: Path) -> None:
    from bundesarchiv.index.models import ArticleIndex

    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    with _roots(tmp_path):
        archive = Archive.canonical()

        dry = _run(csv_dir, media_root, "--dry-run")
        assert "Articles: 3" in dry
        assert list(archive.articles.list_ulids()) == []  # a dry run writes NOTHING
        assert archive.collections.load_all() == ()

        _run(csv_dir, media_root)
        ulids = list(archive.articles.list_ulids())
        assert len(ulids) == 3
        bestände = {c.name for c in archive.collections.load_all()}
        assert bestände == {"Bund", legacy.UNSORTED}
        with_file = next(
            archive.articles.load(u).article
            for u in ulids
            if archive.articles.load(u).article.title == "Mit Datei"
        )
        assert [ref.filename for ref in with_file.media] == ["Eins.pdf"]
        with archive.articles.open_media(with_file.ulid, with_file.media[0]) as stored:
            assert stored.read() == b"%PDF-1.4 eins"
        assert ArticleIndex.objects.count() == 3  # the index sees them without a second command

        with pytest.raises(CommandError, match="already holds"):
            _run(csv_dir, media_root)
        assert len(list(archive.articles.list_ulids())) == 3  # the refusal changed nothing


@pytest.mark.django_db
def test_every_imported_version_names_the_import(tmp_path: Path) -> None:
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    with _roots(tmp_path):
        _run(csv_dir, media_root)
        archive = Archive.canonical()
        changes = [archive.articles.load(u).change for u in archive.articles.list_ulids()]
        changes += [archive.collections.load(c.ulid).change for c in archive.collections.load_all()]
    assert len(changes) == 5  # three Articles, two Bestände
    assert {change.by if change else None for change in changes} == {CHANGED_BY}


@pytest.mark.django_db
def test_the_import_ends_with_the_fixity_check_of_what_it_wrote(tmp_path: Path) -> None:
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    with _roots(tmp_path):
        out = _run(csv_dir, media_root)
    assert "Checked: 5 README versions, 2 media files\n" in out  # three Articles, two Bestände
    assert out.endswith("No findings.\n")


@pytest.mark.django_db
def test_the_import_derives_the_thumbnails_itself(tmp_path: Path) -> None:
    # It writes past the `app.articles` shell, which is what enqueues them, and no worker drains a
    # queue during a one-shot batch — so without this every imported cover would 404 forever.
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    with _roots(tmp_path):
        out = _run(csv_dir, media_root)
        archive = Archive.canonical()
        image = next(
            article
            for u in archive.articles.list_ulids()
            if (article := archive.articles.load(u).article).title == "Mit Bild"
        )
    hash_ = image.media[0].content_hash
    assert thumbnail_path(tmp_path / "thumbnails", hash_).is_file()
    assert "Thumbnails generated: 1" in out  # the PDF is no image and stays a no-op


@pytest.mark.django_db
def test_an_unreadable_bestand_stops_the_import_before_it_writes(tmp_path: Path) -> None:
    """Matching by name cannot see an unreadable Bestand: going on could create its twin."""
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    with _roots(tmp_path):
        archive = Archive.canonical()
        archive.store.write_atomic(COLLECTIONS.readme_key("01BAD"), b"---\nname: [\n---\n")
        with pytest.raises(CommandError, match="01BAD"):
            _run(csv_dir, media_root)
        assert list(archive.collections.list_ulids()) == ["01BAD"]
        assert list(archive.articles.list_ulids()) == []


@pytest.mark.django_db
def test_an_absent_media_root_stops_the_import_before_it_writes(tmp_path: Path) -> None:
    # An unmounted volume would otherwise produce a complete, media-less archive that the one-time
    # refusal then gives no second chance to fix.
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    with _roots(tmp_path):
        with pytest.raises(CommandError, match="Media directory not found"):
            _run(csv_dir, tmp_path / "nicht-eingehängt")
        assert list(Archive.canonical().articles.list_ulids()) == []


@pytest.mark.django_db
def test_a_media_root_holding_none_of_the_exported_files_stops_the_import(tmp_path: Path) -> None:
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    empty = tmp_path / "leer"
    empty.mkdir()
    with _roots(tmp_path):
        with pytest.raises(CommandError, match="wrong media path"):
            _run(csv_dir, empty)
        assert list(Archive.canonical().articles.list_ulids()) == []


@pytest.mark.django_db
def test_the_dry_run_names_what_the_edit_form_would_refuse(tmp_path: Path) -> None:
    # Where `app.legacy` meets the form's vocabulary: the pure module only takes the two lists as
    # arguments, so the command is the one place that can spot a value the form will not re-save.
    stranger = "Papier"
    assert stranger not in vocab.MEDIA_TYPES
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root, _row(id="4", collection="Bund", medartanalog=stranger))
    with _roots(tmp_path):
        out = _run(csv_dir, media_root, "--dry-run")
    assert f"  {stranger}" in out
    assert "Buch" not in out and "Foto(s)" not in out  # the words the form knows stay silent


@pytest.mark.django_db
def test_a_missing_blob_is_reported_not_guessed(tmp_path: Path) -> None:
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    (media_root / "eins.pdf").unlink()
    with _roots(tmp_path):
        out = _run(csv_dir, media_root)
        archive = Archive.canonical()
        assert "Missing files: 1" in out
        titles = {
            article.title: article.media
            for u in archive.articles.list_ulids()
            if (article := archive.articles.load(u).article)
        }
    assert titles["Mit Datei"] == ()  # the reference is lost, the record is not
    assert titles["Mit Bild"] != ()  # and the blob that IS there keeps its own


@pytest.mark.django_db
def test_a_name_that_cleans_to_nothing_is_reported_not_renamed(tmp_path: Path) -> None:
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    nameless = _file(item_id="4", path="eins.pdf", original_filename=" . . ")
    _write_export(csv_dir, media_root, _row(id="4", collection="Bund", title="Namenlos"))
    with (csv_dir / "files.csv").open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=legacy.FILE_COLUMNS).writerow(nameless)
    with _roots(tmp_path):
        dry = _run(csv_dir, media_root, "--dry-run")
        out = _run(csv_dir, media_root)
        archive = Archive.canonical()
        article = next(
            article
            for u in archive.articles.list_ulids()
            if (article := archive.articles.load(u).article).title == "Namenlos"
        )
        stored = archive.articles.keys_for(article.ulid)
    for report in (dry, out):
        assert "File names of only dots or spaces: 1\n  eins.pdf\n" in report
    assert article.media == ()
    assert [key for key in stored if "/media/" in key.key] == []


@pytest.mark.django_db
def test_an_export_with_an_unknown_column_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # A column added to the old database must stop the import, not be dropped on the floor.
    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    items = csv_dir / "items.csv"
    items.write_text(items.read_text().replace("id,signature", "id,neue_spalte,signature", 1))
    with _roots(tmp_path):
        with pytest.raises(CommandError, match="unexpected columns"):
            _run(csv_dir, media_root)
        assert list(Archive.canonical().articles.list_ulids()) == []


@pytest.mark.django_db
def test_rebuild_index_hands_the_shared_index_back_to_another_root(tmp_path: Path) -> None:
    # The index is one table for every canonical root, so the import's rebuild repoints it. This is
    # the documented way back (README, "Legacy import") — and the import's own retry, which the
    # one-time refusal otherwise denies.
    from bundesarchiv.index.models import ArticleIndex

    csv_dir, media_root = tmp_path / "legacy", tmp_path / "media"
    _write_export(csv_dir, media_root)
    with _roots(tmp_path):
        _run(csv_dir, media_root)
        assert ArticleIndex.objects.count() == 3
    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "leerer-baum")):
        call_command("rebuild_index", stdout=io.StringIO())
    assert ArticleIndex.objects.count() == 0
