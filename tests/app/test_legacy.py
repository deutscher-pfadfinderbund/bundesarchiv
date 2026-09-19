"""The legacy→Article mapping (`app.legacy`), the loss-critical half of the one-time import.

This is the data-loss class of the testing razor: the old database is being read once and thrown
away, so anything this module silently drops is gone. Hence the column-coverage gate (every legacy
column is either mapped or named as dropped), a case per date shape the memo automates, and the
keyword/custom/Signatur rules that carry an archivist's typing verbatim.

The rows here are SYNTHETIC — shaped like the real export, never copied from it.
"""

import pytest

from bundesarchiv.app import legacy
from bundesarchiv.domain.models import Lifecycle

#: Stand-ins for the edit form's two lists: `unknown_vocabulary` only ever tests membership, and
#: which lists the real import measures against is the command's business, not this module's.
_KNOWN_MEDIENARTEN = ("Schrifttum", "Foto(s)")
_KNOWN_DOKUMENTTYPEN = ("Zeitschrift", "Lagerheft", "Chronik / Dokumentation", "Sonstiges")

_COLLECTIONS = {
    "Bund": "01BUND0000000000000000000",
    "Orden St. Georg": "01ORDEN000000000000000000",
    legacy.UNSORTIERT: "01UNSORTIERT00000000000000"[:26],
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
    return legacy.map_item(row, files, collection_id=_COLLECTIONS[legacy.bestand_name(row)])


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
        "pub_date",
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
}


def _rendered(mapped: legacy.MappedItem) -> str:
    """Everything the mapping produced from one row, as one string a sentinel can be found in."""
    article = mapped.article
    return " | ".join(
        (
            mapped.bestand,
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
    assert legacy.bestand_name(_row(collection="")) == legacy.UNSORTIERT


def test_the_bestand_names_are_the_legacy_ones_plus_unsortiert() -> None:
    rows = [_row(collection="Bund"), _row(collection=""), _row(collection="Orden St. Georg")]
    assert legacy.bestand_names(rows) == ("Bund", "Orden St. Georg", legacy.UNSORTIERT)


# --- keywords -> tags ---------------------------------------------------------------


def test_keywords_split_on_the_dashes_then_on_whitespace() -> None:
    article = _map(_row(keywords="Filmaufnahmen -- Jugendbewegung Pfadfinder")).article
    assert article.tags == ("Filmaufnahmen", "Jugendbewegung", "Pfadfinder")


def test_keywords_lose_their_carriage_returns_and_duplicates_but_keep_their_order() -> None:
    article = _map(_row(keywords="Lager\r -- Fahrt\r\n-- Lager -- Bund")).article
    assert article.tags == ("Lager", "Fahrt", "Bund")


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
    assert dict(report.per_bestand) == {"Bund": 2, legacy.UNSORTIERT: 1}
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


def test_the_report_reads_as_lines_a_human_can_scan() -> None:
    lines = _plan().report.lines()
    assert any("3" in line for line in lines)
    assert all(isinstance(line, str) for line in lines)
