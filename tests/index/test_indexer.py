"""Task 7 — the scope seam + fail-closed indexer.

Two halves:

- ``build_row`` is PURE: Article + resolved chain -> column dict. Every case in the first
  section runs WITHOUT a database (no ``django_db`` mark, no store fixture) — the purity
  guard. It only ever references ORM column names as dict keys, never touches the ORM.
- ``rebuild`` is the IO edge: it wipes + re-reads everything through the repositories and
  writes ``ArticleIndex`` rows in one transaction. Those cases are ``django_db`` and drive a
  real Postgres via an in-memory ObjectStore fixture (nested Collections, a dangling
  ``collection_id`` -> fail-closed row, a draft -> archivist-only).

The scope seam itself (``_scope_columns`` / ``_viewer_scope``) is the single place
viewer-visibility meets SQL; equivalence to ``domain.access.can_view`` is pinned by Task 9's
``test_equivalence.py``. Here we pin the write-side column mapping.
"""

import datetime
import io

import pytest

from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
    MediaRef,
)
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index import indexer
from bundesarchiv.index.query import FileKind, SearchFilters, search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

# ``cap_year`` is injected so build_row stays pure; a fixed value keeps decade assertions stable.
_CAP_YEAR = 2026


# ---------------------------------------------------------------------------
# Helpers — a chain from a single Collection (leaf == root), and multi-level chains.
# ---------------------------------------------------------------------------


def _root(ulid: str = "ROOT", **overrides: object) -> Collection:
    defaults: dict[str, object] = {"ulid": ulid, "name": "Root", "parent_id": None}
    defaults.update(overrides)
    return Collection(**defaults)  # type: ignore[arg-type]


def _chain(*collections: Collection) -> ResolvedChain:
    """A resolved chain, leaf-first. Callers pass leaf ... root."""
    return ResolvedChain(collections)


