"""Domain data shapes (CONTEXT.md terms). Value objects validate their own invariants."""

import enum
import unicodedata
from dataclasses import dataclass, fields
from datetime import datetime, timedelta

from bundesarchiv.domain.edtf import EdtfDate

type Ulid = str  # a Crockford-base32 ULID; the Article's stable identity
type Version = int  # optimistic-concurrency counter (0 = never saved; first save -> 1)


class Lifecycle(enum.Enum):
    """An Article's workflow state (CONTEXT.md)."""

    DRAFT = "draft"
    PUBLISHED = "published"


class AudienceTier(enum.Enum):
    """A rung on the visibility ladder Public ⊃ Members ⊃ named Group(s)."""

    PUBLIC = "public"
    MEMBERS = "members"
    GROUPS = "groups"


@dataclass(frozen=True, slots=True)
class Audience:
    """Who may see an Article (*Sichtbarkeit*). When `tier` is GROUPS, `groups`
    names the Keycloak group(s) (OR-combined) that narrow Members to a subset.

    Invariant: `groups` is non-empty *iff* `tier is GROUPS`. A GROUPS rung with no
    group named would narrow Members to nobody; naming a group on a PUBLIC/MEMBERS
    rung is a silent over-exposure (a tier-first reader ignores the group). Both are
    illegal states, forbidden here so they can never reach the access model.
    """

    tier: AudienceTier = AudienceTier.MEMBERS
    groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Dedupe (groups are OR-combined), first occurrence wins; frozen, hence object.__setattr__.
        groups = tuple(dict.fromkeys(self.groups))
        if any(not name.strip() for name in groups):
            raise ValueError(f"audience: group names must be non-blank (got {self.groups!r})")
        object.__setattr__(self, "groups", groups)
        if bool(groups) != (self.tier is AudienceTier.GROUPS):
            raise ValueError(
                f"audience: groups must be non-empty iff tier is GROUPS "
                f"(got tier={self.tier.value}, groups={groups!r})"
            )


@dataclass(frozen=True, slots=True)
class Change:
    """Who wrote one version, and when (ADR 0019): version metadata, never Article or Collection
    content. ``by`` is a Keycloak username or a fixed label: one line of text, never blank.
    ``at`` is UTC."""

    at: datetime
    by: str

    def __post_init__(self) -> None:
        if not self.by.strip() or any(unicodedata.category(ch) == "Cc" for ch in self.by):
            raise ValueError(f"change: by must be a non-blank name, got {self.by!r}")
        if self.at.utcoffset() != timedelta(0):
            raise ValueError(f"change: at must be UTC, got {self.at!r}")


@dataclass(frozen=True, slots=True)
class MediaRef:
    """A reference to one write-once media file. `filename` is the upload name; `stored_name`
    is set only when the stored name differs (ADR 0019); `content_hash` is the fixity value.
    `caption` is README front-matter input (ADR 0015). Order is meaning: the first entry is the
    cover."""

    filename: str
    content_hash: str  # sha256 hex of the bytes
    media_type: str | None = None  # MIME-ish
    byte_size: int | None = None
    caption: str | None = None
    # An image's description for people who cannot see it; the caption stands in.
    alt: str | None = None
    stored_name: str | None = None


@dataclass(frozen=True, slots=True)
class Collection:
    """The single owning, nestable division an Article belongs to (*Bestand*).
    Collections form a single-parent tree; the root has `parent_id is None`."""

    ulid: Ulid
    name: str
    parent_id: Ulid | None = None
    audience: Audience | None = None  # None = inherit from parent / root default (ADR 0001)


@dataclass(frozen=True, slots=True)
class Article:
    """A single catalog record describing one archived thing (*Artikel*).

    `body` is the Markdown description; the remaining fields are metadata that
    round-trips through the README.md front-matter.
    """

    ulid: Ulid
    title: str
    collection_id: Ulid
    body: str = ""
    lifecycle: Lifecycle = Lifecycle.DRAFT
    audience: Audience | None = None  # None = inherit from the Collection chain (ADR 0001)
    ref_code: str | None = None  # Signatur — human-facing, not identity
    media_type: str | None = None  # Medienart
    document_type: str | None = None  # Dokumenttyp
    tags: tuple[str, ...] = ()
    physical_location: str | None = None  # Standort
    media: tuple[MediaRef, ...] = ()
    # Member-visible provenance fields.
    date: EdtfDate | None = None  # EDTF Level 0/1 archival date
    creator: str | None = None  # Urheber
    subject_place: str | None = None  # Ortsangabe
    # Archivist-only escape hatch for metadata the schema doesn't cover (ADR 0009).
    custom: tuple[tuple[str, str], ...] = ()
    # Hinzugefügt am; None = unknown (ADR 0019).
    added_at: datetime | None = None
    # The Papierkorb mark: who deleted the Article and when; None = not deleted (ADR 0022).
    deleted: Change | None = None
    # A Vorlage: a Draft archivists copy to start a new Article; never published (CONTEXT.md).
    template: bool = False

    def __post_init__(self) -> None:
        if self.template and self.lifecycle is not Lifecycle.DRAFT:
            raise ValueError("a template is always a draft")
        if self.added_at is not None and (
            self.added_at.utcoffset() != timedelta(0) or self.added_at.microsecond
        ):
            raise ValueError(f"added_at must be UTC in whole seconds, got {self.added_at!r}")
        # Canonical: sorted by key, last duplicate wins. A key may not shadow a predefined field,
        # or it would pose as one.
        reserved = {f.name for f in fields(self)} - {"custom"}
        normalized: dict[str, str] = {}
        for key, value in self.custom:
            name = str(key)
            if name in reserved:
                raise ValueError(f"custom: key {name!r} collides with a predefined Article field")
            normalized[name] = str(value)
        object.__setattr__(self, "custom", tuple(sorted(normalized.items())))
