"""Shared corpus builders and the signed-viewer client for the web suite.

This is the whole wiring for ``tests/app/web/``, held once so no file clones another's: the
``corpus`` / ``make_corpus`` fixtures in ``conftest.py`` hand it out with the settings override
already applied.

**The standard corpus is FROZEN.** ``standard_corpus`` is ROOT → PUB (PUBLIC) with exactly two
articles, ``PUBLISHED_ULID`` and ``DRAFT_ULID``. Never extend it: a test that asserts a global
count, a listing or a facet total reads the whole store, so one added record silently rewrites
another file's expectations. Such a test builds its own content with ``make_corpus``.
"""

from pathlib import Path
from typing import Any

from django.core import signing
from django.test import Client

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
    Ulid,
    Version,
)
from bundesarchiv.domain.viewer import Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

DEV_KEY = "test-web-dev-viewer-key"

ROOT = "ROOT"
# A real ULID: the collection routes validate their ``<ulid>`` in-view, so a mnemonic literal
# would 404 there instead of failing loudly.
PUB = "01KX7YT9E3VX0CP3A5Q49RZMPB"
PUBLISHED_ULID = "01KX7YT9E3VX0CP3A5Q49RZMWK"
DRAFT_ULID = "01KX7YT9E3VX0CP3A5Q49RZMVH"


def client_as(viewer: Viewer | None, *, enforce_csrf: bool = False) -> Client:
    """A test client carrying the signed ``dev_viewer`` cookie for ``viewer`` — or, for ``None``,
    no cookie at all (an anonymous visitor)."""
    client = Client(enforce_csrf_checks=enforce_csrf)
    if viewer is not None:
        signer = signing.TimestampSigner(key=DEV_KEY, salt=_DEV_VIEWER_SALT)
        client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def make_collection(
    ulid: Ulid,
    name: str = "Sammlung",
    parent_id: Ulid | None = ROOT,
    audience: Audience | None = None,
) -> Collection:
    """A Collection under ROOT — pass only what the test asserts about."""
    return Collection(ulid, name, parent_id, audience)


def make_article(
    ulid: Ulid,
    *,
    collection_id: Ulid = PUB,
    lifecycle: Lifecycle = Lifecycle.PUBLISHED,
    title: str = "Testartikel",
    **overrides: Any,
) -> Article:
    """An Article filed in PUB — pass only what the test asserts about. ``ulid`` stays explicit:
    tests address records by ulid, and the views reject anything that is not a real ULID
    (``is_valid_ulid``), so a literal like ``"A1"`` would 404 instead of failing loudly."""
    return Article(
        ulid=ulid,
        title=title,
        collection_id=collection_id,
        lifecycle=lifecycle,
        **overrides,
    )


class Corpus:
    """A local-FS archive rooted at ``root``, holding only the ROOT collection, with its store and
    both repositories ready for a test to add content through."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        self.collections = CollectionRepository(self.store)
        self.articles = ArticleRepository(self.store)
        self.collections.save(Collection(ROOT, "Wurzel", None), 0)

    def add_collection(self, collection: Collection) -> Version:
        return self.collections.save(collection, 0)

    def add_article(self, article: Article) -> Version:
        return self.articles.save(article, 0)


def standard_corpus(root: Path) -> Corpus:
    """The frozen standard shape: ROOT → PUB (PUBLIC) with one published and one draft article.
    See the module docstring before adding anything to it."""
    corpus = Corpus(root)
    corpus.add_collection(
        make_collection(PUB, "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    corpus.add_article(make_article(PUBLISHED_ULID, title="Sommerfahrt 1962", ref_code="F12"))
    corpus.add_article(
        make_article(
            DRAFT_ULID,
            lifecycle=Lifecycle.DRAFT,
            title="Entwurf Lagerchronik",
            ref_code="F9",
        )
    )
    return corpus


def settings_for(corpus: Corpus) -> dict[str, object]:
    """The settings a web test runs under: the prod urlconf, the dev-viewer signing key
    ``client_as`` signs with, and ``corpus`` as the canonical store."""
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(corpus.root),
    }
