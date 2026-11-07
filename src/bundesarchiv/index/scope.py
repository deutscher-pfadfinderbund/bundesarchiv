"""The scope seam (ADR 0012): the only translation of Audience and Viewer into ``ArticleIndex``
scope columns (write side) and the ``Q`` over them (read side), one set per aspect (ADR 0027). The
read side must stay row-equivalent to ``domain.access.can_view``.
"""

from dataclasses import dataclass
from typing import assert_never

from django.db.models import Q

from bundesarchiv.domain.audience import ArchivistOnly, EffectiveAudience
from bundesarchiv.domain.models import Aspect, Audience
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
    """``_viewer_scope`` matches these ``AudienceTier.name`` strings as literals."""
    match effective:
        case ArchivistOnly():
            return ScopeColumns(archivist_only=True, tier=None, groups=())
        case Audience(tier=tier, groups=groups):
            return ScopeColumns(archivist_only=False, tier=tier.name, groups=groups)
        case _ as unreachable:
            assert_never(unreachable)


# The prefix of each aspect's scope columns on ``ArticleIndex``.
_COLUMN_PREFIX = {Aspect.RECORD: "", Aspect.FILES: "files_"}


def _viewer_scope(viewer: Viewer, aspect: Aspect) -> Q:
    """The rows whose ``aspect`` rung ``viewer`` clears; for ``FILES`` it holds only beside the
    ``RECORD`` scope (ADR 0027)."""
    p = _COLUMN_PREFIX[aspect]
    match viewer:
        case Archivist():
            return Q()
        case Member(groups=groups):
            return Q(**{f"{p}archivist_only": False}) & (
                Q(**{f"{p}tier__in": ("PUBLIC", "MEMBERS")})
                | Q(**{f"{p}tier": "GROUPS", f"{p}groups__overlap": list(groups)})
            )
        case Public():
            return Q(**{f"{p}archivist_only": False, f"{p}tier": "PUBLIC"})
        case _ as unreachable:
            assert_never(unreachable)
