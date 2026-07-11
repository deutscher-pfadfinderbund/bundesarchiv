"""Article-level authorization for the workbench detail path (Part 4.5-MVP).

The media routes gate BYTES; this gates an ARTICLE view. Same discipline, same 404: validate the
ulid, load the Article from the canonical store, resolve its Collection chain, and ``can_view`` it —
returning the Article ONLY if every check passes, else ``None`` (the caller returns the media
route's byte-identical ``_not_found``). A forbidden article is indistinguishable from a missing one
(existence-hiding, plan §4.3), so a result link a viewer can't follow leaks nothing.

This is the FIRST full-Article detail caller. It mirrors ``media_views._authorize`` deliberately
(one load → resolve → can_view shape across the whole web layer) but returns the Article rather than
a MediaRef, since a detail view has no blob to locate. The projection to member-visible fields
(``project``) is 4.6's job; the stub only proves the GATE, so it never emits Article fields.
"""

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest

from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.access import can_view, visible
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


def authorize_article(request: HttpRequest, ulid: str) -> Article | None:
    """The shared gate for the detail path: validate the ulid, load the Article, resolve its chain,
    and ``can_view`` it — returning the Article ONLY if the request's viewer may see it, else
    ``None`` (the caller maps ``None`` to the byte-identical 404).

    Order matches the media route: a malformed param, a missing/unreadable article, a broken chain,
    or a denied viewer all collapse to ``None`` — no reason is distinguishable to the caller."""
    if not is_valid_ulid(ulid):
        return None
    store = _canonical_store()
    try:
        article = ArticleRepository(store).load(ulid).article
    except ArchiveError:
        return None  # no such article (or unreadable) → treated as not-found (existence-hiding)
    viewer = viewer_of(request)
    try:
        chain = resolve_chain(article.collection_id, _collections(store))
    except DomainError:
        return None  # broken/unresolvable chain → deny everyone (fail closed)
    if not can_view(viewer, article, chain):
        return None  # AUTHORIZATION denies here
    return article


def resolve_visible_article(request: HttpRequest, ulid: str) -> Article | None:
    """Like ``authorize_article`` but returns the Article PROJECTED to the viewer's visible fields
    (``visible`` = can_view + project), or ``None`` on any deny/absence/malformed/broken-chain — the
    ONE resolution path for a full-Article RENDER (the preview pane, the 4.6 detail).

    Same fail-closed order as ``authorize_article``: a malformed ulid, a missing/unreadable article,
    a broken chain, or a denied viewer all collapse to ``None`` — indistinguishable to the caller, so
    a rendered pane can never be an existence oracle. The returned Article has ARCHIVIST_ONLY_FIELDS
    floored for non-archivists, so the render layer cannot leak a floored field even by accident."""
    if not is_valid_ulid(ulid):
        return None
    store = _canonical_store()
    try:
        article = ArticleRepository(store).load(ulid).article
    except ArchiveError:
        return None
    viewer = viewer_of(request)
    try:
        chain = resolve_chain(article.collection_id, _collections(store))
    except DomainError:
        return None
    return visible(viewer, article, chain)


@dataclass(frozen=True, slots=True)
class DetailResolution:
    """One resolution of the 4.6 detail path: the ``visible``-projected Article (for the template),
    its owning Collection ``chain`` (leaf-first, for the Bestand breadcrumb — names are member-safe),
    its raw ``version`` (the archivist action-row's lifecycle CAS field), and ``is_archivist`` (the
    presentation gate for the action row + ENTWURF badge). Produced by a SINGLE store load."""

    article: Article
    chain: ResolvedChain
    version: int
    is_archivist: bool


def resolve_visible_detail(request: HttpRequest, ulid: str) -> DetailResolution | None:
    """The detail page's single entry (spec §8): load ONCE, resolve the chain, ``visible``-project,
    and read ``.version`` off the same ``LoadedArticle`` — returning the projection + version +
    is_archivist, or ``None`` on any deny/absence/malformed/broken-chain (the byte-identical 404).

    Same fail-closed order as ``resolve_visible_article`` (which the pane keeps): a malformed ulid, a
    missing/unreadable article, a broken chain, or a denied viewer all collapse to ``None`` —
    indistinguishable, so the rendered detail view is never an existence oracle. This kills the stub's
    double load (``authorize_article`` + ``_detail_version`` each loaded); the version comes free off
    the one ``load`` the projection already needs. The version is meaningful only to the archivist
    CAS field; the caller surfaces it to the template only when ``is_archivist``."""
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