def _article(collection_id: str = "ROOT", **overrides: object) -> Article:
    defaults: dict[str, object] = {
        "ulid": "01ART",
        "title": "Ein Titel",
        "collection_id": collection_id,
        "lifecycle": Lifecycle.PUBLISHED,
    }
    defaults.update(overrides)
    return Article(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# SECTION 1 — build_row purity. NO db fixture, NO django_db. Pure column mapping.
# ===========================================================================


def test_build_row_explicit_public_audience() -> None:
    root = _root()
    article = _article(audience=Audience(AudienceTier.PUBLIC))
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["archivist_only"] is False
    assert row["tier"] == "PUBLIC"
    assert row["groups"] == []


def test_build_row_explicit_members_audience() -> None:
    root = _root()
    article = _article(audience=Audience(AudienceTier.MEMBERS))
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["archivist_only"] is False
    assert row["tier"] == "MEMBERS"
    assert row["groups"] == []


def test_build_row_explicit_groups_audience_carries_groups() -> None:
    root = _root()
    article = _article(audience=Audience(AudienceTier.GROUPS, ("bundesfuehrung", "vorstand")))
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["archivist_only"] is False
    assert row["tier"] == "GROUPS"
    assert row["groups"] == ["bundesfuehrung", "vorstand"]


def test_build_row_silent_chain_defaults_to_members() -> None:
    root = _root()  # no audience anywhere
    article = _article(audience=None)
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["archivist_only"] is False
    assert row["tier"] == "MEMBERS"


def test_build_row_draft_lifecycle_is_archivist_only() -> None:
    root = _root(audience=Audience(AudienceTier.PUBLIC))
    article = _article(lifecycle=Lifecycle.DRAFT, audience=Audience(AudienceTier.PUBLIC))
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["archivist_only"] is True
    assert row["tier"] is None  # None iff archivist_only
    assert row["groups"] == []


def test_build_row_still_indexes_text_of_a_draft() -> None:
    """An archivist-only row still carries title/body so an Archivist can find it."""
    root = _root()
    article = _article(lifecycle=Lifecycle.DRAFT, title="Geheim", body="Notizen")
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["title"] == "Geheim"
    assert row["body"] == "Notizen"


# --- media captions join the body-weight FTS bucket (ADR 0015) --------------


def test_build_row_appends_media_captions_to_the_body_bucket() -> None:
    """Media captions join the article's FTS document at BODY weight: build_row concatenates them,
    order-preserving, into the same column the body text feeds (weight D in the general tsvector).
    The body text stays first; captions follow in media order."""
    root = _root()
    article = _article(
        body="Ein Bericht.",
        media=(
            MediaRef("a.mp3", "9" * 64, caption="Sprecher unbekannt"),
            MediaRef("b.jpg", "c" * 64),  # uncaptioned -> contributes nothing
            MediaRef("c.jpg", "d" * 64, caption="Huelle vorne"),
        ),
    )
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    body = row["body"]
    assert isinstance(body, str)
    assert body.startswith("Ein Bericht.")  # the real body text leads
    assert "Sprecher unbekannt" in body
    assert "Huelle vorne" in body
    # order-preserving: the first caption precedes the third
    assert body.index("Sprecher unbekannt") < body.index("Huelle vorne")


def test_build_row_body_unchanged_without_captions() -> None:
    """No captions -> the body column is exactly the article body (no trailing whitespace/joins)."""
    root = _root()
    article = _article(body="Nur Text.", media=(MediaRef("a.jpg", "a" * 64),))
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["body"] == "Nur Text."


def test_build_row_counts_files_per_kind_by_mime_else_extension() -> None:
    article = _article(
        media=(
            MediaRef("scan.pdf", "1" * 64, media_type="application/pdf"),
            MediaRef("a.JPG", "2" * 64),
            MediaRef("b.pdf", "3" * 64, media_type="image/png"),
            MediaRef("film.mp4", "4" * 64),
            MediaRef("ton.wav", "5" * 64, media_type="audio/x-wav"),
            MediaRef("paket.zip", "6" * 64, media_type="application/zip"),
            MediaRef("ohne-endung", "7" * 64),
        ),
    )
    row = indexer.build_row(article, _chain(_root()), cap_year=_CAP_YEAR)
    assert row["file_counts"] == {"pdf": 1, "image": 2, "video": 1, "audio": 1, "other": 2}


# --- date columns ----------------------------------------------------------


def test_build_row_date_bounds_and_decades() -> None:
    root = _root()
    article = _article(date=EdtfDate("1965/1978"))
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["date_edtf"] == "1965/1978"
    assert row["date_earliest"] == datetime.date(1965, 1, 1)
    assert row["date_latest"] == datetime.date(1978, 12, 31)
    assert row["decades"] == [1960, 1970]


def test_build_row_open_ended_date_has_null_latest() -> None:
    root = _root()
    article = _article(date=EdtfDate("1970/.."))
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["date_earliest"] == datetime.date(1970, 1, 1)
    assert row["date_latest"] is None  # open end
    # decades run from the earliest up to (not incl.) cap_year's decade.
    assert row["decades"] == [1970, 1980, 1990, 2000, 2010, 2020]


def test_build_row_no_date_yields_nulls_and_empty_decades() -> None:
    root = _root()
    article = _article(date=None)
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert row["date_edtf"] is None
    assert row["date_earliest"] is None
    assert row["date_latest"] is None
    assert row["decades"] == []


# --- archivist_text --------------------------------------------------------


def test_build_row_archivist_text_folds_location_and_custom_values() -> None:
    root = _root()
    article = _article(
        physical_location="Regal 4",
        custom=(("Provenienz", "Nachlass Müller"), ("Zustand", "brüchig")),
    )
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    text = row["archivist_text"]
    assert isinstance(text, str)
    assert "Regal 4" in text
    assert "Nachlass Müller" in text
    assert "brüchig" in text


def test_build_row_archivist_text_excludes_custom_keys() -> None:
    """Keys are structure, not prose — only the VALUES land in archivist_text."""
    root = _root()
    article = _article(custom=(("Provenienz", "Nachlass Müller"),))
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert "Nachlass Müller" in str(row["archivist_text"])
    assert "Provenienz" not in str(row["archivist_text"])


def test_build_row_archivist_text_excludes_member_visible_fields() -> None:
    """A member-visible field (title/body/creator) must never leak into archivist_text."""
    root = _root()
    article = _article(
        title="Sichtbarer Titel",
        body="Sichtbarer Text",
        creator="Sichtbarer Urheber",
        physical_location="Regal 4",
    )
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    text = str(row["archivist_text"])
    assert "Regal 4" in text
    assert "Sichtbarer Titel" not in text
    assert "Sichtbarer Text" not in text
    assert "Sichtbarer Urheber" not in text


def test_build_row_archivist_text_empty_without_sources() -> None:
    root = _root()
    article = _article(physical_location=None, custom=())
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert str(row["archivist_text"]).strip() == ""


# --- collection_ancestors --------------------------------------------------


def test_build_row_ancestors_are_leaf_to_root_including_own_collection() -> None:
    root = _root("ROOT")
    mid = Collection(ulid="MID", name="Mid", parent_id="ROOT")
    leaf = Collection(ulid="LEAF", name="Leaf", parent_id="MID")
    article = _article(collection_id="LEAF")
    row = indexer.build_row(article, _chain(leaf, mid, root), cap_year=_CAP_YEAR)
    assert row["collection_ancestors"] == ["LEAF", "MID", "ROOT"]
    assert row["collection_id"] == "LEAF"


# ===========================================================================
# SECTION 2 — rebuild end-to-end against real Postgres via an in-memory store.
# ===========================================================================


@pytest.fixture
def store() -> InMemoryObjectStore:
    """A populated store: 3 nested Collections (one audience-carrying), 5 Articles including
    one with a dangling collection_id (fail-closed) and one draft (archivist-only)."""
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    # Tree: ROOT (Members default) -> FOTOS (PUBLIC) -> AKTEN (inherits PUBLIC)
    collections.save(_root("ROOT", name="Wurzel"), 0, changed_by="tester")
    collections.save(
        Collection(
            ulid="FOTOS", name="Fotos", parent_id="ROOT", audience=Audience(AudienceTier.PUBLIC)
        ),
        0,
        changed_by="tester",
    )
    collections.save(
        Collection(ulid="AKTEN", name="Akten", parent_id="FOTOS"), 0, changed_by="tester"
    )

    # 1. Published, inherits PUBLIC from FOTOS.
    articles.save(
        _article("FOTOS", ulid="01PUB", title="Öffentliches Foto", date=EdtfDate("1965")),
        0,
        changed_by="tester",
    )
    # 2. Published, explicit GROUPS.
    articles.save(
        _article(
            "AKTEN",
            ulid="01GRP",
            title="Vertrauliche Akte",
            audience=Audience(AudienceTier.GROUPS, ("vorstand",)),
        ),
        0,
        changed_by="tester",
    )
    # 3. Published at ROOT -> Members default.
    articles.save(_article("ROOT", ulid="01MEM", title="Mitglieder-Notiz"), 0, changed_by="tester")
    # 4. Draft -> archivist-only regardless of audience.
    articles.save(
        _article("FOTOS", ulid="01DRF", title="Entwurf", lifecycle=Lifecycle.DRAFT),
        0,
        changed_by="tester",
    )
    # 5. Dangling collection_id -> resolve_chain fails -> fail-closed row.
    articles.save(
        _article("GHOST", ulid="01BAD", title="Verwaistes Artikel"), 0, changed_by="tester"
    )

    return store


@pytest.mark.django_db
def test_rebuild_maps_scope_columns_per_article(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.rebuild(store)
    by_ulid = {row.ulid: row for row in ArticleIndex.objects.all()}

    assert by_ulid["01PUB"].tier == "PUBLIC"
    assert by_ulid["01PUB"].archivist_only is False

    assert by_ulid["01GRP"].tier == "GROUPS"
    assert list(by_ulid["01GRP"].groups) == ["vorstand"]

    assert by_ulid["01MEM"].tier == "MEMBERS"

    assert by_ulid["01DRF"].archivist_only is True
    assert by_ulid["01DRF"].tier is None


@pytest.mark.django_db
def test_rebuild_fails_closed_on_dangling_collection(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    report = indexer.rebuild(store)
    assert "01BAD" in report.failed_closed

    bad = ArticleIndex.objects.get(ulid="01BAD")
    assert bad.archivist_only is True  # fail-closed: only an Archivist can find it
    assert bad.tier is None
    assert list(bad.groups) == []
    assert (
        bad.is_draft is False
    )  # a broken chain is NOT a draft — draft-vs-failclosed stay distinct
    assert bad.title == "Verwaistes Artikel"  # still indexed with its text, so it's findable


@pytest.mark.django_db
def test_rebuild_is_idempotent(store: InMemoryObjectStore) -> None:
    """A second rebuild wipes and re-writes: the same row count, no duplicates."""
    from bundesarchiv.index.models import ArticleIndex

    first = indexer.rebuild(store)
    second = indexer.rebuild(store)
    assert first.indexed == second.indexed == 5
    assert ArticleIndex.objects.count() == 5  # no dupes
    assert second.failed_closed == ("01BAD",)


@pytest.mark.django_db
def test_rebuild_empty_store_indexes_nothing(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    empty = InMemoryObjectStore()
    ArticleIndex.objects.create(
        ulid="STALE",
        title="stale",
        collection_id="X",
        archivist_only=False,
        tier="PUBLIC",
        config_version=1,
    )
    report = indexer.rebuild(empty)
    assert report.indexed == 0
    assert report.failed_closed == ()
    assert ArticleIndex.objects.count() == 0  # the wipe cleared the stale row


@pytest.mark.django_db
def test_the_added_sort_is_newest_first_unknown_last_ulid_breaking_ties() -> None:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(_root(), 0, changed_by="tester")
    articles = ArticleRepository(store)
    newer = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    older = datetime.datetime(2017, 6, 26, 6, 6, 40, tzinfo=datetime.UTC)
    for ulid, added_at in (("01C", None), ("01D", newer), ("01B", older), ("01A", newer)):
        articles.save(_article(ulid=ulid, added_at=added_at), 0, changed_by="tester")
    indexer.rebuild(store)

    hits = search(Archivist(), sort="added").hits
    assert [hit.ulid for hit in hits] == ["01A", "01D", "01B", "01C"]


@pytest.mark.django_db
def test_a_hit_summarizes_its_files_and_the_files_filter_reads_the_same_fact() -> None:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(_root(), 0, changed_by="tester")
    articles = ArticleRepository(store)
    media = tuple(
        articles.add_media("01MIX", name, io.BytesIO(name.encode()), media_type=mime)
        for name, mime in (("brief.pdf", "application/pdf"), ("a.jpg", None), ("b.jpg", None))
    )
    articles.save(_article(ulid="01MIX", media=media), 0, changed_by="tester")
    articles.save(_article(ulid="01NIX"), 0, changed_by="tester")
    indexer.rebuild(store)

    hits = {hit.ulid: hit for hit in search(Archivist()).hits}
    assert hits["01MIX"].file_counts == ((FileKind.IMAGE, 2), (FileKind.PDF, 1))
    assert hits["01NIX"].file_counts == ()
    assert hits["01MIX"].collection_id == "ROOT"
    with_files = search(Archivist(), filters=SearchFilters(has_files=True)).hits
    assert [hit.ulid for hit in with_files] == ["01MIX"]


# ===========================================================================
# Drift guard — archivist_text builder is tied to the domain floor.
# ===========================================================================


def test_archivist_text_builder_tracks_the_domain_floor() -> None:
    """A member-visible field never reaches archivist_text; a floor field does."""
    # A field NOT in the floor (creator is member-visible) never appears in archivist_text.
    root = _root()
    article = _article(creator="Nicht Geheim", physical_location="Regal 9")
    row = indexer.build_row(article, _chain(root), cap_year=_CAP_YEAR)
    assert "Nicht Geheim" not in str(row["archivist_text"])
    assert "Regal 9" in str(row["archivist_text"])
