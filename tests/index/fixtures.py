"""Shared search corpus (``build_store``; per-viewer truth in ``EXPECTED_VISIBILITY``):

ROOT  "Bundesarchiv"                       (no audience: MEMBERS default)
+- FOTOS "Fotografien"          PUBLIC
|    +- LAGER "Lagerfotos"      (inherits PUBLIC)
+- AKTEN "Aktenbestand"         MEMBERS
     +- VORSTAND "Vorstandsakten"   GROUPS {vorstand}
"""

import io
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace

import pytest

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    ULID,
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

ID_AKTEN = ULID("AKTEN")
ID_FOTOS = ULID("FOTOS")
ID_ROOT = ULID("ROOT")

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
    """Saved through the real repositories so ``rebuild`` reads canonical READMEs."""
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    collections.save(
        Collection(ulid=ID_ROOT, name="Bundesarchiv", parent_id=None), 0, changed_by="tester"
    )
    collections.save(
        Collection(
            ulid=ID_FOTOS,
            name="Fotografien",
            parent_id=ID_ROOT,
            audience=Audience(AudienceTier.PUBLIC),
        ),
        0,
        changed_by="tester",
    )
    collections.save(
        Collection(ulid=ULID("LAGER"), name="Lagerfotos", parent_id=ID_FOTOS),
        0,
        changed_by="tester",
    )
    collections.save(
        Collection(
            ulid=ID_AKTEN,
            name="Aktenbestand",
            parent_id=ID_ROOT,
            audience=Audience(AudienceTier.MEMBERS),
        ),
        0,
        changed_by="tester",
    )
    collections.save(
        Collection(
            ulid=ULID("VORSTAND"),
            name="Vorstandsakten",
            parent_id=ID_AKTEN,
            audience=Audience(AudienceTier.GROUPS, ("vorstand",)),
        ),
        0,
        changed_by="tester",
    )

    for article in _articles():
        articles.save(_with_captioned_media(articles, article), 0, changed_by="tester")

    return store


# Each word appears nowhere else in the corpus, so a search for it probes only the caption channel
# (ADR 0015).
CAPTION_WORDS: dict[str, str] = {
    "ART_PUBFOTO": "Zeltwiese",
    "ART_GRPPROT": "Tresornotiz",
    "ART_DRAFT": "Skizzenblatt",
}


def _with_captioned_media(articles: ArticleRepository, article: Article) -> Article:
    """``save`` refuses unstored media, so the blob goes through ``add_media`` first."""
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
    """``rebuild`` commits, so no test transaction rolls the rows back: this wipes ``ArticleIndex``
    at teardown. Every module-scoped corpus fixture yields from it and adds no wipe of its own; not
    autouse, so no-DB tests stay DB-free. One more row beside the corpus: ``index_beside_corpus``.
    """
    from bundesarchiv.index.models import ArticleIndex

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        yield build()
        ArticleIndex.objects.all().delete()


def index_beside_corpus(root: Collection, *articles: Article) -> None:
    """``articles`` all sit under ``root``. Call inside a test's transaction so the rows roll back:
    unlike ``rebuild`` this wipes nothing."""
    store = InMemoryObjectStore()
    CollectionRepository(store).save(root, 0, changed_by="tester")
    repo = ArticleRepository(store)
    for article in articles:
        repo.save(article, 0, changed_by="tester")
        indexer.index_article(store, article.ulid)


def _articles() -> tuple[Article, ...]:
    """The German text exercises ADR 0011 stemming and umlauts (Häuser/Haus, Bäume, Fahrten,
    Lieder)."""
    return (
        # --- PUBLIC (via FOTOS / LAGER) ---
        Article(
            ulid=ULID("ART_PUBFOTO"),
            title="Öffentliches Foto der Fahrten",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="B 2",
            media_type="Foto",
            document_type="Fotografie",
            tags=("fahrten", "lager"),
            date=EdtfDate("1965"),
            creator="Hans Müller",
        ),
        Article(
            ulid=ULID("ART_PUBLAGER"),
            title="Bundeslager Lieder und Häuser",
            collection_id=ULID("LAGER"),
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="B 10",
            media_type="Foto",
            document_type="Fotografie",
            tags=("lieder", "lager"),
            date=EdtfDate("1972"),
        ),
        Article(
            ulid=ULID("ART_PUBHAUS"),
            title="Bäume vor dem Haus",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="B 1",
            media_type="Foto",
            document_type="Karte",
            tags=("natur",),
            date=EdtfDate("1981"),
        ),
        Article(
            ulid=ULID("ART_PUBKARTE"),
            title="Historische Wanderkarte",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="K 3",
            media_type="Karte",
            document_type="Karte",
            tags=("natur", "fahrten"),
            date=EdtfDate("1958"),
        ),
        Article(
            ulid=ULID("ART_PUBPLAKAT"),
            title="Plakat zum Singewettstreit",
            collection_id=ULID("LAGER"),
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="P 20",
            media_type="Plakat",
            document_type="Plakat",
            tags=("lieder",),
            # the indexed date_latest is NULL
            date=EdtfDate("1970/.."),
        ),
        # --- MEMBERS (explicit AKTEN / inherited) ---
        Article(
            ulid=ULID("ART_MEMAKTE"),
            title="Vertrauliche Mitgliederakte",
            collection_id=ID_AKTEN,
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="A 5",
            media_type="Akte",
            document_type="Schriftstueck",
            tags=("mitglieder",),
            date=EdtfDate("1975"),
        ),
        Article(
            ulid=ULID("ART_MEMNOTIZ"),
            title="Interne Notiz der Fahrten",
            collection_id=ID_AKTEN,
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="A 12",
            media_type="Akte",
            document_type="Schriftstueck",
            tags=("fahrten", "mitglieder"),
            date=EdtfDate("1988"),
        ),
        Article(
            ulid=ULID("ART_MEMBRIEF"),
            title="Briefwechsel im Bund",
            collection_id=ID_ROOT,
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="A 1",
            media_type="Akte",
            document_type="Brief",
            tags=("mitglieder",),
            date=EdtfDate("1990"),
        ),
        # --- GROUPS {vorstand} ---
        Article(
            ulid=ULID("ART_GRPPROT"),
            title="Protokoll der Vorstandssitzung",
            collection_id=ULID("VORSTAND"),
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="V 2",
            media_type="Akte",
            document_type="Protokoll",
            tags=("vorstand", "protokoll"),
            date=EdtfDate("1995"),
            physical_location="Tresor 1",
        ),
        Article(
            ulid=ULID("ART_GRPBESCH"),
            title="Beschluss der Fahrten-Ordnung",
            collection_id=ULID("VORSTAND"),
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
            ulid=ULID("ART_DRAFT"),
            title="Entwurf einer Chronik",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.DRAFT,
            ref_code="D 1",
            media_type="Akte",
            document_type="Chronik",
            tags=("entwurf",),
            date=EdtfDate("2010"),
        ),
        # --- Dangling collection_id -> fail-closed archivist-only row (no ancestors) ---
        Article(
            ulid=ULID("ART_ORPHAN"),
            title="Verwaistes Dokument Lieder",
            collection_id=ULID("GHOST"),
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="O 1",
            media_type="Akte",
            document_type="Unbekannt",
            tags=("verwaist",),
            date=EdtfDate("1969"),
        ),
    )
