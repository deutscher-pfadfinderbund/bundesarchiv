"""Domain data shapes for the archive — the records the persistence layer (de)serializes.

Value objects self-validate their construction invariants here (e.g. `Audience` enforces
the groups-iff-GROUPS rule in `__post_init__`); the *resolution* logic over these shapes —
effective-audience and Collection-tree resolution — lives in `audience.py` / `collections.py`,
and field floors land with the `can_view` layer (Part 2, later steps). Terms follow CONTEXT.md
(English code, German UI labels live in the glossary).
"""

import enum
from dataclasses import dataclass

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
    names the Keycloak group(s) (OR-combined) that narrow Members to a subset.

    Invariant: `groups` is non-empty *iff* `tier is GROUPS`. A GROUPS rung with no
    group named would narrow Members to nobody; naming a group on a PUBLIC/MEMBERS
    rung is a silent over-exposure (a tier-first reader ignores the group). Both are
    illegal states, forbidden here so they can never reach the access model.
    """

    tier: AudienceTier = AudienceTier.MEMBERS
    groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Normalize before validating: a frozen, hashable value object must store a tuple
        # even if built from a list via untyped input (object.__setattr__ — the class is frozen).
        object.__setattr__(self, "groups", tuple(self.groups))
        if bool(self.groups) != (self.tier is AudienceTier.GROUPS):
            raise ValueError(
                f"audience: groups must be non-empty iff tier is GROUPS "
                f"(got tier={self.tier.value}, groups={self.groups!r})"
            )


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
    physical_description: str | None = None  # Objektbeschreibung
    media: tuple[MediaRef, ...] = ()
