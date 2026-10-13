"""The write services' result shapes.

``index_updated`` False: the canonical write stood but the index lags, so the view shows the
ADR 0014 warning. ``UpdateOutcome`` is a closed union, so the caller must match it exhaustively,
not remember to catch ``Conflict``.
"""

from dataclasses import dataclass

from bundesarchiv.domain.models import Article, Ulid, Version


@dataclass(frozen=True, slots=True)
class SaveResult:
    """``index_updated``: the synchronous index update took effect in-request (ADR 0014)."""

    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class CreateResult:
    """A ``SaveResult`` plus the ``ulid`` a create service minted."""

    ulid: Ulid
    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class Updated:
    """``update_article`` committed: the SAVED ``article`` (after a retry, the mutation applied to
    the winner) at ``version``."""

    article: Article
    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class Conflicted:
    """Every attempt lost the race (ADR 0013): nothing of the caller's was committed and the
    concurrent writer's state stands. The caller tells the archivist to try again."""


@dataclass(frozen=True, slots=True)
class Missing:
    """No live Article at that ulid: absent, in the Papierkorb, or hard-deleted underneath a retry.
    Answer it with the plain 404 (existence-hiding)."""


type UpdateOutcome = Updated | Conflicted | Missing
