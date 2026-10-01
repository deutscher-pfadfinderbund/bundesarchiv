"""The 4.6 detail resolver (`resolve_visible_detail`, spec §8) — ONE load feeding the render
view-model.

`resolve_visible_article` (the pane's path) returns only a projected Article; the detail view also
needs the Bestand chain and the is_archivist presentation gate, so `resolve_visible_detail` loads ONCE
and returns a `DetailResolution` carrying all three. These tests pin the projection (archivist-only
fields floored for members).
"""

from collections.abc import Callable

import pytest
from django.core import signing
from django.test import RequestFactory
from tests.app.web._fixtures import DEV_KEY, PUB, Corpus, make_article, make_collection

from bundesarchiv.app.web.article_auth import resolve_visible_detail
from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

PUB_ULID = new_ulid()


@pytest.fixture
def archive(make_corpus: Callable[[], Corpus]) -> Corpus:
    """An archive whose one published article carries BOTH archivist-only fields, so the
    projection has something to floor."""
    corpus = make_corpus()
    corpus.add_collection(
        make_collection(PUB, "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    corpus.add_article(
        make_article(
            PUB_ULID,
            title="Sommerfahrt",
            physical_location="Regal 7",
            custom=(("Bemerkung", "intern"),),
        )
    )
    return corpus


def _request(viewer: Viewer):  # type: ignore[no-untyped-def]
    signer = signing.TimestampSigner(key=DEV_KEY, salt=_DEV_VIEWER_SALT)
    request = RequestFactory().get(f"/articles/{PUB_ULID}")
    request.COOKIES["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return request


def test_resolves_the_projected_article(archive: Corpus) -> None:
    res = resolve_visible_detail(_request(Archivist()), PUB_ULID)
    assert res is not None
    assert res.article.title == "Sommerfahrt"
    assert res.is_archivist is True
    # archivist sees the archivist-only fields
    assert res.article.physical_location == "Regal 7"
    assert res.article.custom == (("Bemerkung", "intern"),)


def test_member_projection_floors_archivist_only_fields(archive: Corpus) -> None:
    res = resolve_visible_detail(_request(Member(groups=())), PUB_ULID)
    assert res is not None
    assert res.is_archivist is False
    # project() floored these on the domain object — they cannot reach the template
    assert res.article.physical_location is None
    assert res.article.custom == ()


def test_public_projection_floors_too(archive: Corpus) -> None:
    res = resolve_visible_detail(_request(Public()), PUB_ULID)
    assert res is not None
    assert res.article.physical_location is None


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_malformed_or_absent_is_none(archive: Corpus, ulid: str) -> None:
    assert resolve_visible_detail(_request(Archivist()), ulid) is None
