"""The scope seam (ADR 0012): the only translation of Audience and Viewer into ``ArticleIndex``
scope columns (write side) and the ``Q`` over them (read side). The read side must stay
row-equivalent to ``domain.access.can_view``.
"""

from dataclasses import dataclass
from typing import assert_never

from django.db.models import Q

from bundesarchiv.domain.audience import ArchivistOnly, EffectiveAudience
from bundesarchiv.domain.models import Audience
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


@dataclass(frozen=True, slots=True)
class ScopeColumns:
    """The flat scope columns one ``ArticleIndex`` row carries — the write-side materialization
    of an ``EffectiveAudience``. ``tier`` is ``None`` iff ``archivist_only`` (an archivist-only
    row is not a rung on the ladder); ``groups`` is non-empty only on a GROUPS tier."""

    archivist_only: bool
    tier: str | None
    groups: tuple[str, ...]


def _scope_columns(effective: EffectiveAudience) -> ScopeColumns:
    """Write side: the columns an ``EffectiveAudience`` is stored as. Tier strings are
    ``AudienceTier.name``, which ``_viewer_scope`` matches."""
    match effective:
        case ArchivistOnly():
            return ScopeColumns(archivist_only=True, tier=None, groups=())
        case Audience(tier=tier, groups=groups):
            return ScopeColumns(archivist_only=False, tier=tier.name, groups=groups)
        case _ as unreachable:
            assert_never(unreachable)


def _viewer_scope(viewer: Viewer) -> Q:
    """Read side: the ``Q`` selecting exactly the rows ``viewer`` may see, row-equivalent to
    ``can_view``."""
    match viewer:
        case Archivist():
            return Q()
        case Member(groups=groups):
            return Q(archivist_only=False) & (
                Q(tier__in=("PUBLIC", "MEMBERS"))
                | (Q(tier="GROUPS") & Q(groups__overlap=list(groups)))
            )
        case Public():
            return Q(archivist_only=False, tier="PUBLIC")
        case _ as unreachable:
            assert_never(unreachable)
