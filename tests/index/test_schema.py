import pytest

from bundesarchiv.index.models import ArticleIndex


def _make(ulid: str, **overrides: object) -> ArticleIndex:
    fields: dict[str, object] = {
        "ulid": ulid,
        "title": "",
        "collection_id": "C1",
        "archivist_only": False,
        "tier": "PUBLIC",
        "config_version": 1,
    }
    fields.update(overrides)
    return ArticleIndex.objects.create(**fields)


# --- Generated tsvector columns populate on an ORM insert -------------------------------------


@pytest.mark.django_db
def test_general_tsv_populates_with_german_stemming_and_weights() -> None:
    row = _make(
        "01GEN",
        title="Bundeslager",
        body="Häuser und Bäume",
        tags=["Fahrten", "Lieder"],
        ref_code="B 12",
    )
    row.refresh_from_db()  # generated columns are computed by the DB, not Python
    tsv = str(row.general_tsv)
    assert tsv, "general_tsv should be non-empty after insert"
    # German stem of "Bundeslager" is "bundeslag", carried at weight A (from the title).
    assert "'bundeslag':1A" in tsv, tsv
    # A tag word and a stemmed, umlaut-folded body word (Bäume -> baum).
    assert "'fahrt'" in tsv and "'baum'" in tsv, tsv


@pytest.mark.django_db
def test_archivist_tsv_populates_from_archivist_text() -> None:
    """The archivist tsvector is a plain (unweighted) to_tsvector of ``archivist_text``."""
    row = _make("01ARC", archivist_text="Standort Regal 4")
    row.refresh_from_db()
    tsv = str(row.archivist_tsv)
    assert tsv, "archivist_tsv should be non-empty when archivist_text is set"
    assert "standort" in tsv and "regal" in tsv, tsv
    # No weight labels on the archivist vector (weights are A/B/C/D suffixes on lexeme positions).
    assert "A" not in tsv and "B" not in tsv, f"archivist_tsv must be unweighted, got {tsv}"
