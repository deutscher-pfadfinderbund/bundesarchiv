"""The media leak suite (Part 4.3, plan §4.10 seed) — authorized media serving via the seam.

This is the review-critical suite: it proves the classic direct-media leak is closed. Every media
and thumbnail byte is served ONLY where ``can_view`` allows, and every denial/absence is a
byte-identical 404 that leaks nothing about existence.

Structure:
- A fixture corpus of Articles across every tier (public / members / groups / draft /
  archivist-only), each carrying one real image blob, on a ``LocalFsObjectStore`` under a tmp root.
- The per-tier grid: original + thumb URLs against [Public, Member(wrong group), Member(right
  group), Archivist] -> 200 iff ``can_view`` says so, everything else 404.
- Byte-identical 404s across five distinct denial/absence reasons.
- Authz-before-existence: the blob lookup at the seam is never reached for a forbidden article.
- X-Accel mode and dev-streaming mode.
- The thumbnail job (JPEG/PNG generate, text no-op, idempotent, output location).
"""

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.core import signing
from django.test import Client, override_settings
from PIL import Image

from bundesarchiv.app.web import media as media_seam
from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-media-dev-key"

# Media serving is pure request handling against a local FS store — no Postgres. (The tests/app
# conftest already exempts the web/ subtree from SKIP_PG.)


