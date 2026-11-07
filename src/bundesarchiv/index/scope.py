"""The scope seam (ADR 0012): the only translation of Audience and Viewer into ``ArticleIndex``
scope columns (write side) and the ``Q`` over them (read side), one set per aspect (ADR 0027). The
read side must stay row-equivalent to ``domain.access.can_view``.
"""

from collections.abc import Mapping
from typing import TypedDict, assert_never, cast

from django.db.models import Q

from bundesarchiv.domain.audience import ArchivistOnly, EffectiveAudience
from bundesarchiv.domain.models import Aspect, Audience
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

# The prefix of each aspect's scope columns on ``ArticleIndex``.
_COLUMN_PREFIX = {Aspect.RECORD: "", Aspect.FILES: "files_"}


class ScopeRow(TypedDict):
    """The scope columns of one ``ArticleIndex`` row, ``_COLUMN_PREFIX`` spelled out. ``tier`` is
    ``None`` iff ``archivist_only`` (an archivist-only row is not a rung on the ladder);
    ``groups`` is non-empty only on a GROUPS tier."""

    archivist_only: bool
    tier: str | None
    groups: list[str]
    files_archivist_only: bool
    files_tier: str | None
    files_groups: list[str]


def scope_row(effective: Mapping[Aspect, EffectiveAudience]) -> ScopeRow:
    """The write-side materialization of each aspect's resolved audience."""
    return cast(
        ScopeRow,
        {
            f"{_COLUMN_PREFIX[aspect]}{column}": value
            for aspect in Aspect
            for column, value in _columns(effective[aspect]).items()
        },
    )


def _columns(effective: EffectiveAudience) -> dict[str, bool | str | list[str] | None]:
    """``_rung_scope`` matches these ``AudienceTier.name`` strings as literals."""
    match effective:
        case ArchivistOnly():
            return {"archivist_only": True, "tier": None, "groups": []}
        case Audience(tier=tier, groups=groups):
            return {"archivist_only": False, "tier": tier.name, "groups": list(groups)}
        case _ as unreachable:
            assert_never(unreachable)


def _viewer_scope(viewer: Viewer, aspect: Aspect) -> Q:
    """The rows whose ``aspect`` rung ``viewer`` clears, only together with the record, as
    ``can_view`` (ADR 0027)."""
    return _rung_scope(viewer, "") & _rung_scope(viewer, _COLUMN_PREFIX[aspect])


def _rung_scope(viewer: Viewer, p: str) -> Q:
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
