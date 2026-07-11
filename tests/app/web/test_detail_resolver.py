"""The 4.6 detail resolver (`resolve_visible_detail`, spec §8) — one load feeding both the render
view-model and the archivist CAS version.

`resolve_visible_article` (the pane's path) returns only a projected Article; the detail view ALSO
needs the raw version for the lifecycle action-row's CAS field. Rather than load twice (the stub's
double-load bug), `resolve_visible_detail` loads ONCE and returns a `DetailResolution` carrying the
`visible`-projected Article + the version + the is_archivist flag. These tests pin the projection
(archivist-only fields floored for members) and the single load.
"""

from pathlib import Path

import pytest
from django.core import signing
from django.test import RequestFactory, override_settings

from bundesarchiv.app.web.article_auth import resolve_visible_detail
from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-detail-resolver-key"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    store = LocalFsObjectStore(tmp_path / "canonical")
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(Collection("ROOT", "Wurzel", None), 0)
    collections.save(Collection("PUB", "Public", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
    articles.save(
        Article(
            ulid=PUB_ULID,
            title="Sommerfahrt",
            collection_id="PUB",
            lifecycle=Lifecycle.PUBLISHED,
            physical_location="Regal 7",
            custom=(("Bemerkung", "intern"),),
        ),
        0,
    )
    return tmp_path / "canonical"


PUB_ULID = new_ulid()


def _request(viewer: Viewer, root: Path):  # type: ignore[no-untyped-def]
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    request = RequestFactory().get(f"/artikel/{PUB_ULID}")
    request.COOKIES["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return request


def _settings(root: Path) -> dict[str, object]:
    return {"DEV_VIEWER_SIGNING_KEY": _DEV_KEY, "BUNDESARCHIV_CANONICAL_ROOT": str(root)}


def test_resolves_projected_article_and_version(root: Path) -> None:
    with override_settings(**_settings(root)):
        res = resolve_visible_detail(_request(Archivist(), root), PUB_ULID)
    assert res is not None
    assert res.article.title == "Sommerfahrt"
    assert res.version == 1  # one save (expected_version 0) increments the stored version to 1
    assert res.is_archivist is True
    # archivist sees the archivist-only fields
    assert res.article.physical_location == "Regal 7"
    assert res.article.custom == (("Bemerkung", "intern"),)


def test_member_projection_floors_archivist_only_fields(root: Path) -> None:
    with override_settings(**_settings(root)):
        res = resolve_visible_detail(_request(Member(groups=()), root), PUB_ULID)
    assert res is not None
    assert res.is_archivist is False
    # project() floored these on the domain object — they cannot reach the template
    assert res.article.physical_location is None
    assert res.article.custom == ()


def test_public_projection_floors_too(root: Path) -> None:
    with override_settings(**_settings(root)):
        res = resolve_visible_detail(_request(Public(), root), PUB_ULID)
    assert res is not None
    assert res.article.physical_location is None


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_malformed_or_absent_is_none(root: Path, ulid: str) -> None:
    with override_settings(**_settings(root)):
        assert resolve_visible_detail(_request(Archivist(), root), ulid) is None


def test_single_load(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # §8 double-load fix: the whole resolution reads the store exactly once.
    calls = {"n": 0}
    original = ArticleRepository.load

    def counting_load(self: ArticleRepository, ulid: str):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return original(self, ulid)

    # patch on the class itself (the resolver's article_auth.ArticleRepository is the same object)
    monkeypatch.setattr(ArticleRepository, "load", counting_load)
    with override_settings(**_settings(root)):
        resolve_visible_detail(_request(Archivist(), root), PUB_ULID)
    assert calls["n"] == 1
