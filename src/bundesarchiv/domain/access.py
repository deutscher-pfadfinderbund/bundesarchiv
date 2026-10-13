"""Viewer-facing access: the only place a Viewer meets an Article's resolved Audience,
always through `effective_audience` (ADR 0001). Pure."""

from dataclasses import dataclass, fields, replace
from typing import assert_never

from bundesarchiv.domain.audience import ArchivistOnly, effective_audience
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

# Fields floored from every non-Archivist projection. `project` names them explicitly, and the
# drift test in tests/domain/test_access.py keeps the two equal.
ARCHIVIST_ONLY_FIELDS: frozenset[str] = frozenset({"physical_location", "custom"})

# Fail at import on a name Article lacks (a typo or a renamed field). A raise, not an assert,
# because `python -O` strips asserts.
if _unknown := ARCHIVIST_ONLY_FIELDS - {f.name for f in fields(Article)}:
    raise RuntimeError(f"ARCHIVIST_ONLY_FIELDS names unknown Article fields: {_unknown}")


def can_view(viewer: Viewer, article: Article, chain: ResolvedChain) -> bool:
    """Fail-closed yes/no: may `viewer` see `article` given its resolved Collection `chain`?

    Any `DomainError` from resolution (e.g. a chain resolved for a different Article) denies
    *everyone*, including an Archivist — an unresolvable chain yields no Audience to authorize
    against.
    """
    try:
        effective = effective_audience(article, chain)
    except DomainError:
        return False
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
    """OR-combined: the Member holds at least one named group."""
    return any(group in named for group in held)


def project(viewer: Viewer, article: Article) -> Article:
    """`article` with the Archivist-only fields floored for any non-Archivist. Not a visibility
    gate: that is `can_view`."""
    match viewer:
        case Archivist():
            return article
        case Public() | Member():
            # Explicit kwargs keep each floored field type-checked; the drift test pins them to
            # ARCHIVIST_ONLY_FIELDS.
            return replace(article, physical_location=None, custom=())
        case _ as unreachable:
            assert_never(unreachable)


def visible(viewer: Viewer, article: Article, chain: ResolvedChain) -> Article | None:
    """``can_view`` then ``project`` in one call: None on deny, else the floored copy, so no
    call site can apply only one half."""
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


def preview(article: Article, chain: ResolvedChain) -> VisibilityPreview:
    """Who would see `article` if it were published now (ADR 0001 publish-time warning),
    decided by `can_view`."""
    published = replace(article, lifecycle=Lifecycle.PUBLISHED, template=False)
    public = can_view(Public(), published, chain)
    members = can_view(Member(), published, chain)
    return VisibilityPreview(
        public=public, members=members, groups=_would_be_groups(published, chain)
    )


def _would_be_groups(article: Article, chain: ResolvedChain) -> tuple[str, ...]:
    """The effective rung's groups, for display; empty unless it is a GROUPS rung."""
    try:
        effective = effective_audience(article, chain)
    except DomainError:
        return ()
    if isinstance(effective, Audience) and effective.tier is AudienceTier.GROUPS:
        return effective.groups
    return ()
