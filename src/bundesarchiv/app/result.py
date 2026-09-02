"""The result shapes the write services return.

A service returns more than the new ``Version``: the view needs to know whether the SYNCHRONOUS
index update took effect. When it did not (the canonical write stood, but the index update failed
and a retry job was enqueued), the view must show the ADR-0014 specific warning
"Sichtbarkeitsänderung noch nicht wirksam" — the archivist just made an access-control decision
that has not yet propagated. ``index_updated`` carries exactly that bit.

``UpdateOutcome`` is the closed union ``update_article`` answers with. A raising service tells the
caller "your version was stale"; the retrying one has already spent its retries, so the only things
left to say are "committed", "lost every race" and "gone" — a union the caller must match on
exhaustively rather than a ``Conflict`` it might forget to catch.
"""

from dataclasses import dataclass

from bundesarchiv.domain.models import Article, Ulid, Version


@dataclass(frozen=True, slots=True)
class SaveResult:
    """Outcome of a save/delete service call. ``version`` is the new canonical version (the durable
    truth, always valid because the canonical write is what happened first). ``index_updated`` is
    True iff the synchronous index update succeeded in-request; False means the canonical write
    stood but the index is momentarily stale and a reindex job was enqueued — the view shows the
    specific visibility-not-yet-effective warning (ADR 0014)."""

    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class CreateResult:
    """Outcome of ``create_article``: the freshly-minted ``ulid`` plus the same fields as
    ``SaveResult``. The ulid is surfaced so the view can redirect to the new Article."""

    ulid: Ulid
    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class Updated:
    """``update_article`` committed the mutation. Carries the SAVED ``article`` — the caller handed
    in a transform, not a value, and after a retry the article is the mutation applied to the
    WINNER's state, which only this service knows. With ``version`` it is everything a re-render
    needs, so the caller pays for no second load. ``index_updated`` as in ``SaveResult``."""

    article: Article
    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class Conflicted:
    """Every attempt lost the race (ADR 0013): nothing of the caller's was committed and the
    concurrent writer's state stands. The caller tells the archivist to try again."""


@dataclass(frozen=True, slots=True)
class Missing:
    """No Article at that ulid — absent from the start, or hard-deleted underneath a retry. Web
    callers collapse this to the plain 404, never to a conflict hinweis (existence-hiding)."""


type UpdateOutcome = Updated | Conflicted | Missing
