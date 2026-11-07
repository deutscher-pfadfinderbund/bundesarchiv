from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from django.http import HttpRequest

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.access import can_view, project_change, project_versions, visible
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Article, Aspect, Change, Version
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.errors import ArchiveError


@dataclass(frozen=True, slots=True)
class DetailResolution:
    """``article`` is the ``visible`` projection; ``version`` the stored one the archivist's CAS
    writes expect; ``sees_files`` whether the viewer may open the files too (ADR 0027); ``change``
    who wrote it, floored by ``project_change``; ``versions`` reads every version with its change
    record when called, floored by ``project_versions``."""

    article: Article
    chain: ResolvedChain
    is_archivist: bool
    sees_files: bool
    version: Version
    change: Change | None
    versions: Callable[[], tuple[tuple[Version, Change | None], ...]]


def resolve_visible_detail(
    request: HttpRequest, ulid: str, archive: Archive, chooser: CollectionChooser
) -> DetailResolution | None:
    """The Article ``request``'s viewer may see at ``ulid``, or ``None`` — malformed, absent, broken
    chain and denied are indistinguishable."""
    if not is_valid_ulid(ulid):
        return None
    try:
        loaded = archive.articles.load(ulid)
    except ArchiveError:
        return None
    viewer = viewer_of(request)
    chain = chooser.chain_of(loaded.article.collection_id)
    if chain is None:
        return None
    projected = visible(viewer, loaded.article, chain)
    if projected is None:
        return None  # denied viewer (incl. a draft to a non-archivist) — fail closed
    return DetailResolution(
        article=projected,
        chain=chain,
        is_archivist=isinstance(viewer, Archivist),
        sees_files=can_view(viewer, loaded.article, chain, Aspect.FILES),
        version=loaded.version,
        change=project_change(viewer, loaded.change),
        versions=partial(project_versions, viewer, partial(archive.articles.versions, loaded)),
    )
