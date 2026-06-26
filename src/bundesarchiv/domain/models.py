"""Domain data shapes for the archive (Part 1: shapes only — no behaviour).

These are the records the persistence layer (de)serializes. Audience *logic*
(effective-audience, field floors) and Collection-tree resolution arrive in Part 2;
here Audience and Collection are plain data. Terms follow CONTEXT.md (English code,
German UI labels live in the glossary).
"""

import enum
from dataclasses import dataclass, field

type Ulid = str  # a Crockford-base32 ULID; the Article's stable identity
type Version = int  # optimistic-concurrency counter (0 = never saved; first save -> 1)


class Lifecycle(enum.Enum):
    """An Article's workflow state (CONTEXT.md). Anything not PUBLISHED is
    Archivist-only regardless of Audience."""

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
    names the Keycloak group(s) (OR-combined) that narrow Members to a subset."""

    tier: AudienceTier = AudienceTier.MEMBERS
    groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MediaRef:
    """A content-addressed reference to one stored media blob. The bytes live at a
    media key derived from `content_hash`; media is write-once."""

    filename: str
    content_hash: str  # sha256 hex of the bytes
    media_type: str | None = None  # MIME-ish, optional
    byte_size: int | None = None


@dataclass(frozen=True, slots=True)
class Collection:
    """The single owning, nestable division an Article belongs to (*Sammlung*).
    Collections form a single-parent tree; the root has `parent_id is None`."""

    ulid: Ulid
    name: str
    parent_id: Ulid | None = None


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
    audience: Audience = field(default_factory=Audience)
    ref_code: str | None = None  # Signatur — human-facing, not identity
    media_type: str | None = None  # Medienart
    document_type: str | None = None  # Dokumenttyp
    tags: tuple[str, ...] = ()
    physical_location: str | None = None  # Standort
    physical_description: str | None = None  # Objektbeschreibung
    media: tuple[MediaRef, ...] = ()
