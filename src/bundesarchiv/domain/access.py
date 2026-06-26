"""Viewer-facing access layer — composes the effective-Audience resolver with a Viewer.

This is the only place a Viewer meets an Article's resolved Audience. It imports
`effective_audience` (the single source, ADR 0001) and never re-derives a rung itself,
so every visibility decision routes through one resolver. Pure: no IO, no Keycloak.

The `match` statements close over their unions with `assert_never`: adding a member to
`EffectiveAudience` or `Viewer`, or a rung to `AudienceTier`, becomes a type error rather
than a silent fail-open — the leak the single-source resolver exists to prevent.
"""

from dataclasses import dataclass, fields, replace
from typing import assert_never

from bundesarchiv.domain.audience import ArchivistOnly, effective_audience
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

# Fields only an Archivist may see, floored from any non-Archivist projection regardless of
# whether the Viewer can otherwise view the Article. Add provenance/notes fields here as the
# model grows — projection and the visibility preview both read this one set.
ARCHIVIST_ONLY_FIELDS: frozenset[str] = frozenset({"physical_location", "physical_description"})

# The fields a non-Archivist viewer who can view the Article sees — every field but the floored.
_MEMBER_VISIBLE_FIELDS: frozenset[str] = (
    frozenset(f.name for f in fields(Article)) - ARCHIVIST_ONLY_FIELDS
)


def can_view(viewer: Viewer, article: Article, chain: tuple[Collection, ...]) -> bool:
    """Fail-closed yes/no: may `viewer` see `article` given its resolved Collection `chain`?

    Any `DomainError` from resolution (e.g. a misresolved chain) denies *everyone*, including
    an Archivist — an unresolvable chain yields no Audience to authorize against.
    """
    try:
        effective = effective_audience(article, chain)
    except DomainError:
        return False
    match effective:
        case ArchivistOnly():
            return isinstance(viewer, Archivist)  # the Lifecycle gate: Archivists only
        case Audience() as rung:
            return _viewer_clears_rung(viewer, rung)
        case _ as unreachable:
            assert_never(unreachable)


def _viewer_clears_rung(viewer: Viewer, rung: Audience) -> bool:
    """Does `viewer` clear a (published) Article's effective rung on the ladder?"""
    match viewer:
        case Archivist():
            return True  # an Archivist sees everything
        case Public():
            return rung.tier is AudienceTier.PUBLIC
        case Member(groups=held):
            match rung.tier:
                case AudienceTier.PUBLIC | AudienceTier.MEMBERS:
                    return True  # any Member clears Public/Members
                case AudienceTier.GROUPS:
                    return _member_satisfies(held, rung.groups)
                case _ as unreachable:
                    assert_never(unreachable)
        case _ as unreachable:
            assert_never(unreachable)


def _member_satisfies(held: tuple[str, ...], named: tuple[str, ...]) -> bool:
    """True iff the Member holds at least one of the named groups (OR-combined). An empty
    held set is vacuously False — a Member with no groups never clears a GROUPS rung."""
    return any(group in named for group in held)


def project(viewer: Viewer, article: Article) -> Article:
    """Project `article` to the fields `viewer` may see: the Archivist-only fields are floored
    (set to None) for any non-Archivist, regardless of whether the Viewer can otherwise view
    the Article. An Archivist sees everything. Returns a new Article — the frozen source is
    untouched. This does NOT decide visibility; gate with `can_view` separately.
    """
    match viewer:
        case Archivist():
            return article
        case Public() | Member():
            # Explicit kwargs (not **ARCHIVIST_ONLY_FIELDS) so mypy --strict type-checks each
            # field; the drift-guard test pins that this floors exactly that named set.
            return replace(article, physical_location=None, physical_description=None)
        case _ as unreachable:
            assert_never(unreachable)


@dataclass(frozen=True, slots=True)
class VisibilityPreview:
    """ "If published now, who sees this and which fields" — the ADR 0001 anti-over-exposure
    summary. `members` is a *plain* Member (no groups); `groups` names the groups that would
    see a GROUPS-rung Article (so the Archivist isn't misled by `members=False`)."""

    public: bool
    members: bool
    groups: tuple[str, ...]
    visible_fields: frozenset[str]


def preview(article: Article, chain: tuple[Collection, ...]) -> VisibilityPreview:
    """If `article` were published now, who would see it and which fields it would expose.

    Bypasses the Lifecycle gate by previewing a published projection (ADR 0001's publish-time
    warning), and routes who-sees through `can_view` — it never re-derives visibility, so it
    shares the one resolver. The rung is read only to surface the named groups for display.
    """
    published = replace(article, lifecycle=Lifecycle.PUBLISHED)
    public = can_view(Public(), published, chain)
    members = can_view(Member(), published, chain)
    groups = _would_be_groups(published, chain)
    visible_to_someone = public or members or bool(groups)
    return VisibilityPreview(
        public=public,
        members=members,
        groups=groups,
        visible_fields=_MEMBER_VISIBLE_FIELDS if visible_to_someone else frozenset(),
    )


def _would_be_groups(article: Article, chain: tuple[Collection, ...]) -> tuple[str, ...]:
    """The named groups of the effective rung, if it is a GROUPS rung — else empty. Reads the
    resolver's output for display only; the who-sees decision stays in `can_view`."""
    try:
        effective = effective_audience(article, chain)
    except DomainError:
        return ()
    if isinstance(effective, Audience) and effective.tier is AudienceTier.GROUPS:
        return effective.groups
    return ()
