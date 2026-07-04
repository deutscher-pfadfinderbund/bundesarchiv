"""The scope seam — the single place viewer-visibility is turned into index columns and,
symmetrically, into a SQL predicate. This module is security-critical: it is the ONLY code
that may translate the domain's Audience/Viewer types into the flat ``ArticleIndex`` scope
columns and the ``Q`` filter over them. No tier comparison lives anywhere else in the index
adapter (Task 8's ``search`` imports ``_viewer_scope``; it does not re-derive one).

The two halves are deliberately adjacent and mirror each other:

- ``_scope_columns`` (WRITE side) folds an ``EffectiveAudience`` into the columns the indexer
  stores per row (``archivist_only`` / ``tier`` / ``groups``).
- ``_viewer_scope`` (READ side) folds a ``Viewer`` into the ``Q`` that selects exactly the rows
  that Viewer may see, over those same columns.

They are a materialized restatement of ``domain.access.can_view``, not an independent
reimplementation (ADR 0012): the READ side must stay row-equivalent to running ``can_view``
per Article, which Task 9's ``test_equivalence.py`` pins by comparison. Both ``match`` blocks
close over their unions with ``assert_never``, so adding a member to ``EffectiveAudience`` /
``Viewer`` or a rung to ``AudienceTier`` becomes a type error rather than a silent fail-open —
the same closed-set discipline the domain resolver uses.
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
    tier: str | None  # "PUBLIC" | "MEMBERS" | "GROUPS"; None iff archivist_only
    groups: tuple[str, ...]


def _scope_columns(effective: EffectiveAudience) -> ScopeColumns:
    """WRITE side of the seam: fold a resolved ``EffectiveAudience`` into stored columns.

    Mirror of ``_viewer_scope`` below — the tier strings this emits are exactly the ones the
    READ side matches against. An ``ArchivistOnly`` effective audience becomes the fail-closed
    shape (``tier=None``, no groups) that only an ``Archivist`` viewer's ``Q`` (empty) selects.
    """
    match effective:
        case ArchivistOnly():
            return ScopeColumns(archivist_only=True, tier=None, groups=())
        case Audience(tier=tier, groups=groups):
            return ScopeColumns(archivist_only=False, tier=tier.name, groups=groups)
        case _ as unreachable:
            assert_never(unreachable)


def _viewer_scope(viewer: Viewer) -> Q:
    """READ side of the seam: the ``Q`` selecting exactly the rows ``viewer`` may see.

    Row-equivalent mirror of ``_scope_columns`` above and of ``domain.access.can_view``
    (comparison pinned by Task 9's ``test_equivalence.py``) — the ONLY place a Viewer meets
    SQL. The tier strings here are the ``AudienceTier.name`` values ``_scope_columns`` writes.

    - ``Archivist``: an empty ``Q`` — sees everything, including fail-closed archivist-only rows.
    - ``Member``: never an archivist-only row; clears PUBLIC/MEMBERS unconditionally, and a
      GROUPS row only if the row's groups overlap the groups the Member holds.
    - ``Public``: only non-archivist PUBLIC rows.
    """
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
