"""Shared search fixture — one indexed corpus built via ``rebuild`` from an InMemory store.

Task 8 (``test_search.py``) and Task 9 (the visibility grid / equivalence) both drive the
same corpus, so it lives here once rather than being copied. It is deliberately built the real
way — Collections + Articles saved through the repositories, then ``indexer.rebuild`` — so the
generated ``tsvector`` columns, the scope columns, the date/decade columns and the collection
ancestry are all produced by the production code path, not hand-poked into rows.

Shape (a ~3-level collection tree, 12 articles spanning tiers / groups / lifecycles / dates /
tags / media+document types):

    ROOT  "Bundesarchiv"                       (Members default)
    +- FOTOS "Fotografien"          PUBLIC
    |    +- LAGER "Lagerfotos"      (inherits PUBLIC)
    +- AKTEN "Aktenbestand"         MEMBERS
         +- VORSTAND "Vorstandsakten"   GROUPS {vorstand}

Every article's expected visibility, per-viewer, is captured in :data:`EXPECTED_VISIBILITY`
so Task 9 can assert the grid without re-deriving it. The three viewers used across the tests
are the module-level singletons below.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

# The three viewers the search tests reuse. PLAIN_MEMBER holds no groups (never clears a GROUPS
# rung); VORSTAND_MEMBER holds "vorstand" (clears the VORSTAND collection's GROUPS rung).
ARCHIVIST = Archivist()
PLAIN_MEMBER = Member(())
VORSTAND_MEMBER = Member(("vorstand",))
PUBLIC = Public()


@dataclass(frozen=True, slots=True)
class FixtureArticle:
    """One row of the corpus, with everything a test needs to assert about it: the ulid, and
    which viewers should see it. ``visible_to`` is the set of viewer *labels* ("archivist",
    "vorstand", "member", "public") that ``search`` must return this article for."""

    ulid: str
    title: str
    visible_to: frozenset[str]


# The corpus manifest — ulid -> the labels that may see it. This is the ground truth Task 9's
# grid compares ``search`` against; Task 8 uses it to compute per-viewer expected counts.
EXPECTED_VISIBILITY: dict[str, frozenset[str]] = {
    # PUBLIC-tier, published: everyone.
    "ART_PUBFOTO": frozenset({"archivist", "vorstand", "member", "public"}),
    "ART_PUBLAGER": frozenset({"archivist", "vorstand", "member", "public"}),
    "ART_PUBHAUS": frozenset({"archivist", "vorstand", "member", "public"}),
    # MEMBERS-tier (explicit or inherited/default): members + archivist, not public.
    "ART_MEMAKTE": frozenset({"archivist", "vorstand", "member"}),
    "ART_MEMNOTIZ": frozenset({"archivist", "vorstand", "member"}),
    "ART_MEMBRIEF": frozenset({"archivist", "vorstand", "member"}),
    # GROUPS {vorstand}: only a member holding vorstand, + archivist.
    "ART_GRPPROT": frozenset({"archivist", "vorstand"}),
    "ART_GRPBESCH": frozenset({"archivist", "vorstand"}),
    # DRAFT lifecycle -> archivist-only regardless of audience.
    "ART_DRAFT": frozenset({"archivist"}),
    # Dangling collection_id -> fail-closed archivist-only row.
    "ART_ORPHAN": frozenset({"archivist"}),
    # Two more PUBLIC articles to give facets/pagination real spread.
    "ART_PUBKARTE": frozenset({"archivist", "vorstand", "member", "public"}),
    "ART_PUBPLAKAT": frozenset({"archivist", "vorstand", "member", "public"}),
}


def build_store() -> InMemoryObjectStore:
    """A populated InMemory store: the 3-level tree and 12 articles described in the module
    docstring. Saved through the real repositories so ``rebuild`` sees canonical READMEs."""
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    collections.save(Collection(ulid="ROOT", name="Bundesarchiv", parent_id=None), 0)
    collections.save(
        Collection(
            ulid="FOTOS",
            name="Fotografien",
            parent_id="ROOT",
            audience=Audience(AudienceTier.PUBLIC),
        ),
        0,
    )
    collections.save(Collection(ulid="LAGER", name="Lagerfotos", parent_id="FOTOS"), 0)
    collections.save(
        Collection(
            ulid="AKTEN",
            name="Aktenbestand",
            parent_id="ROOT",
            audience=Audience(AudienceTier.MEMBERS),
        ),
        0,
    )
    collections.save(
        Collection(
            ulid="VORSTAND",
            name="Vorstandsakten",
            parent_id="AKTEN",
            audience=Audience(AudienceTier.GROUPS, ("vorstand",)),
        ),
        0,
    )

    for article in _articles():
        articles.save(article, 0)

    return store


def build_index() -> indexer.RebuildReport:
    """Build the store AND rebuild the index from it. Returns the ``RebuildReport`` (the
    django_db fixture in ``test_search.py`` calls this)."""
    return indexer.rebuild(build_store())


def indexed_corpus[T](
    django_db_blocker: pytest.FixtureRequest, build: Callable[[], T]
) -> Iterator[T]:
    """THE single index-isolation mechanism for ``tests/index/``: build + index a corpus outside
    the per-test transaction, then wipe ``ArticleIndex`` when the requesting module is done.

    ``rebuild`` commits rows with the db blocker unblocked, so no per-test transaction ever rolls
    them back — a corpus left behind leaks into any later module that assumes an empty table
    (``test_schema`` was green only by alphabetical luck before this existed). Every module-scoped
    corpus fixture must ``yield from`` this helper; none may add its own wipe. Deliberately NOT an
    autouse conftest fixture: that would have to touch the DB after EVERY module in this directory,
    breaking the documented guarantee that the pure architecture checks run without Postgres.
    """
    from bundesarchiv.index.models import ArticleIndex

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        yield build()
        ArticleIndex.objects.all().delete()


def _articles() -> tuple[Article, ...]:
    """The 12 corpus articles. German text is chosen so ADR-0011 stemming/umlaut behaviour is
    exercisable (Häuser/Haus, Bäume, Fahrten, Lieder), spanning media/document types, tags,
    decades and one open-ended date."""
    return (
        # --- PUBLIC (via FOTOS / LAGER) ---
        Article(
            ulid="ART_PUBFOTO",
            title="Öffentliches Foto der Fahrten",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="B 2",
            media_type="Foto",
            document_type="Fotografie",
            tags=("fahrten", "lager"),
            date=EdtfDate("1965"),
            creator="Hans Müller",
        ),
        Article(
            ulid="ART_PUBLAGER",
            title="Bundeslager Lieder und Häuser",
            collection_id="LAGER",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="B 10",
            media_type="Foto",
            document_type="Fotografie",
            tags=("lieder", "lager"),
            date=EdtfDate("1972"),
        ),
        Article(
            ulid="ART_PUBHAUS",
            title="Bäume vor dem Haus",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="B 1",
            media_type="Foto",
            document_type="Karte",
            tags=("natur",),
            date=EdtfDate("1981"),
        ),
        Article(
            ulid="ART_PUBKARTE",
            title="Historische Wanderkarte",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="K 3",
            media_type="Karte",
            document_type="Karte",
            tags=("natur", "fahrten"),
            date=EdtfDate("1958"),
        ),
        Article(
            ulid="ART_PUBPLAKAT",
            title="Plakat zum Singewettstreit",
            collection_id="LAGER",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="P 20",
            media_type="Plakat",
            document_type="Plakat",
            tags=("lieder",),
            # Open-ended date (open upper end): 1970 onward, latest is NULL.
            date=EdtfDate("1970/.."),
        ),
        # --- MEMBERS (explicit AKTEN / inherited) ---
        Article(
            ulid="ART_MEMAKTE",
            title="Vertrauliche Mitgliederakte",
            collection_id="AKTEN",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="A 5",
            media_type="Akte",
            document_type="Schriftstueck",
            tags=("mitglieder",),
            date=EdtfDate("1975"),
        ),
        Article(
            ulid="ART_MEMNOTIZ",
            title="Interne Notiz der Fahrten",
            collection_id="AKTEN",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="A 12",
            media_type="Akte",
            document_type="Schriftstueck",
            tags=("fahrten", "mitglieder"),
            date=EdtfDate("1988"),
        ),
        Article(
            # Inherits MEMBERS from ROOT default (no explicit audience, ROOT is silent -> MEMBERS).
            ulid="ART_MEMBRIEF",
            title="Briefwechsel im Bund",
            collection_id="ROOT",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="A 1",
            media_type="Akte",
            document_type="Brief",
            tags=("mitglieder",),
            date=EdtfDate("1990"),
        ),
        # --- GROUPS {vorstand} ---
        Article(
            ulid="ART_GRPPROT",
            title="Protokoll der Vorstandssitzung",
            collection_id="VORSTAND",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="V 2",
            media_type="Akte",
            document_type="Protokoll",
            tags=("vorstand", "protokoll"),
            date=EdtfDate("1995"),
            physical_location="Tresor 1",
        ),
        Article(
            ulid="ART_GRPBESCH",
            title="Beschluss der Fahrten-Ordnung",
            collection_id="VORSTAND",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="V 10",
            media_type="Akte",
            document_type="Protokoll",
            tags=("vorstand", "fahrten"),
            date=EdtfDate("2001"),
            # Archivist-only text: the word "Geheimregal" appears ONLY here, in physical_location.
            physical_location="Geheimregal 7",
        ),
        # --- DRAFT (archivist-only regardless of audience) ---
        Article(
            ulid="ART_DRAFT",
            title="Entwurf einer Chronik",
            collection_id="FOTOS",
            lifecycle=Lifecycle.DRAFT,
            ref_code="D 1",
            media_type="Akte",
            document_type="Chronik",
            tags=("entwurf",),
            date=EdtfDate("2010"),
        ),
        # --- Dangling collection_id -> fail-closed archivist-only row (no ancestors) ---
        Article(
            ulid="ART_ORPHAN",
            title="Verwaistes Dokument Lieder",
            collection_id="GHOST",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="O 1",
            media_type="Akte",
            document_type="Unbekannt",
            tags=("verwaist",),
            date=EdtfDate("1969"),
        ),
    )
