"""Media intake (``CONTEXT.md``): the one write rule for adding files to an Article's media,
whatever the transport. ``refusal`` admits a file before its bytes arrive; ``attach`` stores ready
bytes and lists each file once; ``finish_staged`` attaches a complete chunked upload (ADR 0026).
A transport maps the answers to its protocol."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from functools import reduce
from typing import BinaryIO

from bundesarchiv.app import articles
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import Missing, Updated, UpdateOutcome
from bundesarchiv.app.upload_staging import Finished, Key, Staging
from bundesarchiv.domain.models import ULID, MediaRef
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.repository import Stored, cleaned_name

#: How many times a media save re-loads after a concurrent version bump before it answers
#: ``Conflicted`` (rare: single-app-process, a handful of writers).
SAVE_RETRIES = 2

#: The shape of a multipart part's Content-Type: a media type is served back as that header.
_MEDIA_TYPE = re.compile(r"[\w!#$&^.+-]+/[\w!#$&^.+-]+", re.ASCII)


class Refusal(Enum):
    NAMELESS = "nameless"
    TOO_LARGE = "too large"


@dataclass(frozen=True, slots=True)
class Incoming:
    """A file as its transport hands it over: ``stream`` seekable, read from its current
    position; ``filename`` and ``media_type`` as the client gave them."""

    filename: str
    stream: BinaryIO
    media_type: str | None


@dataclass(frozen=True, slots=True)
class Repeated:
    """The finish of an upload that has landed already: the Article as stored now."""

    stored: Stored


def refusal(filename: str, size: int, *, ceiling: int) -> Refusal | None:
    """Why a file of ``size`` bytes named ``filename`` may not come in over a transport that takes
    ``ceiling`` bytes at most; None when it may. A name that cleans to nothing is refused, never
    renamed (ADR 0019 "Media names")."""
    if cleaned_name(filename) is None:
        return Refusal.NAMELESS
    return Refusal.TOO_LARGE if size > ceiling else None


def attach(
    archive: Archive, ulid: ULID, incoming: Iterable[Incoming], *, changed_by: str
) -> UpdateOutcome:
    """Store the admitted files and list each after the Article's media, in order, unless the
    Article lists its bytes already."""
    refs = [
        archive.articles.add_media(ulid, f.filename, f.stream, _kept(f.media_type))
        for f in incoming
    ]
    return articles.update_article(
        archive,
        ulid,
        lambda article: replace(article, media=_listed(article.media, refs)),
        changed_by=changed_by,
        retries=SAVE_RETRIES,
    )


def finish_staged(archive: Archive, staging: Staging, key: Key) -> UpdateOutcome | Repeated | None:
    """``attach`` the complete upload ``key`` names, by its owner, and free its bytes once that
    saved, all under the upload's lock; an upload that did not land stays for the next finish.
    None when no complete upload of ``key`` is staged."""
    ulid = ULID(key.article)
    with staging.claim(key) as claimed:
        match claimed:
            case None:
                return None
            case Finished.FINISHED:
                # Loaded under the lock: a repeat that waited on the first finish sees its save.
                try:
                    stored = archive.articles.load(ulid)
                except ArchiveError:
                    return Missing()
                return Missing() if stored.article.deleted is not None else Repeated(stored)
            case (upload, stream, finish):
                outcome = attach(
                    archive,
                    ulid,
                    [Incoming(upload.filename, stream, upload.media_type)],
                    changed_by=key.owner,
                )
                if isinstance(outcome, Updated):
                    finish()
                return outcome


def _kept(media_type: str | None) -> str | None:
    return media_type if media_type is not None and _MEDIA_TYPE.fullmatch(media_type) else None


def _listed(media: tuple[MediaRef, ...], refs: list[MediaRef]) -> tuple[MediaRef, ...]:
    return reduce(
        lambda listed, ref: (
            listed if any(r.content_hash == ref.content_hash for r in listed) else (*listed, ref)
        ),
        refs,
        media,
    )
