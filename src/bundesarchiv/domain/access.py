"""Viewer-facing access over `effective_audience` (ADR 0001, per aspect ADR 0027); pure.
`index.scope` must stay row-equivalent to `can_view`."""

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from typing import assert_never

from bundesarchiv.domain.audience import ArchivistOnly, EffectiveAudience, effective_audience
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import (
    Article,
    Aspect,
    Audience,
    AudienceTier,
    Change,
    Lifecycle,
    Version,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

# `project` must floor exactly these.
ARCHIVIST_ONLY_FIELDS: frozenset[str] = frozenset({"physical_location", "custom"})

# A raise, not an assert: `python -O` strips asserts.
if _unknown := ARCHIVIST_ONLY_FIELDS - {f.name for f in fields(Article)}:
    raise RuntimeError(f"ARCHIVIST_ONLY_FIELDS names unknown Article fields: {_unknown}")


def can_view(
    viewer: Viewer, article: Article, chain: ResolvedChain, aspect: Aspect = Aspect.RECORD
) -> bool:
    """Fail-closed yes/no: may `viewer` see `aspect` of `article` given its resolved Collection
    `chain`? Only together with the record (ADR 0027).

    Any `DomainError` from resolution (e.g. a chain resolved for a different Article) denies
    *everyone*, including an Archivist — an unresolvable chain yields no Audience to authorize
    against.
    """
    try:
        return all(
            _viewer_clears(viewer, effective_audience(article, chain, a))
            for a in (Aspect.RECORD, aspect)
        )
    except DomainError:
        return False


def _viewer_clears(viewer: Viewer, effective: EffectiveAudience) -> bool:
    match effective:
        case ArchivistOnly():
            return isinstance(viewer, Archivist)
        case Audience() as rung:
            return _viewer_clears_rung(viewer, rung)
        case _ as unreachable:
            assert_never(unreachable)


def _viewer_clears_rung(viewer: Viewer, rung: Audience) -> bool:
    match viewer:
        case Archivist():
            return True
        case Public():
            return rung.tier is AudienceTier.PUBLIC
        case Member(groups=held):
            match rung.tier:
                case AudienceTier.PUBLIC | AudienceTier.MEMBERS:
                    return True
                case AudienceTier.GROUPS:
                    return _member_satisfies(held, rung.groups)
                case _ as unreachable:
                    assert_never(unreachable)
        case _ as unreachable:
            assert_never(unreachable)


def _member_satisfies(held: tuple[str, ...], named: tuple[str, ...]) -> bool:
    return any(group in named for group in held)


def project(viewer: Viewer, article: Article) -> Article:
    """Not a visibility gate: pair it with `can_view`, or use `visible`."""
    match viewer:
        case Archivist():
            return article
        case Public() | Member():
            # Explicit kwargs, not a loop over ARCHIVIST_ONLY_FIELDS, so each floor is type-checked.
            return replace(article, physical_location=None, custom=())
        case _ as unreachable:
            assert_never(unreachable)


def project_change(viewer: Viewer, change: Change | None) -> Change | None:
    """Who last changed a record is personal data: an Archivist's alone (owner ruling 2026-10-21)."""
    return change if _sees_changes(viewer) else None


def project_versions(
    viewer: Viewer, read: Callable[[], tuple[tuple[Version, Change | None], ...]]
) -> tuple[tuple[Version, Change | None], ...]:
    """Each version names its editor, so the list is an Archivist's alone, as `project_change`;
    `read` runs for no one else."""
    return read() if _sees_changes(viewer) else ()


def _sees_changes(viewer: Viewer) -> bool:
    match viewer:
        case Archivist():
            return True
        case Public() | Member():
            return False
        case _ as unreachable:
            assert_never(unreachable)


def visible(viewer: Viewer, article: Article, chain: ResolvedChain) -> Article | None:
    if not can_view(viewer, article, chain):
        return None
    return project(viewer, article)


@dataclass(frozen=True, slots=True)
class VisibilityPreview:
    """ "If published now, who sees this" — the ADR 0001 anti-over-exposure summary. `members` is
    a *plain* Member (no groups); `groups` names the groups that would see a GROUPS-rung Article
    (so the Archivist isn't misled by `members=False`)."""

    public: bool
    members: bool
    groups: tuple[str, ...]


def preview(
    article: Article, chain: ResolvedChain, aspect: Aspect = Aspect.RECORD
) -> VisibilityPreview:
    published = replace(article, lifecycle=Lifecycle.PUBLISHED, template=False)
    return VisibilityPreview(
        public=can_view(Public(), published, chain, aspect),
        members=can_view(Member(), published, chain, aspect),
        groups=_would_be_groups(published, chain, aspect),
    )


def _would_be_groups(article: Article, chain: ResolvedChain, aspect: Aspect) -> tuple[str, ...]:
    """The groups of the aspect's rung, else the record's: a viewer clears both (ADR 0027)."""
    try:
        rungs = [effective_audience(article, chain, a) for a in (aspect, Aspect.RECORD)]
    except DomainError:
        return ()
    return next(
        (r.groups for r in rungs if isinstance(r, Audience) and r.tier is AudienceTier.GROUPS), ()
    )
