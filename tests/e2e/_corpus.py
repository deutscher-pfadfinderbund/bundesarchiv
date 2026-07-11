"""The canonical E2E corpus — one small archive shaped to exercise every journey (Part #26).

Built once per session into a temp store and indexed. Returns ``CorpusHandles`` so a journey names
what it needs (the draft to edit, the published article to copy/delete, a second collection to move
into) instead of hard-coding ULIDs. Kept deliberately tiny: two collections, a handful of articles
covering search/filter, edit, copy, delete, publish-preview, and bulk paths.
"""

from dataclasses import dataclass
from pathlib import Path

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

# Fixed valid ULIDs for the articles a journey names (generated once; stable so screenshots + tests
# reference the same records across runs).
PUBLISHED_ULID = "01KX8N6P2PBDPMNJE58ZVQKVZ7"
SECOND_ULID = "01KX8N6P2PBDPMNJE58ZVQKVZ8"
DRAFT_ULID = "01KX8N6P2PBDPMNJE58ZVQKVZ9"


@dataclass(frozen=True, slots=True)
class CorpusHandles:
    """What the journeys reference in the built corpus."""

    fotos_id: str
    akten_id: str
    draft_ulid: str
    published_ulid: str
    second_ulid: str


def build_corpus(root: Path) -> CorpusHandles:
    """Build + index the canonical corpus at ``root``. Idempotent per fresh temp dir."""
    store = LocalFsObjectStore(root)
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    collections.save(Collection("ROOT", "Bundesarchiv", None), 0)
    collections.save(Collection("FOTOS", "Fotografien", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
    collections.save(Collection("AKTEN", "Aktenbestand", "ROOT", Audience(AudienceTier.MEMBERS)), 0)

    articles.save(
        Article(
            ulid=PUBLISHED_ULID,
            title="Sommerfahrt 1962",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="F 12",
            media_type="Fotografie",
            document_type="Porträt",
            tags=("fahrt", "sommer"),
            date=EdtfDate("1962"),
            creator="K. Meyer",
        ),
        0,
    )
    articles.save(
        Article(
            ulid=SECOND_ULID,
            title="Herbstlager 1963",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="F 13",
            media_type="Fotografie",
            tags=("lager",),
            date=EdtfDate("1963"),
        ),
        0,
    )
    articles.save(
        Article(
            ulid=DRAFT_ULID,
            title="Entwurf Lagerchronik",
            collection_id="FOTOS",
            lifecycle=Lifecycle.DRAFT,
            ref_code="F 9",
            media_type="Fotografie",
        ),
        0,
    )

    indexer.rebuild(store)
    return CorpusHandles(
        fotos_id="FOTOS",
        akten_id="AKTEN",
        draft_ulid=DRAFT_ULID,
        published_ulid=PUBLISHED_ULID,
        second_ulid=SECOND_ULID,
    )
