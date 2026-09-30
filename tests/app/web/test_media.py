"""The media leak suite (Part 4.3, plan §4.10 seed) — authorized media serving via the seam.

This is the review-critical suite: it proves the classic direct-media leak is closed. Every media
and thumbnail byte is served ONLY where ``can_view`` allows, and every denial/absence is a plain
404 that leaks nothing about existence (the byte-identical-404 law was relaxed by the owner,
2026-08 — a deny is its status code, with no leaked content).

Structure:
- A fixture corpus of Articles across every tier (public / members / groups / draft /
  archivist-only), each carrying one real image blob, on a ``LocalFsObjectStore`` under a tmp root.
- The per-tier grid: original + thumb URLs against [Public, Member(wrong group), Member(right
  group), Archivist] -> 200 iff ``can_view`` says so, everything else 404.
- A 404 for each of five distinct denial/absence reasons.
- Authz-before-existence: a forbidden request is denied before any blob or thumbnail probe.
- X-Accel mode and dev-streaming mode.
- The thumbnail job (JPEG/PNG generate, text no-op, idempotent, output location).
"""

import io
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from django.test import override_settings
from PIL import Image
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    Corpus,
    KeyRecordingStore,
    client_as,
    make_article,
    make_collection,
)

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Lifecycle, MediaRef
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

# Media serving is pure request handling against a local FS store — no Postgres.


