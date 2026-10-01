"""Article identity primitives (ADR 0006).

A ULID is an Article's stable identity and its only key segment — `articles/<ulid>/`.
A title-derived slug would change when the title changes, so it never carries identity.
These are pure functions; minting a ULID at Article creation is a
caller concern (Part 2), so they live in `domain`, not the persistence layer.
"""

from datetime import UTC, datetime

from ulid import ULID

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Article, Audience, Lifecycle, MediaRef, Ulid


def new_ulid() -> Ulid:
    """Mint a fresh ULID (26-char Crockford base32, lexicographically sortable)."""
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
    """Create a NEW Article, minting its stable ULID at creation (ADR 0006: identity is a
    ULID minted here, never derived from a slug). The single place a ULID is minted — every
    other field mirrors Article's, and ``added_at`` is now. Existing Articles are reconstructed by
    the README codec (which carries the already-minted ULID), not created here."""
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
