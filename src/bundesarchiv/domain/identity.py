"""Article identity (ADR 0006): the ULID and the factory that mints it."""

from datetime import UTC, datetime

from ulid import ULID

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Article, Audience, Lifecycle, MediaRef, Ulid


def new_ulid() -> Ulid:
    return str(ULID())


def create_article(
    *,
    title: str,
    collection_id: Ulid,
    body: str = "",
    lifecycle: Lifecycle = Lifecycle.DRAFT,
    audience: Audience | None = None,
    ref_code: str | None = None,
    media_type: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    physical_location: str | None = None,
    media: tuple[MediaRef, ...] = (),
    date: EdtfDate | None = None,
    creator: str | None = None,
    subject_place: str | None = None,
    custom: tuple[tuple[str, str], ...] = (),
) -> Article:
    """A new Article with a freshly minted ULID (ADR 0006) and ``added_at`` now. Loaded
    Articles keep their ULID."""
    return Article(
        ulid=new_ulid(),
        title=title,
        collection_id=collection_id,
        body=body,
        lifecycle=lifecycle,
        audience=audience,
        ref_code=ref_code,
        media_type=media_type,
        document_type=document_type,
        tags=tags,
        physical_location=physical_location,
        media=media,
        date=date,
        creator=creator,
        subject_place=subject_place,
        custom=custom,
        added_at=datetime.now(UTC).replace(microsecond=0),
    )


def is_valid_ulid(value: str) -> bool:
    """True if `value` is a well-formed ULID. Total: returns False (never raises) for
    a non-str too, so an untyped caller (e.g. a README field parsed to None) is safe."""
    try:
        ULID.from_str(value)
    except ValueError, TypeError:
        return False
    return True
