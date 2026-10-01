"""Article-level authorization for the full-Article render path (detail view + preview pane).

The media routes gate BYTES; this gates an ARTICLE view. Same discipline, same 404: validate the
ulid, load the Article from the canonical store, resolve its Collection chain, and ``visible``-project
it — returning the projection ONLY if every check passes, else ``None`` (the caller returns the media
route's shared empty ``not_found``). A forbidden article is indistinguishable from a missing one
(existence-hiding, plan §4.3), so a result link a viewer can't follow leaks nothing.

``resolve_visible_detail`` is the ONE pipeline (one load → resolve → ``visible``-project +
is_archivist); ``resolve_visible_article`` is the pane's thin wrapper over it. Keeping one pipeline
means the fail-closed order — malformed → absent → broken chain → denied — can never drift between
the pane and the detail page.
"""

from dataclasses import dataclass

from django.http import HttpRequest

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.access import visible
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Article, Version
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.errors import ArchiveError


def resolve_visible_article(request: HttpRequest, ulid: str) -> Article | None:
    """The preview pane's resolution: the Article PROJECTED to the viewer's visible fields
    (``visible`` = can_view + project), or ``None`` on any deny/absence/malformed/broken-chain.

    A thin wrapper over ``resolve_visible_detail`` (the ONE full-Article render pipeline): the pane
    just takes the projected Article and ignores the detail-only extras (chain + is_archivist).
    Keeping one pipeline means the fail-closed order — malformed → absent → broken chain → denied —
    can never drift between the pane and the detail page."""
    resolution = resolve_visible_detail(request, ulid)
    return resolution.article if resolution is not None else None


@dataclass(frozen=True, slots=True)
class DetailResolution:
    """One resolution of the full-Article render path: the ``visible``-projected Article (for the
    template), its owning Collection ``chain`` (leaf-first, for the 4.6 Bestand breadcrumb — names are
    member-safe), ``is_archivist`` (the presentation gate for the archivist's tools) and the stored
    ``version`` the tools' CAS writes expect. One store load."""

    article: Article
    chain: ResolvedChain
    is_archivist: bool
    version: Version


def resolve_visible_detail(request: HttpRequest, ulid: str) -> DetailResolution | None:
    """The full-Article render pipeline (spec §8): load ONCE, resolve the chain, ``visible``-project —
    returning the projection + chain + is_archivist, or ``None`` on any
    deny/absence/malformed/broken-chain.

    The ONE resolution path for a rendered full Article — the 4.6 detail view uses it directly;
    ``resolve_visible_article`` (the pane) wraps it. Fail-closed order: a malformed ulid, a
    missing/unreadable article, a broken chain, or a denied viewer all collapse to ``None`` —
    indistinguishable, so a rendered page can never be an existence oracle."""
    if not is_valid_ulid(ulid):
        return None
    archive = Archive.canonical()
    try:
        loaded = archive.articles.load(ulid)
    except ArchiveError:
        return None
    viewer = viewer_of(request)
    chain = BestandChooser.of(archive).chain_of(loaded.article.collection_id)
    if chain is None:
        return None
    projected = visible(viewer, loaded.article, chain)
    if projected is None:
        return None  # denied viewer (incl. a draft to a non-archivist) — fail closed
    return DetailResolution(
        article=projected,
        chain=chain,
        is_archivist=isinstance(viewer, Archivist),
        version=loaded.version,
    )
