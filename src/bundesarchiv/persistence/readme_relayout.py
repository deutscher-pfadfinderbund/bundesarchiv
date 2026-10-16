"""The one-off re-encode of every current README into the layout the codecs write now (ADR 0019,
amended 2026-10-16)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from bundesarchiv.domain.models import Change, Collection, Ulid, Version
from bundesarchiv.persistence import collection_readme, readme
from bundesarchiv.persistence._front_matter import comments, split_title, text_of
from bundesarchiv.persistence._layout import ARTICLES, COLLECTIONS, Records
from bundesarchiv.persistence.errors import UnreadableReadme
from bundesarchiv.persistence.objectstore import ObjectStore

type Left = Literal["unreadable", "would not read the same", "no change record"]


@dataclass(frozen=True, slots=True)
class Codec[R]:
    """One kind of record: where its READMEs live, its codec, and the key the old layout kept its
    title under."""

    records: Records
    decode: Callable[[Ulid, str], tuple[R, Version, Change | None]]
    encode: Callable[[R, Version, Change], str]
    title_key: str


def _decode_collection(ulid: Ulid, text: str) -> tuple[Collection, Version, Change | None]:
    return collection_readme.decode_collection(text, ulid=ulid)


ARTICLE = Codec(ARTICLES, readme.decode, readme.encode, "title")
COLLECTION = Codec(COLLECTIONS, _decode_collection, collection_readme.encode_collection, "name")


@dataclass(frozen=True, slots=True)
class Report:
    """How many READMEs were `rewritten` or `already_new`, and the key of each one `left` as it is,
    with the reason."""

    rewritten: int
    already_new: int
    left: tuple[tuple[str, Left], ...]


def _held(ulid: Ulid, text: str, title_key: str) -> tuple[dict[str, Any], str]:
    """Everything README `text` holds, whether a decoder reads it or not: the front matter with the
    title under `title_key`, and the body after the title."""
    front_matter, title, body = split_title(ulid, text, title_key)
    return (front_matter if title is None else {**front_matter, title_key: title}), body


def relaid[R](ulid: Ulid, data: bytes, codec: Codec[R]) -> bytes | Left | None:
    """The current writer's bytes for README `data`, or None when `data` already is them. They must
    hold the same front matter, title and body, and `data` no comment but the marker; otherwise
    the reason the README is left as it is."""
    try:
        old = text_of(ulid, data)
        record, version, change = codec.decode(ulid, old)
        held = _held(ulid, old, codec.title_key)
        commented = bool(comments(ulid, old))
    except UnreadableReadme:
        return "unreadable"
    if change is None:
        return "no change record"
    try:
        new = codec.encode(record, version, change)
    except ValueError:  # a title the writer refuses
        return "would not read the same"
    if (new_bytes := new.encode()) == data:
        return None
    try:
        # The decoders read nothing beyond what `_held` returns, so the record reads the same too.
        same = _held(ulid, new, codec.title_key) == held
    except UnreadableReadme:
        same = False
    return new_bytes if same and not commented else "would not read the same"


def relayout(store: ObjectStore, *, dry_run: bool = False) -> Report:
    """Re-encode every current README; `history/` is never read. Takes no lock: a save running at
    the same time could be lost. A `dry_run` writes nothing and reports the same."""
    rewritten, already_new, left = 0, 0, list[tuple[str, Left]]()
    codecs: tuple[Codec[Any], ...] = (ARTICLE, COLLECTION)
    for codec in codecs:
        for ulid in codec.records.list_ulids(store):
            key = codec.records.readme_key(ulid)
            outcome = relaid(ulid, store.read(key), codec)
            if isinstance(outcome, bytes):
                if not dry_run:
                    store.write_atomic(key, outcome)
                rewritten += 1
            elif outcome is None:
                already_new += 1
            else:
                left.append((key, outcome))
    return Report(rewritten, already_new, tuple(left))
