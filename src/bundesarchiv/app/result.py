"""The result shapes the write services return.

A service returns more than the new ``Version``: the view needs to know whether the SYNCHRONOUS
index update took effect. When it did not (the canonical write stood, but the index update failed
and a retry job was enqueued), the view must show the ADR-0014 specific warning
"Sichtbarkeitsänderung noch nicht wirksam" — the archivist just made an access-control decision
that has not yet propagated. ``index_updated`` carries exactly that bit.
"""

from dataclasses import dataclass

from bundesarchiv.domain.models import Ulid, Version


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
