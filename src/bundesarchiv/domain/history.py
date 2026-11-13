"""An Article's versions as a list: who wrote each, when, and what it changed."""

import enum
from dataclasses import dataclass, fields

from bundesarchiv.domain.models import Article, Change, Lifecycle, Version


class Act(enum.Enum):
    """A change whose direction the changed field's name does not tell."""

    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    TRASHED = "trashed"
    RESTORED = "restored"


#: A file as the list names it: its ``content_hash`` and its ``filename``.
type NamedFile = tuple[str, str]


@dataclass(frozen=True, slots=True)
class Difference:
    """What differs between two Articles: empty exactly when they are equal up to the order of
    their tags.

    ``fields`` names each differing field of ``Article`` but ``custom``, whose differing keys
    (added, removed or changed) are ``custom``. A file is added or removed when only the later or
    only the earlier Article names its ``content_hash``: a file attached again under another name,
    a caption or a new order adds and removes none and shows only as ``media`` in ``fields``."""

    fields: frozenset[str] = frozenset()
    custom: frozenset[str] = frozenset()
    added: tuple[NamedFile, ...] = ()
    removed: tuple[NamedFile, ...] = ()
    acts: frozenset[Act] = frozenset()


def difference(before: Article, after: Article) -> Difference:
    earlier, later = dict(before.custom), dict(after.custom)
    earlier_files = {ref.content_hash: ref.filename for ref in before.media}
    later_files = {ref.content_hash: ref.filename for ref in after.media}
    lifecycles = (before.lifecycle, after.lifecycle)
    acts = {
        Act.PUBLISHED: lifecycles == (Lifecycle.DRAFT, Lifecycle.PUBLISHED),
        Act.UNPUBLISHED: lifecycles == (Lifecycle.PUBLISHED, Lifecycle.DRAFT),
        Act.TRASHED: before.deleted is None and after.deleted is not None,
        Act.RESTORED: before.deleted is not None and after.deleted is None,
    }
    return Difference(
        fields=frozenset(
            field.name
            for field in fields(Article)
            if field.name != "custom"
            and _compared(before, field.name) != _compared(after, field.name)
        ),
        custom=frozenset(
            key for key in earlier.keys() | later.keys() if earlier.get(key) != later.get(key)
        ),
        added=tuple(item for item in later_files.items() if item[0] not in earlier_files),
        removed=tuple(item for item in earlier_files.items() if item[0] not in later_files),
        acts=frozenset(act for act, happened in acts.items() if happened),
    )


def _compared(article: Article, name: str) -> object:
    value = getattr(article, name)
    return frozenset(value) if name == "tags" else value


@dataclass(frozen=True, slots=True)
class VersionEntry:
    """One version of an Article in its list. ``change`` is who wrote it and when, None without a
    readable change record. ``difference`` is what it changed against the version before it: None
    when that is unknown, because that version is missing or either does not decode; an empty
    ``Difference`` when nothing changed, as for version 1, which has none before it."""

    version: Version
    change: Change | None
    difference: Difference | None


def version_entry(
    version: Version, change: Change | None, article: Article | None, before: Article | None
) -> VersionEntry:
    """The entry of ``version``, decoded as ``article`` and with ``before`` the version below it
    (None: missing or not decoded)."""
    if version == 1:
        return VersionEntry(version, change, Difference())
    if article is None or before is None:
        return VersionEntry(version, change, None)
    return VersionEntry(version, change, difference(before, article))
