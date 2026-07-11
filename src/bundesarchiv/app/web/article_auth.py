"""Article-level authorization for the full-Article render path (detail view + preview pane).

The media routes gate BYTES; this gates an ARTICLE view. Same discipline, same 404: validate the
ulid, load the Article from the canonical store, resolve its Collection chain, and ``visible``-project
it — returning the projection ONLY if every check passes, else ``None`` (the caller returns the media
route's byte-identical ``_not_found``). A forbidden article is indistinguishable from a missing one
(existence-hiding, plan §4.3), so a result link a viewer can't follow leaks nothing.

``resolve_visible_detail`` is the ONE pipeline (one load → resolve → ``visible``-project + version +
is_archivist); ``resolve_visible_article`` is the pane's thin wrapper over it. Keeping one pipeline
means the fail-closed order — malformed → absent → broken chain → denied — can never drift between
the pane and the detail page.
"""

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest

from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.access import visible
from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Article, Collection, Ulid
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository


def _canonical_store() -> ObjectStore:
    """The canonical files-store (ADR 0005), built per request from settings — the same construction
    the media views use. Monkeypatchable in tests."""
    return LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))


def resolve_visible_article(request: HttpRequest, ulid: str) -> Article | None:
    """The preview pane's resolution: the Article PROJECTED to the viewer's visible fields
    (``visible`` = can_view + project), or ``None`` on any deny/absence/malformed/broken-chain.

    A thin wrapper over ``resolve_visible_detail`` (the ONE full-Article render pipeline): the pane
    just takes the projected Article and ignores the detail-only extras (chain/version/is_archivist).
    Keeping one pipeline means the fail-closed order — malformed → absent → broken chain → denied —
    can never drift between the pane and the detail page."""
    resolution = resolve_visible_detail(request, ulid)
    return resolution.article if resolution is not None else None


@dataclass(frozen=True, slots=True)
class DetailResolution:
    """One resolution of the full-Article render path: the ``visible``-projected Article (for the
    template), its owning Collection ``chain`` (leaf-first, for the 4.6 Bestand breadcrumb — names are
    member-safe), its raw ``version`` (the archivist action-row's lifecycle CAS field), and
    ``is_archivist`` (the presentation gate for the action row + ENTWURF badge). One store load."""

    article: Article
    chain: ResolvedChain
    version: int
    is_archivist: bool


def resolve_visible_detail(request: HttpRequest, ulid: str) -> DetailResolution | None:
    """The full-Article render pipeline (spec §8): load ONCE, resolve the chain, ``visible``-project,
    and read ``.version`` off the same ``LoadedArticle`` — returning the projection + chain + version
    + is_archivist, or ``None`` on any deny/absence/malformed/broken-chain (the byte-identical 404).

    The ONE resolution path for a rendered full Article — the 4.6 detail view uses it directly;
    ``resolve_visible_article`` (the pane) wraps it. Fail-closed order: a malformed ulid, a
    missing/unreadable article, a broken chain, or a denied viewer all collapse to ``None`` —
    indistinguishable, so a rendered page can never be an existence oracle. This kills the 4.5 stub's
    double load (it loaded once to authorize, again for the version); the version comes free off the
    one ``load`` the projection already needs, surfaced to the template only when ``is_archivist``."""
    if not is_valid_ulid(ulid):
        return None
    store = _canonical_store()
    try:
        loaded = ArticleRepository(store).load(ulid)
    except ArchiveError:
        return None
    viewer = viewer_of(request)
    try:
        chain = resolve_chain(loaded.article.collection_id, _collections(store))
    except DomainError:
        return None
    projected = visible(viewer, loaded.article, chain)
    if projected is None:
        return None  # denied viewer (incl. a draft to a non-archivist) — fail closed
    return DetailResolution(
        article=projected,
        chain=chain,
        version=loaded.version,
        is_archivist=isinstance(viewer, Archivist),
    )


def _collections(store: ObjectStore) -> dict[Ulid, Collection]:
    """Every saved Collection as a ULID→Collection map for ``resolve_chain`` (read-only, per request;
    chain resolution is injected the lookup, never fetches — domain purity)."""
    return {c.ulid: c for c in CollectionRepository(store).load_all()}
