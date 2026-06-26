"""Viewer-facing access layer — composes the effective-Audience resolver with a Viewer.

This is the only place a Viewer meets an Article's resolved Audience. It imports
`effective_audience` (the single source, ADR 0001) and never re-derives a rung itself,
so every visibility decision routes through one resolver. Pure: no IO, no Keycloak.

The `match` statements close over their unions with `assert_never`: adding a member to
`EffectiveAudience` or `Viewer`, or a rung to `AudienceTier`, becomes a type error rather
than a silent fail-open — the leak the single-source resolver exists to prevent.
"""

from typing import assert_never

from bundesarchiv.domain.audience import ArchivistOnly, effective_audience
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


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
