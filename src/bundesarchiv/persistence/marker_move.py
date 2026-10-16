"""The one-off move of the managed-by marker inside the front matter of the current READMEs
(ADR 0019, amended 2026-10-16)."""

from dataclasses import dataclass

from bundesarchiv.persistence._front_matter import HEAD
from bundesarchiv.persistence._layout import ARTICLES, COLLECTIONS
from bundesarchiv.persistence.objectstore import ObjectStore

_OLD_HEAD = "<!-- Managed by bundesarchiv — do not edit by hand. -->\n---\n".encode()


@dataclass(frozen=True, slots=True)
class Report:
    """How many READMEs were `rewritten` or `already_new`, and the keys of those `skipped`: in
    neither shape, left as they are."""

    rewritten: int
    already_new: int
    skipped: tuple[str, ...]


def marker_moved(data: bytes) -> bytes | None:
    """`data` with the marker moved and every other byte as it was; None unless `data` opens with
    the old marker."""
    if not data.startswith(_OLD_HEAD):
        return None
    return HEAD.encode() + data.removeprefix(_OLD_HEAD)


def move_markers(store: ObjectStore) -> Report:
    """Rewrite every current README in the old shape. Takes no lock: a save running at the same
    time could be lost."""
    rewritten, already_new, skipped = 0, 0, []
    for records in (ARTICLES, COLLECTIONS):
        for ulid in records.list_ulids(store):
            key = records.readme_key(ulid)
            data = store.read(key)
            if (moved := marker_moved(data)) is not None:
                store.write_atomic(key, moved)
                rewritten += 1
            elif data.startswith(HEAD.encode()):
                already_new += 1
            else:
                skipped.append(key)
    return Report(rewritten, already_new, tuple(skipped))