def _png_bytes(color: tuple[int, int, int] = (200, 40, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 500), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (10, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


class _Corpus:
    """The fixture archive: a store, its canonical/thumbnail roots, and one Article per tier with a
    known media content-hash. Every Article carries exactly one image blob."""

    def __init__(self, canonical_root: Path, thumbnail_root: Path) -> None:
        self.canonical_root = canonical_root
        self.thumbnail_root = thumbnail_root
        self.store = LocalFsObjectStore(canonical_root)
        self.hash_by_tier: dict[str, str] = {}
        self.ulid_by_tier: dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        collections = CollectionRepository(self.store)
        articles = ArticleRepository(self.store)
        # ROOT (Members default) → tier collections.
        collections.save(Collection(ulid="ROOT", name="Wurzel", parent_id=None), 0)
        collections.save(Collection("PUB", "Public", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        collections.save(Collection("MEM", "Members", "ROOT", Audience(AudienceTier.MEMBERS)), 0)
        collections.save(
            Collection("GRP", "Groups", "ROOT", Audience(AudienceTier.GROUPS, ("vorstand",))), 0
        )
        # public, members, groups, draft (non-published → archivist-only via lifecycle),
        # archivist-only (draft under groups). Each blob is a DISTINCT colour so every content-hash
        # differs (the wrong-hash test needs a real hash that belongs to a different article).
        specs = [
            ("public", "PUB", Lifecycle.PUBLISHED, (200, 40, 60)),
            ("members", "MEM", Lifecycle.PUBLISHED, (40, 200, 60)),
            ("groups", "GRP", Lifecycle.PUBLISHED, (40, 60, 200)),
            ("draft", "PUB", Lifecycle.DRAFT, (200, 200, 40)),
            ("archivist", "GRP", Lifecycle.DRAFT, (200, 40, 200)),
        ]
        for tier, coll, lifecycle, color in specs:
            ulid = new_ulid()
            ref = articles.add_media(ulid, f"{tier}.png", _png_bytes(color), media_type="image/png")
            articles.save(
                Article(
                    ulid=ulid,
                    title=f"{tier} article",
                    collection_id=coll,
                    lifecycle=lifecycle,
                    media=(ref,),
                ),
                0,
            )
            self.hash_by_tier[tier] = ref.content_hash
            self.ulid_by_tier[tier] = ulid

    def url(self, tier: str, *, thumb: bool = False) -> str:
        base = f"/media/{self.ulid_by_tier[tier]}/{self.hash_by_tier[tier]}"
        return base + "/thumb" if thumb else base


@pytest.fixture
def corpus(tmp_path: Path) -> _Corpus:
    return _Corpus(tmp_path / "canonical", tmp_path / "thumbnails")


def _settings(corpus: _Corpus, **extra: object) -> dict[str, object]:
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(corpus.canonical_root),
        "BUNDESARCHIV_THUMBNAIL_ROOT": str(corpus.thumbnail_root),
        "BUNDESARCHIV_X_ACCEL_PREFIX": None,
        **extra,
    }


def _client_as(viewer: Viewer) -> Client:
    """A test client carrying a valid dev-viewer cookie for ``viewer`` (signed with the test dev
    key, exactly as the switcher would)."""
    client = Client()
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def _body(response: object) -> bytes:
    """The full response body whether streamed (FileResponse) or buffered (the 404)."""
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)  # type: ignore[attr-defined]
    content: bytes = response.content  # type: ignore[attr-defined]
    return content


# --- fixtures for the per-tier grid ----------------------------------------------

_VIEWERS: dict[str, Viewer] = {
    "public": Public(),
    "member_wrong": Member(groups=("andere",)),
    "member_right": Member(groups=("vorstand",)),
    "archivist": Archivist(),
}

# Ground truth from can_view: which (tier, viewer) pairs may see the bytes.
_ALLOWED: set[tuple[str, str]] = {
    ("public", "public"),
    ("public", "member_wrong"),
    ("public", "member_right"),
    ("public", "archivist"),
    ("members", "member_wrong"),
    ("members", "member_right"),
    ("members", "archivist"),
    ("groups", "member_right"),  # holds "vorstand"
    ("groups", "archivist"),
    ("draft", "archivist"),  # non-published → archivist-only
    ("archivist", "archivist"),
}


def _grid() -> Iterator[tuple[str, str, bool]]:
    for tier in ("public", "members", "groups", "draft", "archivist"):
        for viewer_name in _VIEWERS:
            yield tier, viewer_name, (tier, viewer_name) in _ALLOWED


@pytest.mark.parametrize(("tier", "viewer_name", "allowed"), list(_grid()))
def test_original_per_tier_grid(
    corpus: _Corpus, tier: str, viewer_name: str, allowed: bool
) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(_VIEWERS[viewer_name]).get(corpus.url(tier))
    if allowed:
        assert response.status_code == 200, f"{tier}/{viewer_name} should be served"
        assert _body(response) == corpus.store.read(
            f"articles/{corpus.ulid_by_tier[tier]}/media/{corpus.hash_by_tier[tier]}"
        )
    else:
        assert response.status_code == 404, f"{tier}/{viewer_name} must be 404"


@pytest.mark.parametrize(("tier", "viewer_name", "allowed"), list(_grid()))
def test_thumbnail_per_tier_grid(
    corpus: _Corpus, tier: str, viewer_name: str, allowed: bool
) -> None:
    # Generate every thumbnail first so a 404 for a denied viewer is authorization, not absence.
    from bundesarchiv.app import thumbnails

    for t in corpus.hash_by_tier:
        thumbnails.generate_thumbnail(corpus.store, corpus.hash_by_tier[t], corpus.thumbnail_root)
    with override_settings(**_settings(corpus)):
        response = _client_as(_VIEWERS[viewer_name]).get(corpus.url(tier, thumb=True))
    if allowed:
        assert response.status_code == 200, f"thumb {tier}/{viewer_name} should be served"
        assert response["Content-Type"] == "image/webp"
    else:
        assert response.status_code == 404, f"thumb {tier}/{viewer_name} must be 404"


# --- byte-identical 404s ----------------------------------------------------------


def _header_set(response: object) -> set[tuple[str, str]]:
    # Every header EXCEPT ones a test harness/date stamps per-response; the invariant is the app's
    # own header set, which must not vary with the 404 reason.
    volatile = {"Date", "Server", "X-Frame-Options", "Vary", "Content-Language"}
    return {(k, v) for k, v in response.items() if k not in volatile}  # type: ignore[attr-defined]


def test_byte_identical_404s_across_all_reasons(corpus: _Corpus) -> None:
    good_hash = corpus.hash_by_tier["members"]
    real_ulid = corpus.ulid_by_tier["members"]
    responses = {}
    with override_settings(**_settings(corpus)):
        # (a) nonexistent ulid (well-formed but no such article)
        responses["nonexistent_ulid"] = _client_as(Archivist()).get(
            f"/media/01BX5ZZKBKACTAV9WEVGEMMVRZ/{good_hash}"
        )
        # (b) real-but-forbidden article (members-only, Public viewer)
        responses["forbidden"] = _client_as(Public()).get(corpus.url("members"))
        # (c) valid article + wrong hash (a hash that belongs to a DIFFERENT article)
        responses["wrong_hash"] = _client_as(Archivist()).get(
            f"/media/{real_ulid}/{corpus.hash_by_tier['public']}"
        )
        # (d) malformed ulid
        responses["malformed_ulid"] = _client_as(Archivist()).get(f"/media/not-a-ulid/{good_hash}")
        # (e) missing thumbnail on a permitted article (never generated)
        responses["missing_thumb"] = _client_as(Archivist()).get(corpus.url("members", thumb=True))
    statuses = {name: r.status_code for name, r in responses.items()}
    assert set(statuses.values()) == {404}, statuses
    bodies = {name: r.content for name, r in responses.items()}
    assert len(set(bodies.values())) == 1, f"bodies differ: {bodies}"
    header_sets = {name: frozenset(_header_set(r)) for name, r in responses.items()}
    assert len(set(header_sets.values())) == 1, f"header sets differ: {header_sets}"


# --- authz-before-existence -------------------------------------------------------


def test_authz_denies_before_any_blob_lookup(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Monkeypatch the seam (the genuine boundary that touches the blob) with a recorder. A FORBIDDEN
    # request must NEVER reach it — authorization denies before existence is probed.
    reached: list[str] = []

    def recorder(*args: object, **kwargs: object) -> object:
        reached.append("media_response")
        raise AssertionError("blob lookup reached for a forbidden request")

    monkeypatch.setattr("bundesarchiv.app.web.media.media_response", recorder)
    with override_settings(**_settings(corpus)):
        response = _client_as(Public()).get(corpus.url("members"))
    assert response.status_code == 404
    assert reached == [], "the seam (blob lookup) was reached for a forbidden article"


def test_authz_denies_before_lookup_for_thumbnail(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    reached: list[str] = []

    def recorder(*args: object, **kwargs: object) -> object:
        reached.append("thumbnail_response")
        raise AssertionError("thumbnail lookup reached for a forbidden request")

    monkeypatch.setattr("bundesarchiv.app.web.media.thumbnail_response", recorder)
    with override_settings(**_settings(corpus)):
        response = _client_as(Public()).get(corpus.url("members", thumb=True))
    assert response.status_code == 404
    assert reached == []


# --- X-Accel mode -----------------------------------------------------------------


def test_x_accel_mode_permitted_carries_redirect_and_empty_body(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus, BUNDESARCHIV_X_ACCEL_PREFIX="/_protected")):
        response = _client_as(Public()).get(corpus.url("public"))
    assert response.status_code == 200
    assert response.content == b""
    ulid, chash = corpus.ulid_by_tier["public"], corpus.hash_by_tier["public"]
    assert response["X-Accel-Redirect"] == f"/_protected/articles/{ulid}/media/{chash}"
    assert response["Content-Type"] == "image/png"
    assert "inline" in response["Content-Disposition"]


def test_x_accel_mode_forbidden_is_404_with_no_redirect(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus, BUNDESARCHIV_X_ACCEL_PREFIX="/_protected")):
        response = _client_as(Public()).get(corpus.url("members"))
    assert response.status_code == 404
    assert "X-Accel-Redirect" not in response


def test_hostile_filename_cannot_inject_a_response_header(corpus: _Corpus) -> None:
    # A MediaRef filename is user-controlled (upload). The seam must encode it safely so a
    # quote/CRLF in the name cannot break out of Content-Disposition into an injected header.
    from bundesarchiv.app.web.media import media_response
    from bundesarchiv.domain.models import Article, MediaRef

    ref = MediaRef('e"vil\r\nSet-Cookie: x=1.png', corpus.hash_by_tier["public"], "image/png")
    article = Article(
        ulid=corpus.ulid_by_tier["public"], title="x", collection_id="PUB", media=(ref,)
    )
    factory_request = None  # media_response ignores request for header building
    with override_settings(**_settings(corpus, BUNDESARCHIV_X_ACCEL_PREFIX="/_protected")):
        response = media_response(article, ref, factory_request)  # type: ignore[arg-type]
    disposition = response["Content-Disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert "Set-Cookie" not in response  # no header was injected
    # The raw unescaped quote must not appear as a bare filename= value (it is RFC5987-encoded).
    assert 'filename="e"vil' not in disposition


# --- dev streaming mode -----------------------------------------------------------


def test_dev_streaming_returns_blob_bytes(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):  # no X-Accel prefix → dev FileResponse
        response = _client_as(Public()).get(corpus.url("public"))
    assert response.status_code == 200
    blob = corpus.store.read(
        f"articles/{corpus.ulid_by_tier['public']}/media/{corpus.hash_by_tier['public']}"
    )
    assert _body(response) == blob
    assert response["Content-Type"] == "image/png"


# --- the thumbnail job ------------------------------------------------------------


def test_thumbnail_job_generates_for_jpeg_and_png(tmp_path: Path) -> None:
    from bundesarchiv.app import thumbnails

    store = LocalFsObjectStore(tmp_path / "c")
    thumbs = tmp_path / "t"
    articles = ArticleRepository(store)
    png = articles.add_media("A1", "a.png", _png_bytes(), media_type="image/png")
    jpg = articles.add_media("A2", "b.jpg", _jpeg_bytes(), media_type="image/jpeg")
    for ref in (png, jpg):
        assert thumbnails.generate_thumbnail(store, ref.content_hash, thumbs) is True
        out = thumbs / f"{ref.content_hash}.webp"
        assert out.is_file()
        with Image.open(out) as im:
            assert im.format == "WEBP"
            assert max(im.size) <= 480


def test_thumbnail_job_noops_for_text_blob(tmp_path: Path) -> None:
    from bundesarchiv.app import thumbnails

    store = LocalFsObjectStore(tmp_path / "c")
    thumbs = tmp_path / "t"
    ref = ArticleRepository(store).add_media(
        "A1", "notes.txt", b"not an image at all", media_type="text/plain"
    )
    assert thumbnails.generate_thumbnail(store, ref.content_hash, thumbs) is False
    assert not (thumbs / f"{ref.content_hash}.webp").exists()


def test_thumbnail_job_noops_for_missing_blob(tmp_path: Path) -> None:
    from bundesarchiv.app import thumbnails

    store = LocalFsObjectStore(tmp_path / "c")
    assert thumbnails.generate_thumbnail(store, "0" * 64, tmp_path / "t") is False


def test_thumbnail_job_is_idempotent(tmp_path: Path) -> None:
    from bundesarchiv.app import thumbnails

    store = LocalFsObjectStore(tmp_path / "c")
    thumbs = tmp_path / "t"
    ref = ArticleRepository(store).add_media("A1", "a.png", _png_bytes(), media_type="image/png")
    thumbnails.generate_thumbnail(store, ref.content_hash, thumbs)
    first = (thumbs / f"{ref.content_hash}.webp").read_bytes()
    thumbnails.generate_thumbnail(store, ref.content_hash, thumbs)
    second = (thumbs / f"{ref.content_hash}.webp").read_bytes()
    assert first == second


# --- seam / repository key equivalence -------------------------------------------


def test_media_key_matches_repository() -> None:
    # The seam owns its own store-relative key scheme; pin it equal to the repository's so a layout
    # change in one can't silently diverge the other (the bytes would 404).
    from bundesarchiv.persistence.repository import _media_key

    assert media_seam.blob_key("ULID", "abc123") == _media_key("ULID", "abc123")
