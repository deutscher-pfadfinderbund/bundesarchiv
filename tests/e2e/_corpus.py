"""The canonical E2E corpus — one small archive shaped to exercise every journey (Part #26).

Built once per session into a temp store and indexed. Returns ``CorpusHandles`` so a journey names
what it needs (the draft to edit, the published article to copy/delete, a second collection to move
into) instead of hard-coding ULIDs. Kept deliberately tiny: two collections, a handful of articles
covering search/filter, edit, copy, delete, publish-preview, and bulk paths.
"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from bundesarchiv.app import thumbnails
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
    MediaRef,
)
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository


def _png(color: tuple[int, int, int]) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


# Fixed valid ULIDs for the articles a journey names (generated once; stable so screenshots + tests
# reference the same records across runs).
PUBLISHED_ULID = "01KX8N6P2PBDPMNJE58ZVQKVZ7"
SECOND_ULID = "01KX8N6P2PBDPMNJE58ZVQKVZ8"
DRAFT_ULID = "01KX8N6P2PBDPMNJE58ZVQKVZ9"
# A ULID-keyed collection (unlike the literal "ROOT"/"FOTOS" ids) for the 4.8 rename route + gallery
# state: /bestand/<ulid>/bearbeiten validates a real ULID (real collections created via the app get
# one), so the rename state needs a genuine ULID, not a literal.
RENAMABLE_ULID = "01KX939S67DNGH0AB53HNXGB9B"


@dataclass(frozen=True, slots=True)
class CorpusHandles:
    """What the journeys reference in the built corpus."""

    fotos_id: str
    akten_id: str
    draft_ulid: str
    published_ulid: str
    second_ulid: str
    published_cover_hash: str
    renamable_ulid: str


def build_corpus(root: Path, thumbnail_root: Path | None = None) -> CorpusHandles:
    """Build + index the canonical corpus at ``root``. Idempotent per fresh temp dir.

    When ``thumbnail_root`` is given, the media blobs' WebP thumbnails are pre-generated into it —
    the worker-side generation the live e2e run has no worker for — so the detail cover + filmstrip
    <img>s (which point at the /media/.../thumb route) actually render instead of 404ing."""
    store = LocalFsObjectStore(root)
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    collections.save(Collection("ROOT", "Bundesarchiv", None), 0)
    collections.save(Collection("FOTOS", "Fotografien", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
    collections.save(Collection("AKTEN", "Aktenbestand", "ROOT", Audience(AudienceTier.MEMBERS)), 0)
    # A ULID-keyed Bestand under FOTOS so the 4.8 rename route/gallery state has a valid-ULID target.
    collections.save(
        Collection(RENAMABLE_ULID, "Karten", "FOTOS", Audience(AudienceTier.PUBLIC)), 0
    )

    # Two media on the published article so the 4.6 detail page has a cover Platte + a filmstrip
    # (add_media stores the blobs first; the repository refuses an Article referencing unstored ones).
    cover = articles.add_media(
        PUBLISHED_ULID, "cover.png", _png((200, 60, 40)), media_type="image/png"
    )
    plate = articles.add_media(
        PUBLISHED_ULID, "plate.png", _png((40, 120, 200)), media_type="image/png"
    )
    articles.save(
        Article(
            ulid=PUBLISHED_ULID,
            title="Sommerfahrt 1962",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            # A multi-paragraph body so the detail gallery states exercise the prose+card split (a
            # body-less article would hide the layout bug the design gate found — process fix, §5).
            body=(
                "Die Sommerfahrt führte die Gruppe im Juli 1962 in den Harz.\n\n"
                "Aufgenommen wurden Porträts am Lagerfeuer sowie ein Gruppenbild vor der Hütte.\n\n"
                "Der Bestand dokumentiert die Ferienlager der frühen 1960er Jahre."
            ),
            ref_code="F 12",
            media_type="Fotografie",
            document_type="Porträt",
            tags=("fahrt", "sommer"),
            date=EdtfDate("1962-07"),
            creator="K. Meyer",
            subject_place="Harz",
            media=(
                MediaRef(cover.filename, cover.content_hash, caption="Am Lagerfeuer"),
                MediaRef(plate.filename, plate.content_hash, caption="Gruppenbild"),
            ),
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
    if thumbnail_root is not None:
        # Pre-generate the thumbnails the worker would (the e2e run has no worker), so the detail
        # cover + filmstrip images render instead of the /media/.../thumb route 404ing.
        for content_hash in (cover.content_hash, plate.content_hash):
            thumbnails.generate_thumbnail(store, content_hash, thumbnail_root)
    return CorpusHandles(
        fotos_id="FOTOS",
        akten_id="AKTEN",
        draft_ulid=DRAFT_ULID,
        published_ulid=PUBLISHED_ULID,
        second_ulid=SECOND_ULID,
        published_cover_hash=cover.content_hash,
        renamable_ulid=RENAMABLE_ULID,
    )
