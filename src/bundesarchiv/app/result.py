from dataclasses import dataclass

from bundesarchiv.domain.models import Article, Ulid, Version


@dataclass(frozen=True, slots=True)
class SaveResult:
    """``index_updated`` False: the write stood but the index lags, so the route must show the
    ADR 0014 warning."""

    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class CreateResult:
    ulid: Ulid
    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class Updated:
    """The saved ``article``: after a retry, the mutation applied to the winner."""

    article: Article
    version: Version
    index_updated: bool


@dataclass(frozen=True, slots=True)
class Conflicted:
    """Every attempt lost the race (ADR 0013): nothing of the caller's was committed and the
    concurrent writer's state stands. The caller tells the archivist to try again."""


@dataclass(frozen=True, slots=True)
class Missing:
    """No live Article: absent, in the Papierkorb, or gone underneath a retry."""


type UpdateOutcome = Updated | Conflicted | Missing
