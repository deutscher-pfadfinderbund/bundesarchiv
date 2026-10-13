"""Shared search corpus: collections and articles saved through the repositories, then indexed by
``rebuild``.

    ROOT  "Bundesarchiv"                       (no audience: MEMBERS default)
    +- FOTOS "Fotografien"          PUBLIC
    |    +- LAGER "Lagerfotos"      (inherits PUBLIC)
    +- AKTEN "Aktenbestand"         MEMBERS
         +- VORSTAND "Vorstandsakten"   GROUPS {vorstand}

Per-viewer ground truth: ``EXPECTED_VISIBILITY``.
"""

import io
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace

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

# BOARD_MEMBER holds "vorstand", the group that clears the VORSTAND collection.
ARCHIVIST = Archivist()
PLAIN_MEMBER = Member(())
BOARD_MEMBER = Member(("vorstand",))
PUBLIC = Public()


@dataclass(frozen=True, slots=True)
class FixtureArticle:
    """One row of the corpus, with everything a test needs to assert about it: the ulid, and
    which viewers should see it. ``visible_to`` is the set of viewer *labels* ("archivist",
    "vorstand", "member", "public") that ``search`` must return this article for."""

    ulid: str
    title: str
    visible_to: frozenset[str]


# ulid -> the viewer labels ``search`` must return it for.
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
    """The corpus, saved through the real repositories so ``rebuild`` reads canonical READMEs."""
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    collections.save(
        Collection(ulid="ROOT", name="Bundesarchiv", parent_id=None), 0, changed_by="tester"
    )
    collections.save(
        Collection(
            ulid="FOTOS",
            name="Fotografien",
            parent_id="ROOT",
            audience=Audience(AudienceTier.PUBLIC),
        ),
        0,
        changed_by="tester",
    )
    collections.save(
        Collection(ulid="LAGER", name="Lagerfotos", parent_id="FOTOS"), 0, changed_by="tester"
    )
    collections.save(
        Collection(
            ulid="AKTEN",
            name="Aktenbestand",
            parent_id="ROOT",
            audience=Audience(AudienceTier.MEMBERS),
        ),
        0,
        changed_by="tester",
    )
    collections.save(
        Collection(
            ulid="VORSTAND",
            name="Vorstandsakten",
            parent_id="AKTEN",
            audience=Audience(AudienceTier.GROUPS, ("vorstand",)),
        ),
        0,
        changed_by="tester",
    )

    for article in _articles():
        articles.save(_with_captioned_media(articles, article), 0, changed_by="tester")

    return store


# Each word appears nowhere else in the corpus, so a search for it probes only the caption channel
# (ADR 0015); one article per visibility case.
CAPTION_WORDS: dict[str, str] = {
    "ART_PUBFOTO": "Zeltwiese",
    "ART_GRPPROT": "Tresornotiz",
    "ART_DRAFT": "Skizzenblatt",
}


def _with_captioned_media(articles: ArticleRepository, article: Article) -> Article:
    """Attach one captioned media file to the articles named in ``CAPTION_WORDS``; the blob goes
    through ``add_media`` because ``save`` refuses unstored media."""
    word = CAPTION_WORDS.get(article.ulid)
    if word is None:
        return article
    ref = articles.add_media(
        article.ulid,
        f"{article.ulid.lower()}-media.jpg",
        io.BytesIO(f"bytes for {article.ulid}".encode()),
        media_type="image/jpeg",
        caption=f"Aufnahme: {word}",
    )
    return replace(article, media=(ref,))


def build_index() -> indexer.RebuildReport:
    return indexer.rebuild(build_store())


def indexed_corpus[T](
    django_db_blocker: pytest.FixtureRequest, build: Callable[[], T]
) -> Iterator[T]:
    """The index-isolation mechanism for ``tests/index/``: build and index a corpus outside the
    per-test transaction, wipe ``ArticleIndex`` at module teardown.

    ``rebuild`` commits, so no test transaction rolls the rows back. Every module-scoped corpus
    fixture yields from this and adds no wipe of its own; not autouse, so the directory's no-DB
    tests stay DB-free. A test that needs one more row beside the corpus uses
    ``index_beside_corpus``.
    """
    from bundesarchiv.index.models import ArticleIndex

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        yield build()
        ArticleIndex.objects.all().delete()


def index_beside_corpus(root: Collection, *articles: Article) -> None:
    """Index ``articles`` (all under ``root``) beside the indexed corpus, without the rebuild wipe;
    call inside a test's transaction so the rows roll back."""
    store = InMemoryObjectStore()
    CollectionRepository(store).save(root, 0, changed_by="tester")
    repo = ArticleRepository(store)
    for article in articles:
        repo.save(article, 0, changed_by="tester")
        indexer.index_article(store, article.ulid)


def _articles() -> tuple[Article, ...]:
    """The corpus articles; the German text exercises ADR 0011 stemming and umlauts (Häuser/Haus,
    Bäume, Fahrten, Lieder)."""
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
            # Open upper end: the indexed date_latest is NULL.
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
            # No audience on the chain: the MEMBERS default.
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
