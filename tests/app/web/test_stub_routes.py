"""Stub-route auth discipline for the workbench (Part 4.5-MVP).

Two stub routes are registered now so their URL names are stable for 4.6/4.7, and — critically —
so their VISIBILITY GATE ships with the workbench, not after it:

- ``/artikel/neu`` (``artikel-neu``) — the "Neuer Artikel" target. Archivist-only. A non-Archivist
  gets the SAME byte-identical 404 the media routes return (existence-hiding: a Member must not learn
  the cataloging entry point even exists).
- ``/artikel/<ulid>`` (``artikel-detail``) — the result-link target. Applies the SAME visibility
  rule it eventually will: load + resolve the chain + ``can_view``; any deny (forbidden article,
  missing article, malformed ulid, broken chain) collapses to the byte-identical 404.

These are pure request-handling against a local FS store (load + resolve + can_view) — no Postgres,
so they run with no container (the web/ subtree is exempt from SKIP_PG).
"""

from pathlib import Path

import pytest
from django.core import signing
from django.http.response import HttpResponseBase
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-stub-dev-key"


class _Corpus:
    """A tiny FS-store archive: one public-published, one members-only, one draft article, each in a
    tiered Collection — enough to exercise the detail stub's can_view gate per viewer."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        self.ulid_by_tier: dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        collections = CollectionRepository(self.store)
        articles = ArticleRepository(self.store)
        collections.save(Collection("ROOT", "Wurzel", None), 0)
        collections.save(Collection("PUB", "Public", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        collections.save(Collection("MEM", "Members", "ROOT", Audience(AudienceTier.MEMBERS)), 0)
        specs = [
            ("public", "PUB", Lifecycle.PUBLISHED),
            ("members", "MEM", Lifecycle.PUBLISHED),
            ("draft", "PUB", Lifecycle.DRAFT),
        ]
        for tier, coll, lifecycle in specs:
            ulid = new_ulid()
            articles.save(
                Article(
                    ulid=ulid, title=f"{tier} Artikel", collection_id=coll, lifecycle=lifecycle
                ),
                0,
            )
            self.ulid_by_tier[tier] = ulid


@pytest.fixture
def corpus(tmp_path: Path) -> _Corpus:
    return _Corpus(tmp_path / "canonical")


def _settings(corpus: _Corpus, **extra: object) -> dict[str, object]:
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(corpus.root),
        **extra,
    }


def _client_as(viewer: Viewer) -> Client:
    client = Client()
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def _media_404_shape() -> tuple[bytes, frozenset[tuple[str, str]]]:
    """The byte-identical 404 the media route emits, captured directly from ``media_views`` so the
    stubs are pinned to the SAME shape (not a copy that could drift)."""
    from bundesarchiv.app.web.media_views import _not_found

    r = _not_found()
    volatile = {"Date", "Server", "X-Frame-Options", "Vary", "Content-Language"}
    headers = frozenset((k, v) for k, v in r.items() if k not in volatile)
    return r.content, headers


def _stub_404_shape(response: HttpResponseBase) -> tuple[bytes, frozenset[tuple[str, str]]]:
    volatile = {"Date", "Server", "X-Frame-Options", "Vary", "Content-Language"}
    headers = frozenset((k, v) for k, v in response.items() if k not in volatile)
    content: bytes = response.content  # type: ignore[attr-defined]  # 404s are non-streaming
    return content, headers


# --- /artikel/neu (archivist-gated stub) -----------------------------------------


def test_neu_stub_served_to_archivist(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get("/artikel/neu")
    assert response.status_code == 200
    assert "4.7" in response.content.decode()  # the German "kommt in 4.7" placeholder


@pytest.mark.parametrize("viewer", [Public(), Member(groups=("vorstand",))])
def test_neu_stub_is_byte_identical_404_for_non_archivist(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).get("/artikel/neu")
    assert response.status_code == 404
    assert _stub_404_shape(response) == _media_404_shape()


# --- /artikel/<ulid> (detail stub, can_view gated) -------------------------------


def test_detail_stub_served_when_can_view(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Public()).get(f"/artikel/{corpus.ulid_by_tier['public']}")
    assert response.status_code == 200
    assert "4.6" in response.content.decode()  # the German "kommt in 4.6" placeholder


def test_detail_stub_denies_forbidden_article_as_byte_identical_404(corpus: _Corpus) -> None:
    # A members-only article, viewed as Public → the SAME 404 as a nonexistent one (existence-hiding).
    with override_settings(**_settings(corpus)):
        response = _client_as(Public()).get(f"/artikel/{corpus.ulid_by_tier['members']}")
    assert response.status_code == 404
    assert _stub_404_shape(response) == _media_404_shape()


def test_detail_stub_denies_draft_to_member(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Member(groups=())).get(f"/artikel/{corpus.ulid_by_tier['draft']}")
    assert response.status_code == 404


def test_detail_stub_archivist_sees_draft(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{corpus.ulid_by_tier['draft']}")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "ulid",
    ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"],  # malformed, then well-formed-but-absent
)
def test_detail_stub_malformed_or_missing_is_byte_identical_404(corpus: _Corpus, ulid: str) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{ulid}")
    assert response.status_code == 404
    assert _stub_404_shape(response) == _media_404_shape()
