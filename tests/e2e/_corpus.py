"""The canonical E2E corpus every journey and gallery state names through ``CorpusHandles``. Layout
stress goes on the Titel, the one unbounded field (Signaturen are bounded: ``CEILING_REF_CODE``).
"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from tests._pdfs import text_pdf

from bundesarchiv.app import media_text, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    ULID,
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

ID_FOTOS = ULID("FOTOS")


def _png(color: tuple[int, int, int], size: tuple[int, int] = (8, 8)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _page() -> Image.Image:
    """An A4 page with bars for lines of text, so its thumbnail reads as a document."""
    page = Image.new("L", (595, 842), 250)
    draw = ImageDraw.Draw(page)
    for top in range(96, 760, 26):
        draw.rectangle((72, top, 72 + 260 + (top * 37) % 200, top + 9), fill=70)
    return page


def _pdf() -> bytes:
    """A one-page PDF of ``_page``, without a text layer."""
    buf = BytesIO()
    _page().save(buf, format="PDF")
    return buf.getvalue()


def _report_pdf() -> bytes:
    """``_page`` as page 1, then a page whose text layer holds ``PAGE_ONLY_WORD``."""
    buf = BytesIO()
    _page().convert("RGB").save(buf, format="JPEG")
    return text_pdf([PAGE_ONLY_WORD], first_page_image=buf.getvalue())


# Fixed valid ULIDs for the articles a journey names (generated once; stable so screenshots + tests
# reference the same records across runs).
PUBLISHED_ULID = ULID("01KX8N6P2PBDPMNJE58ZVQKVZ7")
SECOND_ULID = ULID("01KX8N6P2PBDPMNJE58ZVQKVZ8")
DRAFT_ULID = ULID("01KX8N6P2PBDPMNJE58ZVQKVZ9")
CEILING_ULID = ULID("01KX8N6P2PBDPMNJE58ZVQKVZA")
MARKED_ULID = ULID("01KX8N6P2PBDPMNJE58ZVQKVZB")  # in the Papierkorb
MANY_ULID = ULID("01KX8N6P2PBDPMNJE58ZVQKVZC")
TEMPLATE_ULID = ULID("01KX8N6P2PBDPMNJE58ZVQKVZD")
SOUND_ULID = ULID("01KX8N6P2PBDPMNJE58ZVQKVZE")  # a film and a recording: tiles with no thumbnail

#: The Signatur at the domain ceiling (owner, 2026-08-07): 8 characters, no spaces — Collection ·
#: subdivision · volume, the longest code the archive is expected to carry.
CEILING_REF_CODE = "F12/3-b2"
KARTEN_ULID = ULID("01KX939S67DNGH0AB53HNXGB9B")

#: The photos of MANY_ULID: (filename, caption, pixel size) — landscape, portrait, square, wide.
MANY_PHOTOS = (
    ("zelte.png", "Zeltplatz am Morgen", (1600, 1067)),
    ("kochen.png", "Kochen am Feuer", (1067, 1600)),
    ("gruppe.png", "Gruppenbild vor der Hütte", (1400, 1400)),
    (
        "wanderung.png",
        "Wanderung durch das Moor, am dritten Tag, bei strömendem Regen",
        (1800, 900),
    ),
    ("fahne.png", "", (900, 1200)),
    ("see.png", "Der See", (1600, 1067)),
    ("abend.png", "Abendrunde", (1500, 1000)),
)
_PHOTO_COLORS = ((90, 120, 70), (160, 110, 60), (70, 110, 150), (120, 90, 130))

#: The one file of the ceiling record: a PDF, so its article page leads with its first page.
MINUTES_FILENAME = "Protokoll_1958.pdf"

#: A word only on page 2 of the published record's PDF, in no record field.
PAGE_ONLY_WORD = "Wimpelweihe"


@dataclass(frozen=True, slots=True)
class CorpusHandles:
    """What the journeys reference in the built corpus."""

    draft_ulid: str
    published_ulid: str
    second_ulid: str
    marked_ulid: str
    ceiling_ulid: str
    many_ulid: str
    template_ulid: str
    sound_ulid: str


def build_corpus(root: Path, thumbnail_root: Path | None = None) -> CorpusHandles:
    """With ``thumbnail_root``, pre-generate the thumbnails the absent worker would, so media <img>s
    render."""
    store = LocalFsObjectStore(root)
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    collections.save(Collection(ULID("ROOT"), "Bundesarchiv", None), 0, changed_by="tester")
    collections.save(
        Collection(ID_FOTOS, "Fotografien", ULID("ROOT"), Audience(AudienceTier.PUBLIC)),
        0,
        changed_by="tester",
    )
    collections.save(
        Collection(ULID("AKTEN"), "Aktenbestand", ULID("ROOT"), Audience(AudienceTier.MEMBERS)),
        0,
        changed_by="tester",
    )
    collections.save(
        Collection(KARTEN_ULID, "Karten", ID_FOTOS, Audience(AudienceTier.PUBLIC)),
        0,
        changed_by="tester",
    )

    # add_media first: the repository refuses an Article referencing unstored blobs.
    cover = articles.add_media(
        PUBLISHED_ULID,
        "cover.png",
        BytesIO(
            _png((200, 60, 40), size=(1600, 1067))
        ),  # a photo's pixels: the lead fills the column
        media_type="image/png",
    )
    plate = articles.add_media(
        PUBLISHED_ULID, "plate.png", BytesIO(_png((40, 120, 200))), media_type="image/png"
    )
    # a PDF beside the photos: its tiles show its first page
    report = articles.add_media(
        PUBLISHED_ULID,
        "Fahrtenbericht_1962.pdf",
        BytesIO(_report_pdf()),
        media_type="application/pdf",
    )
    minutes = articles.add_media(
        CEILING_ULID, MINUTES_FILENAME, BytesIO(_pdf()), media_type="application/pdf"
    )
    sommerfahrt = Article(
        ulid=PUBLISHED_ULID,
        title="Sommerfahrt 1962",
        collection_id=ID_FOTOS,
        lifecycle=Lifecycle.PUBLISHED,
        # A multi-paragraph body, so the detail states exercise the prose+card split.
        body=(
            "Die Sommerfahrt führte die Gruppe im Juli 1962 in den Harz.\n\n"
            "Aufgenommen wurden Porträts am Lagerfeuer sowie ein Gruppenbild vor der Hütte.\n\n"
            "Der Bestand dokumentiert die Ferienlager der frühen 1960er Jahre."
        ),
        ref_code="F12",
        media_type="Foto(s)",
        document_type="Zeitschrift",
        tags=("fahrt", "sommer"),
        date=EdtfDate("1962-07"),
        creator="K. Meyer",
        subject_place="Harz",
        media=(
            MediaRef(cover.filename, cover.content_hash, caption="Am Lagerfeuer"),
            MediaRef(plate.filename, plate.content_hash, caption="Gruppenbild"),
            report,
        ),
    )
    # two versions by two archivists: the article page's version list
    articles.save(
        sommerfahrt, articles.save(sommerfahrt, 0, changed_by="anna.k"), changed_by="tester"
    )
    articles.save(
        Article(
            ulid=SECOND_ULID,
            title="Herbstlager 1963",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="F13",
            media_type="Foto(s)",
            tags=("lager",),
            date=EdtfDate("1963"),
        ),
        0,
        changed_by="tester",
    )
    # draft-ness is lifecycle state, never words in the title
    articles.save(
        Article(
            ulid=DRAFT_ULID,
            title="Lagerchronik",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.DRAFT,
            ref_code="F9",
            media_type="Foto(s)",
            # the archivist-only lines, so the article page's draft state shows them under the head
            physical_location="Bund \u203a Alben",
            custom=(("Legacy-ID", "1293"),),
        ),
        0,
        changed_by="tester",
    )
    # not a Foto(s): the filter journeys narrow on that count
    articles.save(
        Article(
            ulid=CEILING_ULID,
            title="Gauversammlung Rhön",
            collection_id=ULID("AKTEN"),
            lifecycle=Lifecycle.PUBLISHED,
            ref_code=CEILING_REF_CODE,
            media_type="Schrifttum",
            document_type="Protokoll",
            date=EdtfDate("1958-05"),
            media=(minutes,),
        ),
        0,
        changed_by="tester",
    )

    many = tuple(
        articles.add_media(
            MANY_ULID,
            name,
            BytesIO(_png(_PHOTO_COLORS[n % len(_PHOTO_COLORS)], size=size)),
            media_type="image/png",
        )
        for n, (name, _, size) in enumerate(MANY_PHOTOS)
    )
    articles.save(
        Article(
            ulid=MANY_ULID,
            title="Pfingstlager 1964",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="F14",
            media_type="Foto(s)",
            date=EdtfDate("1964-05"),
            media=tuple(
                MediaRef(ref.filename, ref.content_hash, caption=caption)
                for ref, (_, caption, _) in zip(many, MANY_PHOTOS, strict=True)
            ),
        ),
        0,
        changed_by="tester",
    )

    # The Vorlage: the shared structure of a series' parts lives in its description.
    articles.save(
        Article(
            ulid=TEMPLATE_ULID,
            title="Fahrtenbericht",
            collection_id=ULID("AKTEN"),
            lifecycle=Lifecycle.DRAFT,
            template=True,
            media_type="Schrifttum",
            body="Route: …\n\nTeilnehmende: …\n\nWetter: …",
        ),
        0,
        changed_by="tester",
    )

    film = articles.add_media(
        SOUND_ULID, "Liederabend.mp4", BytesIO(b"mp4 film"), media_type="video/mp4"
    )
    recording = articles.add_media(
        SOUND_ULID, "Liederabend.mp3", BytesIO(b"ID3 recording"), media_type="audio/mpeg"
    )
    articles.save(
        Article(
            ulid=SOUND_ULID,
            title="Liederabend 1960",
            collection_id=ULID("AKTEN"),
            lifecycle=Lifecycle.PUBLISHED,
            ref_code="A7",
            date=EdtfDate("1960"),
            media=(film, recording),
        ),
        0,
        changed_by="tester",
    )

    winterlager = Article(
        ulid=MARKED_ULID,
        title="Winterlager 1961",
        collection_id=ID_FOTOS,
        lifecycle=Lifecycle.PUBLISHED,
        ref_code="F11",
        media_type="Foto(s)",
    )
    articles.mark_deleted(
        winterlager, articles.save(winterlager, 0, changed_by="tester"), changed_by="tester"
    )

    indexer.rebuild(store)
    filled = media_text.fill(Archive.of(store), PUBLISHED_ULID)
    assert len(filled) == 1  # fill never raises; a miss is silent
    if thumbnail_root is not None:
        for ulid, ref in (
            (PUBLISHED_ULID, cover),
            (PUBLISHED_ULID, plate),
            (PUBLISHED_ULID, report),
            (CEILING_ULID, minutes),
            *((MANY_ULID, ref) for ref in many),
        ):
            thumbnails.generate_thumbnail(store, ULID(ulid), ref.content_hash, thumbnail_root)
    return CorpusHandles(
        draft_ulid=DRAFT_ULID,
        published_ulid=PUBLISHED_ULID,
        second_ulid=SECOND_ULID,
        marked_ulid=MARKED_ULID,
        ceiling_ulid=CEILING_ULID,
        many_ulid=MANY_ULID,
        template_ulid=TEMPLATE_ULID,
        sound_ulid=SOUND_ULID,
    )
