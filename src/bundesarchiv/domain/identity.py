from datetime import UTC, datetime
from typing import TypeGuard

import ulid as _ulid

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import ULID, Article, Audience, Lifecycle, MediaRef


def new_ulid() -> ULID:
    return ULID(str(_ulid.ULID()))


def create_article(
    *,
    title: str,
    collection_id: ULID,
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
    """Never for rebuilding a loaded Article: that keeps its ULID (ADR 0006)."""
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


def is_valid_ulid(value: object) -> TypeGuard[ULID]:
    """The parse every outside value takes to become a ULID: True only for the canonical
    uppercase spelling. Total: False, never an exception, for any other value or type."""
    if not isinstance(value, str):
        return False
    try:
        _ulid.ULID.from_str(value)
    except ValueError:
        return False
    return True