def _png_bytes(color: tuple[int, int, int] = (200, 40, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 500), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (10, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


class _TierCorpus:
    """The fixture archive over a shared ``Corpus``: one Article per tier with a known media
    content-hash, plus the thumbnail root the seam serves its derived cache from. Every Article
    carries exactly one image blob. The frozen standard corpus is PUBLIC and media-free, so the
    tier grid builds its own content."""

    def __init__(self, base: Corpus, thumbnail_root: Path) -> None:
        self.thumbnail_root = thumbnail_root
        self.store = base.store
        self.articles = base.articles
        self.hash_by_tier: dict[str, str] = {}
        self.ulid_by_tier: dict[str, str] = {}
        self.ref_by_tier: dict[str, MediaRef] = {}
        self._build(base)

    def _build(self, base: Corpus) -> None:
        # ROOT (Members default, saved by ``Corpus``) → tier collections.
        base.add_collection(
            make_collection("PUB", "Public", audience=Audience(AudienceTier.PUBLIC))
        )
        base.add_collection(
            make_collection("MEM", "Members", audience=Audience(AudienceTier.MEMBERS))
        )
        base.add_collection(
            make_collection("GRP", "Groups", audience=Audience(AudienceTier.GROUPS, ("vorstand",)))
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
            ref = base.articles.add_media(
                ulid, f"{tier}.png", io.BytesIO(_png_bytes(color)), media_type="image/png"
            )
            base.add_article(
                make_article(
                    ulid,
                    collection_id=coll,
                    lifecycle=lifecycle,
                    title=f"{tier} article",
                    media=(ref,),
                )
            )
            self.hash_by_tier[tier] = ref.content_hash
            self.ulid_by_tier[tier] = ulid
            self.ref_by_tier[tier] = ref

    def url(self, tier: str, *, thumb: bool = False) -> str:
        base = f"/media/{self.ulid_by_tier[tier]}/{self.hash_by_tier[tier]}"
        return base + "/thumb" if thumb else base

    def blob_key(self, tier: str) -> str:
        """This tier's file key, from the repository that owns the layout — a byte comparison
        proves the right bytes, never the key scheme (which the X-Accel test pins verbatim)."""
        return self.articles.media_key(self.ulid_by_tier[tier], self.ref_by_tier[tier])

    def generate_thumbnails(self) -> None:
        from bundesarchiv.app import thumbnails

        for tier, ulid in self.ulid_by_tier.items():
            thumbnails.generate_thumbnail(
                self.store, ulid, self.hash_by_tier[tier], self.thumbnail_root
            )


@pytest.fixture
def corpus(make_corpus: Callable[[], Corpus], tmp_path: Path) -> Iterator[_TierCorpus]:
    """The tier archive — this module's ``corpus``, deliberately in place of the frozen standard one.

    The two settings ``settings_for`` does not carry stay here: the thumbnail root and the X-Accel
    prefix (``None`` = Django streams the bytes, so the probes read a body). Build BEFORE entering
    the override — ``make_corpus`` enters a settings context of its own that tears down last, so
    this one has to nest inside it to unwind in order.
    """
    thumbnail_root = tmp_path / "thumbnails"
    built = _TierCorpus(make_corpus(), thumbnail_root)
    with override_settings(
        BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbnail_root), BUNDESARCHIV_X_ACCEL_PREFIX=None
    ):
        yield built


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
    corpus: _TierCorpus, tier: str, viewer_name: str, allowed: bool
) -> None:
    response = client_as(_VIEWERS[viewer_name]).get(corpus.url(tier))
    if allowed:
        assert response.status_code == 200, f"{tier}/{viewer_name} should be served"
        assert _body(response) == corpus.store.read(corpus.blob_key(tier))
    else:
        assert_denied(response, f"{tier}/{viewer_name}")


@pytest.mark.parametrize(("tier", "viewer_name", "allowed"), list(_grid()))
def test_thumbnail_per_tier_grid(
    corpus: _TierCorpus, tier: str, viewer_name: str, allowed: bool
) -> None:
    # Generate every thumbnail first so a 404 for a denied viewer is authorization, not absence.
    corpus.generate_thumbnails()
    response = client_as(_VIEWERS[viewer_name]).get(corpus.url(tier, thumb=True))
    if allowed:
        assert response.status_code == 200, f"thumb {tier}/{viewer_name} should be served"
        assert response["Content-Type"] == "image/webp"
    else:
        assert_denied(response, f"thumb {tier}/{viewer_name}")


# --- 404 across every deny reason ---------------------------------------------------


def test_404_across_all_deny_reasons(corpus: _TierCorpus) -> None:
    good_hash = corpus.hash_by_tier["members"]
    real_ulid = corpus.ulid_by_tier["members"]
    responses = {
        "nonexistent_ulid": client_as(Archivist()).get(
            f"/media/01BX5ZZKBKACTAV9WEVGEMMVRZ/{good_hash}"
        ),
        "forbidden": client_as(Public()).get(corpus.url("members")),
        # a hash that belongs to a DIFFERENT article
        "wrong_hash": client_as(Archivist()).get(
            f"/media/{real_ulid}/{corpus.hash_by_tier['public']}"
        ),
        "malformed_ulid": client_as(Archivist()).get(f"/media/not-a-ulid/{good_hash}"),
        "missing_thumb": client_as(Archivist()).get(corpus.url("members", thumb=True)),
    }
    for reason, response in responses.items():
        assert_denied(response, reason)


# --- authz-before-existence -------------------------------------------------------


class _WatchedRoot:
    """A thumbnail root that records each time a path is built from it."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.touched = 0

    def __fspath__(self) -> str:
        self.touched += 1
        return str(self._root)


def test_authz_denies_before_any_blob_lookup(
    corpus: _TierCorpus, recording_store: KeyRecordingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    reached: list[str] = []

    def recorder(*args: object, **kwargs: object) -> object:
        reached.append("media_response")
        raise AssertionError("blob lookup reached for a forbidden request")

    monkeypatch.setattr("bundesarchiv.app.web.media.media_response", recorder)
    response = client_as(Public()).get(corpus.url("members"))
    assert_denied(response)
    assert reached == [], "the seam was reached for a forbidden article"
    assert recording_store.keys, "the recording store saw no call; the article was never loaded"
    assert corpus.blob_key("members") not in recording_store.keys, "the blob was probed first"


def test_authz_denies_before_lookup_for_thumbnail(
    corpus: _TierCorpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus.generate_thumbnails()
    root = _WatchedRoot(corpus.thumbnail_root)
    reached: list[str] = []

    def recorder(*args: object, **kwargs: object) -> object:
        reached.append("thumbnail_response")
        raise AssertionError("thumbnail lookup reached for a forbidden request")

    monkeypatch.setattr("bundesarchiv.app.web.media.thumbnail_response", recorder)
    with override_settings(BUNDESARCHIV_THUMBNAIL_ROOT=root):
        response = client_as(Public()).get(corpus.url("members", thumb=True))
    assert_denied(response)
    assert reached == []
    assert root.touched == 0, "the thumbnail cache was probed before the deny"


# --- X-Accel mode -----------------------------------------------------------------


def test_x_accel_mode_permitted_carries_redirect_and_empty_body(corpus: _TierCorpus) -> None:
    with override_settings(BUNDESARCHIV_X_ACCEL_PREFIX="/_protected"):
        response = client_as(Public()).get(corpus.url("public"))
    assert response.status_code == 200
    assert response.content == b""
    # Spelled out, not derived: this header is the contract with nginx's `internal;` location, so a
    # silent layout change under it must fail HERE rather than agree with itself.
    ulid = corpus.ulid_by_tier["public"]
    assert response["X-Accel-Redirect"] == f"/_protected/articles/{ulid}/media/public.png"
    assert response["Content-Type"] == "image/png"
    assert "inline" in response["Content-Disposition"]


def test_x_accel_redirect_percent_encodes_the_named_file(corpus: _TierCorpus) -> None:
    # nginx decodes the header as a URI (ADR 0019), so a raw "%41" would name another file.
    ulid = new_ulid()
    ref = corpus.articles.add_media(ulid, "Grüße 100%41.png", io.BytesIO(_png_bytes()), "image/png")
    corpus.articles.save(
        Article(ulid, "Umlaute", "PUB", lifecycle=Lifecycle.PUBLISHED, media=(ref,)),
        0,
        changed_by="tester",
    )
    with override_settings(BUNDESARCHIV_X_ACCEL_PREFIX="/_protected"):
        response = client_as(Public()).get(f"/media/{ulid}/{ref.content_hash}")
    assert response["X-Accel-Redirect"] == (
        f"/_protected/articles/{ulid}/media/Gr%C3%BC%C3%9Fe%20100%2541.png"
    )


def test_x_accel_mode_forbidden_is_404_with_no_redirect(corpus: _TierCorpus) -> None:
    with override_settings(BUNDESARCHIV_X_ACCEL_PREFIX="/_protected"):
        response = client_as(Public()).get(corpus.url("members"))
    assert_denied(response)
    assert "X-Accel-Redirect" not in response


def test_hostile_filename_cannot_inject_a_response_header(corpus: _TierCorpus) -> None:
    # A MediaRef filename is user-controlled (upload). The seam must encode it safely so a
    # quote/CRLF in the name cannot break out of Content-Disposition into an injected header.
    from bundesarchiv.app.web.media import media_response
    from bundesarchiv.domain.models import Article, MediaRef

    ref = MediaRef('e"vil\r\nSet-Cookie: x=1.png', corpus.hash_by_tier["public"], "image/png")
    article = Article(
        ulid=corpus.ulid_by_tier["public"], title="x", collection_id="PUB", media=(ref,)
    )
    factory_request = None  # media_response ignores request for header building
    with override_settings(BUNDESARCHIV_X_ACCEL_PREFIX="/_protected"):
        response = media_response(
            Archive.of(corpus.store),
            article,
            ref,
            factory_request,  # type: ignore[arg-type]
        )
    disposition = response["Content-Disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert "Set-Cookie" not in response  # no header was injected
    # The raw unescaped quote must not appear as a bare filename= value (it is RFC5987-encoded).
    assert 'filename="e"vil' not in disposition


# --- dev streaming mode -----------------------------------------------------------


def test_dev_streaming_returns_blob_bytes(corpus: _TierCorpus) -> None:
    # the fixture leaves BUNDESARCHIV_X_ACCEL_PREFIX at None → dev FileResponse
    response = client_as(Public()).get(corpus.url("public"))
    assert response.status_code == 200
    assert _body(response) == corpus.store.read(corpus.blob_key("public"))
    assert response["Content-Type"] == "image/png"


def test_permitted_but_absent_blob_is_the_same_404(corpus: _TierCorpus) -> None:
    # Past the auth gate the bytes can still be gone (not yet mirrored, pruned, hand-deleted).
    # Absence must surface as the SAME plain 404 as a denial — never a 500 that says "this
    # article exists and you may see it, but the file is missing".
    corpus.store.delete(corpus.blob_key("public"))
    assert_denied(client_as(Public()).get(corpus.url("public")))


# --- cache policy on gated bytes (ADR 0017) ---------------------------------------

#: Spelled out, not imported from the seam, so a weakened directive fails HERE.
_EXPECTED_CACHE_CONTROL = "private, max-age=31536000, immutable"


@pytest.mark.parametrize("x_accel_prefix", [None, "/_protected"], ids=["dev_stream", "x_accel"])
def test_permitted_media_is_privately_cacheable_forever(
    corpus: _TierCorpus, x_accel_prefix: str | None
) -> None:
    with override_settings(BUNDESARCHIV_X_ACCEL_PREFIX=x_accel_prefix):
        response = client_as(Public()).get(corpus.url("public"))
    assert response.status_code == 200
    assert response["Cache-Control"] == _EXPECTED_CACHE_CONTROL


def test_permitted_thumbnail_is_privately_cacheable_forever(corpus: _TierCorpus) -> None:
    corpus.generate_thumbnails()
    response = client_as(Public()).get(corpus.url("public", thumb=True))
    assert response.status_code == 200
    assert response["Cache-Control"] == _EXPECTED_CACHE_CONTROL


@pytest.mark.parametrize("x_accel_prefix", [None, "/_protected"], ids=["dev_stream", "x_accel"])
def test_permitted_media_runs_no_script(corpus: _TierCorpus, x_accel_prefix: str | None) -> None:
    # An uploaded SVG or HTML file opened directly is a document on the archive's origin; the
    # sandbox keeps its scripts off and gives it an opaque origin (no cookies, no CSRF token).
    with override_settings(BUNDESARCHIV_X_ACCEL_PREFIX=x_accel_prefix):
        response = client_as(Public()).get(corpus.url("public"))
    assert response.status_code == 200
    assert response["Content-Security-Policy"] == "sandbox"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_permitted_thumbnail_runs_no_script(corpus: _TierCorpus) -> None:
    corpus.generate_thumbnails()
    response = client_as(Public()).get(corpus.url("public", thumb=True))
    assert response.status_code == 200
    assert response["Content-Security-Policy"] == "sandbox"


@pytest.mark.parametrize("thumb", [False, True], ids=["original", "thumbnail"])
def test_permitted_media_is_not_readable_by_another_site(corpus: _TierCorpus, thumb: bool) -> None:
    # A page on a sibling DPB host is same-site, so its image requests carry the token cookies.
    corpus.generate_thumbnails()
    response = client_as(Public()).get(corpus.url("public", thumb=thumb))
    assert response.status_code == 200
    assert response["Cross-Origin-Resource-Policy"] == "same-origin"


def test_the_media_sidecar_sandboxes_what_it_serves() -> None:
    # On an X-Accel redirect nginx drops the app's CSP, nosniff and CORP headers, so the sidecar's
    # internal location must add them itself, and must not replace the app's Cache-Control.
    conf = (Path(__file__).parents[3] / "deploy/nginx/nginx.conf").read_text()
    media_location = conf.split("alias /canonical/", 1)[1].split("}", 1)[0]
    assert 'add_header Content-Security-Policy "sandbox" always;' in media_location
    assert 'add_header X-Content-Type-Options "nosniff" always;' in media_location
    assert 'add_header Cross-Origin-Resource-Policy "same-origin" always;' in media_location
    assert "disable_symlinks on;" in media_location
    assert "expires" not in media_location
    assert "Cache-Control" not in media_location


def test_deny_is_never_cached(corpus: _TierCorpus) -> None:
    # Caching a deny would pin a viewer to a 404 for a year after their access is granted.
    forbidden = client_as(Public()).get(corpus.url("members"))
    missing_thumb = client_as(Archivist()).get(corpus.url("members", thumb=True))
    for name, response in (("forbidden", forbidden), ("missing_thumb", missing_thumb)):
        assert_denied(response, name)
        assert "Cache-Control" not in response, name


# --- the thumbnail job ------------------------------------------------------------


def _saved(articles: ArticleRepository, ulid: str, *refs: MediaRef) -> None:
    articles.save(Article(ulid, "Bilder", "PUB", media=refs), 0, changed_by="tester")


def test_thumbnail_job_generates_for_jpeg_and_png(tmp_path: Path) -> None:
    from bundesarchiv.app import thumbnails

    store = LocalFsObjectStore(tmp_path / "c")
    thumbs = tmp_path / "t"
    articles = ArticleRepository(store)
    png = articles.add_media("A1", "a.png", io.BytesIO(_png_bytes()), media_type="image/png")
    jpg = articles.add_media("A1", "b.jpg", io.BytesIO(_jpeg_bytes()), media_type="image/jpeg")
    _saved(articles, "A1", png, jpg)
    for ref in (png, jpg):
        assert thumbnails.generate_thumbnail(store, "A1", ref.content_hash, thumbs) is True
        out = thumbnails.thumbnail_path(thumbs, ref.content_hash)
        assert out.is_file()
        with Image.open(out) as im:
            assert im.format == "WEBP"
            assert max(im.size) <= 480


def test_thumbnail_job_noops_for_text_file(tmp_path: Path) -> None:
    from bundesarchiv.app import thumbnails

    store = LocalFsObjectStore(tmp_path / "c")
    thumbs = tmp_path / "t"
    articles = ArticleRepository(store)
    ref = articles.add_media(
        "A1", "notes.txt", io.BytesIO(b"not an image at all"), media_type="text/plain"
    )
    _saved(articles, "A1", ref)
    assert thumbnails.generate_thumbnail(store, "A1", ref.content_hash, thumbs) is False
    assert not thumbnails.thumbnail_path(thumbs, ref.content_hash).exists()


def test_thumbnail_job_noops_for_a_file_not_on_the_article(tmp_path: Path) -> None:
    from bundesarchiv.app import thumbnails

    store = LocalFsObjectStore(tmp_path / "c")
    articles = ArticleRepository(store)
    dropped = articles.add_media("A1", "a.png", io.BytesIO(_png_bytes()), media_type="image/png")
    _saved(articles, "A1")
    for ulid, content_hash in (("A1", dropped.content_hash), ("A2", dropped.content_hash)):
        assert thumbnails.generate_thumbnail(store, ulid, content_hash, tmp_path / "t") is False


def test_thumbnail_job_is_idempotent(tmp_path: Path) -> None:
    from bundesarchiv.app import thumbnails

    store = LocalFsObjectStore(tmp_path / "c")
    thumbs = tmp_path / "t"
    articles = ArticleRepository(store)
    ref = articles.add_media("A1", "a.png", io.BytesIO(_png_bytes()), media_type="image/png")
    _saved(articles, "A1", ref)
    thumbnails.generate_thumbnail(store, "A1", ref.content_hash, thumbs)
    first = thumbnails.thumbnail_path(thumbs, ref.content_hash).read_bytes()
    thumbnails.generate_thumbnail(store, "A1", ref.content_hash, thumbs)
    second = thumbnails.thumbnail_path(thumbs, ref.content_hash).read_bytes()
    assert first == second
