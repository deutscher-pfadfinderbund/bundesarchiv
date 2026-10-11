"""The route x tier leak matrix, gated exhaustive against the prod urlconf. ``/static/*`` is
WhiteNoise's (ADR 0016), outside the urlconf."""

import io
from collections import defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from django.test import override_settings
from django.urls import Resolver404, URLPattern, get_resolver, resolve
from PIL import Image
from tests.app.web._asserts import assert_denied, assert_door
from tests.app.web._fixtures import ROOT, Corpus, client_as, make_article, make_collection

from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

_PROD_URLCONF = "bundesarchiv.app.web.urls"
_DEV_URLCONF = "bundesarchiv.app.web.dev_urls"


# --- the corpus: real articles + collections + one media blob, across every tier -----------------


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(buf, format="PNG")
    return buf.getvalue()


# Real ULIDs: ``collection_edit`` validates the ulid in-view (a literal like "GRP" would 404 as
# malformed), and the article routes do the same.
_COLLECTION = "01M553AGABD8F8ZVQV43GRE7TN"
_ARTICLE = "01M553AGABD8F8ZVQV43GRE7TP"
_MARKED = "01M553AGABD8F8ZVQV43GRE7TQ"


def _fill(base: Corpus) -> None:
    """The matrix's own content: the frozen standard corpus is PUBLIC and media-free."""
    base.add_collection(
        make_collection(_COLLECTION, "Gruppen", ROOT, Audience(AudienceTier.GROUPS, ("vorstand",)))
    )
    ref = base.articles.add_media(
        _ARTICLE, "cover.png", io.BytesIO(_png_bytes((30, 60, 90))), media_type="image/png"
    )
    base.add_article(
        make_article(
            _ARTICLE,
            collection_id=_COLLECTION,
            lifecycle=Lifecycle.PUBLISHED,
            title="Matrix Artikel",
            media=(ref,),
        )
    )
    # A Public article in the Papierkorb (ADR 0022): every tier would see it but for the mark.
    marked_ref = base.articles.add_media(
        _MARKED, "cover.png", io.BytesIO(_png_bytes((90, 60, 30))), media_type="image/png"
    )
    marked = make_article(
        _MARKED,
        collection_id=_COLLECTION,
        audience=Audience(AudienceTier.PUBLIC),
        media=(marked_ref,),
    )
    base.articles.mark_deleted(marked, base.add_article(marked), changed_by="tester")


class _MatrixCorpus:
    """The ``_fill`` content of ``base``, read back."""

    collection_ulid = _COLLECTION
    article_ulid = _ARTICLE
    marked_ulid = _MARKED

    def __init__(self, base: Corpus) -> None:
        self.base = base
        article = base.articles.load(_ARTICLE)
        self.content_hash = article.article.media[0].content_hash
        self.article_version = article.version
        marked = base.articles.load(_MARKED)
        self.marked_hash = marked.article.media[0].content_hash
        self.marked_version = marked.version


@pytest.fixture
def matrix_corpus(
    copy_of: Callable[[Callable[[Corpus], None]], Corpus], tmp_path: Path
) -> Iterator[_MatrixCorpus]:
    # The two settings ``settings_for`` does not carry stay local: the thumbnail root (per-test tmp
    # dir) and the X-Accel prefix (None = Django serves the bytes, so the media probes read a body).
    # No version is generated here: an allowed probe of a version route derives it on the miss.
    # Build BEFORE entering the override — ``make_corpus`` enters a settings context of its own that
    # tears down last, so this one has to nest inside it to unwind in order.
    thumbnail_root = tmp_path / "thumbnails"
    built = _MatrixCorpus(copy_of(_fill))
    with override_settings(
        BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbnail_root), BUNDESARCHIV_X_ACCEL_PREFIX=None
    ):
        yield built


# --- the tiers under test -------------------------------------------------------------------------

#: ``anonymous`` = a client with NO cookie at all (viewer_of floors to Public); ``public`` = a
#: client carrying a valid signed Public cookie. Both must behave identically (the seam floors any
#: bad/absent cookie to Public), so including both proves the floor is not accidentally cookie-gated.
_TIERS: dict[str, Viewer | None] = {
    "anonymous": None,
    "public": Public(),
    "member": Member(groups=()),
    "member_matching": Member(groups=("vorstand",)),
    "archivist": Archivist(),
}

#: The tiers that are NOT the trusted Archivist — every catalog/collection/bulk write route denies
#: all of these with a 404, and the media/detail routes deny all but the matching-group Member on
#: the GROUPS-tier corpus article.
_NON_ARCHIVIST = ("anonymous", "public", "member", "member_matching")


# --- the contract: expected status per route x method, and how to reach each -----------------------

FOUR_OH_FOUR = 404
OK = 200
NO_CONTENT = 204
REDIRECT = 302
ALIAS_PREFIX = "alias-"


class Route:
    """One route's leak contract."""

    def __init__(
        self,
        *,
        build_path: Callable[[_MatrixCorpus], str],
        get_nonarch: int | None,
        get_arch: int | None,
        post_nonarch: int | None,
        post_arch: int | None,
        post_data: dict[str, object] | None = None,
        tier_sensitive: bool = False,
        member_route: bool = False,
        stub_search: bool = False,
    ) -> None:
        self.build_path = build_path
        self.get_nonarch = get_nonarch
        self.get_arch = get_arch
        self.post_nonarch = post_nonarch
        self.post_arch = post_arch
        self.post_data = post_data or {}
        # tier_sensitive: a read route where the matching-group Member is ALLOWED (media/detail).
        self.tier_sensitive = tier_sensitive
        # member_route: every Member is allowed like the Archivist; Public and anonymous are not.
        self.member_route = member_route
        self.stub_search = stub_search


def _p_root(_c: _MatrixCorpus) -> str:
    return "/"


def _p_list(_c: _MatrixCorpus) -> str:
    return "/articles"


def _p_columns(_c: _MatrixCorpus) -> str:
    return "/columns"


def _p_trash(_c: _MatrixCorpus) -> str:
    return "/trash"


def _p_login(_c: _MatrixCorpus) -> str:
    return "/login"


def _p_oidc_callback(_c: _MatrixCorpus) -> str:
    return "/oidc/callback"


def _p_logout(_c: _MatrixCorpus) -> str:
    return "/logout"


def _p_new_article(_c: _MatrixCorpus) -> str:
    return "/articles/new"


def _p_new_collection(_c: _MatrixCorpus) -> str:
    return "/collections/new"


def _p_collection_edit(c: _MatrixCorpus) -> str:
    return f"/collections/{c.collection_ulid}/edit"


def _p_bulk_doctype(_c: _MatrixCorpus) -> str:
    return "/articles/bulk-edit/document-types"


def _p_bulk(_c: _MatrixCorpus) -> str:
    return "/articles/bulk-edit"


def _p_edit(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/edit"


def _p_copy(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/copy"


def _p_delete(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/delete"


def _p_delete_permanently(c: _MatrixCorpus) -> str:
    return f"/articles/{c.marked_ulid}/delete-permanently"


def _p_restore(c: _MatrixCorpus) -> str:
    return f"/articles/{c.marked_ulid}/restore"


def _p_publish(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/publish"


def _p_media_move(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/media/move"


def _p_media_remove(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/media/remove"


def _p_media_upload(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/media/upload"


def _p_upload_gate(c: _MatrixCorpus) -> str:
    return f"/upload-gate/{c.article_ulid}"


def _p_document_types(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/document-types"


def _p_tag_suggestions(_c: _MatrixCorpus) -> str:
    return "/tags/suggestions"


def _p_suggestions(_c: _MatrixCorpus) -> str:
    return "/suggestions"


def _p_detail(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}"


def _p_media(c: _MatrixCorpus) -> str:
    return f"/media/{c.article_ulid}/{c.content_hash}"


def _p_media_thumb(c: _MatrixCorpus) -> str:
    return f"/media/{c.article_ulid}/{c.content_hash}/thumb"


def _p_media_display(c: _MatrixCorpus) -> str:
    return f"/media/{c.article_ulid}/{c.content_hash}/display"


_CONTRACT: dict[str, Route] = {
    # Open pages.
    "start": Route(
        build_path=_p_root,
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
        stub_search=True,
    ),
    "workbench": Route(
        build_path=_p_list,
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
        stub_search=True,
    ),
    # The "Spalten …" choice: a viewer's own preference, kept in a cookie — every tier may make it
    # (302 back to the list), and GET is the plain 404. It reads and writes no record.
    "columns": Route(
        build_path=_p_columns,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,
        post_nonarch=REDIRECT,
        post_arch=REDIRECT,
    ),
    # The Papierkorb (ADR 0022): the Archivist's alone, GET only. Its rows come from search(), whose
    # Papierkorb scoping is test_leaks_trash.py's; here the gate.
    "trash": Route(
        build_path=_p_trash,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,
        stub_search=True,
    ),
    # The login surface (ADR 0018) with NO realm configured — the deploy-misconfiguration case, which
    # is what these settings are. ``/login`` and the callback fall closed to the shared 404 (no
    # signing key, no realm, no state cookie); their configured behaviour is test_auth_views.py's.
    # ``/logout`` is the deliberate exception: signing somebody OUT may not fail closed, so it
    # answers every tier the same 302 (cookie cleared, land on the workbench).
    "login": Route(
        build_path=_p_login,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,
    ),
    "oidc-callback": Route(
        build_path=_p_oidc_callback,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,
    ),
    "logout": Route(
        build_path=_p_logout,
        get_nonarch=FOUR_OH_FOUR,  # GET disallowed
        get_arch=FOUR_OH_FOUR,
        post_nonarch=REDIRECT,
        post_arch=REDIRECT,
    ),
    # Archivist-only cataloging/collection routes — every non-archivist gets a 404 on BOTH methods;
    # the archivist status depends on the route's own method contract.
    "article-create": Route(
        build_path=_p_new_article,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # empty POST → validation re-render (200)
    ),
    "collection-create": Route(
        build_path=_p_new_collection,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,  # empty POST names no Sichtbarkeit (catalog.audience_choice)
    ),
    "collection-edit": Route(
        build_path=_p_collection_edit,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # blank-name POST → error re-render (200)
    ),
    "article-edit": Route(
        build_path=_p_edit,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # invalid POST → validation re-render (200)
    ),
    "article-copy": Route(
        build_path=_p_copy,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed → 404 even for archivist
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # copy → 302 to the copy's edit form
    ),
    "article-delete": Route(
        build_path=_p_delete,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,  # GET = confirm page
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # confirmed delete → 302 to /
        post_data=None,  # filled at probe time (the confirm's version) — see _POST_DATA_BUILDERS
    ),
    # The Papierkorb's two routes, probed on the marked article (ADR 0022).
    "article-delete-permanently": Route(
        build_path=_p_delete_permanently,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,  # GET = confirm page
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # deleted for good → 302 to the Papierkorb
    ),
    "article-restore": Route(
        build_path=_p_restore,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # restored → 302 to its page
    ),
    "article-publish": Route(
        build_path=_p_publish,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # the corpus article is published: refused, back to its page
    ),
    "article-media-move": Route(
        build_path=_p_media_move,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # re-render edit form
    ),
    "article-media-remove": Route(
        build_path=_p_media_remove,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # confirm step / re-render
    ),
    "article-media-upload": Route(
        build_path=_p_media_upload,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # re-render edit form
    ),
    # nginx's auth_request for the upload route: tells nobody but an Archivist anything.
    "upload-gate": Route(
        build_path=_p_upload_gate,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=NO_CONTENT,  # the upload may proceed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,  # POST disallowed
    ),
    "article-document-types": Route(
        build_path=_p_document_types,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,  # options partial
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,  # POST disallowed
    ),
    # The Schlagwort suggestions: counts across every Article, so the Archivist's alone. No ``q``,
    # so the probe never reaches the index; the ranking is tests/index/test_tag_suggestions.py's.
    "tag-suggestions": Route(
        build_path=_p_tag_suggestions,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,  # POST disallowed
    ),
    # The search field's suggestions: a member route. No ``q``, so the probe never reaches the
    # index; what each tier is offered is tests/index/test_leaks_suggestions.py's.
    "suggestions": Route(
        build_path=_p_suggestions,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,  # POST disallowed
        member_route=True,
    ),
    "article-bulk-edit": Route(
        build_path=_p_bulk,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # confirm page for a real selection + field
        post_data=None,  # filled at probe time (needs the corpus ulid) — see _bulk_post_data
    ),
    "article-bulk-edit-document-types": Route(
        build_path=_p_bulk_doctype,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,  # ULID-free options partial
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,  # POST disallowed
    ),
    # Read routes — group-sensitive. Non-matching tiers get a 404; the matching-group Member and
    # Archivist get 200. Method-blind (POST runs the GET path).
    "article-detail": Route(
        build_path=_p_detail,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,
        tier_sensitive=True,
    ),
    "media": Route(
        build_path=_p_media,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,
        tier_sensitive=True,
    ),
    "media-thumb": Route(
        build_path=_p_media_thumb,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,
        tier_sensitive=True,
    ),
    "media-display": Route(
        build_path=_p_media_display,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,
        tier_sensitive=True,
    ),
}


def _bulk_post_data(c: _MatrixCorpus) -> dict[str, object]:
    """A valid confirm-phase bulk POST: one real ulid selected + a field + its value → the confirm
    page (200) for an archivist. Non-archivists never reach validation (gate denies first)."""
    return {"selection": [c.article_ulid], "field": "creator", "value_creator": "Jemand"}


def _delete_post_data(c: _MatrixCorpus) -> dict[str, object]:
    """The confirm as its page hands it out: against the article's current version."""
    return {"expected_version": str(c.article_version)}


def _marked_post_data(c: _MatrixCorpus) -> dict[str, object]:
    return {"expected_version": str(c.marked_version)}


def _empty_search_page() -> object:
    from bundesarchiv.index.query import SearchPage

    return SearchPage(hits=(), total=0, facets={}, dateless_count=0)


def _expected_for(route: Route, tier: str, method: str) -> int | None:
    is_arch = tier == "archivist"
    if route.tier_sensitive and tier == "member_matching":
        is_arch = True  # a matching-group Member sees the GROUPS-tier corpus article
    if route.member_route and tier in ("member", "member_matching"):
        is_arch = True
    if method == "GET":
        return route.get_arch if is_arch else route.get_nonarch
    return route.post_arch if is_arch else route.post_nonarch


# --- the matrix -----------------------------------------------------------------------------------


def _tier_invariant(route: Route) -> bool:
    statuses = {route.get_nonarch, route.get_arch, route.post_nonarch, route.post_arch}
    return len(statuses) == 1 and not route.tier_sensitive and not route.member_route


def _matrix_cases() -> Iterator[tuple[str, str, str]]:
    for name, route in _CONTRACT.items():
        if _tier_invariant(route):
            # One probe (Public GET) — the routes stay in _CONTRACT so the exhaustiveness gate
            # still covers them.
            yield name, "public", "GET"
            continue
        for tier in _TIERS:
            for method in ("GET", "POST"):
                yield name, tier, method


#: Routes whose POST payload needs the corpus (a real ulid / version), filled at probe time.
_POST_DATA_BUILDERS = {
    "article-bulk-edit": _bulk_post_data,
    "article-delete": _delete_post_data,
    "article-delete-permanently": _marked_post_data,
    "article-restore": _marked_post_data,
}


@pytest.mark.parametrize(("name", "tier", "method"), list(_matrix_cases()))
def test_route_tier_matrix(
    matrix_corpus: _MatrixCorpus, monkeypatch: pytest.MonkeyPatch, name: str, tier: str, method: str
) -> None:
    route = _CONTRACT[name]
    expected = _expected_for(route, tier, method)
    path = route.build_path(matrix_corpus)
    data: dict[str, object] = route.post_data
    if name in _POST_DATA_BUILDERS:
        data = _POST_DATA_BUILDERS[name](matrix_corpus)
    if route.stub_search:
        # the index is these routes' only DB dependency
        monkeypatch.setattr(
            "bundesarchiv.app.web.browse_views.search", lambda *a, **k: _empty_search_page()
        )
        monkeypatch.setattr(
            "bundesarchiv.app.web.start.facet_counts", lambda *a, **k: defaultdict(tuple)
        )
        monkeypatch.setattr("bundesarchiv.app.web.start.dateless_count", lambda *a, **k: 0)
        monkeypatch.setattr(
            "bundesarchiv.app.web.start.search", lambda *a, **k: _empty_search_page()
        )
    client = client_as(_TIERS[tier])
    headers = {"Sec-Fetch-Site": "same-origin"}  # a browser sends it on every request
    response = (
        client.post(path, data=data, headers=headers)
        if method == "POST"
        else client.get(path, headers=headers)
    )
    if expected == FOUR_OH_FOUR:
        assert_denied(response, f"{method} {name} as {tier}")
    else:
        assert response.status_code == expected, (
            f"{method} {name} as {tier}: expected {expected}, got {response.status_code}"
        )


# --- a marked Article: the read routes answer the Archivist alone (ADR 0022) ----------------------

#: Method-blind like the rows above, so GET probes each.
_MARKED_PATHS: dict[str, Callable[[_MatrixCorpus], str]] = {
    "article-detail": lambda c: f"/articles/{c.marked_ulid}",
    "media": lambda c: f"/media/{c.marked_ulid}/{c.marked_hash}",
    "media-thumb": lambda c: f"/media/{c.marked_ulid}/{c.marked_hash}/thumb",
    "media-display": lambda c: f"/media/{c.marked_ulid}/{c.marked_hash}/display",
}


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("name", _MARKED_PATHS)
def test_a_marked_article_answers_the_archivist_alone(
    matrix_corpus: _MatrixCorpus, name: str, tier: str
) -> None:
    response = client_as(_TIERS[tier]).get(_MARKED_PATHS[name](matrix_corpus))
    if tier == "archivist":
        assert response.status_code == OK, f"{name} of a marked article as the archivist"
    else:
        assert_denied(response, f"{name} of a marked article as {tier}")


#: Every other Article route refuses a marked Article to the Archivist too (ADR 0022: restore it
#: first), writing nothing. Each probe is one that answers something other than the 404 without
#: the refusal, so it bites.
_MARKED_REFUSED: dict[str, tuple[str, str, Callable[[_MatrixCorpus], dict[str, object]]]] = {
    "article-edit": ("POST", "/articles/{}/edit", _marked_post_data),
    "article-copy": ("POST", "/articles/{}/copy", lambda _c: {}),
    "article-delete": ("POST", "/articles/{}/delete", _marked_post_data),
    "article-publish": ("POST", "/articles/{}/publish", lambda _c: {}),
    "article-media-move": (
        "POST",
        "/articles/{}/media/move",
        lambda c: {"hash": c.marked_hash, "direction": "down"},
    ),
    "article-media-remove": (
        "POST",
        "/articles/{}/media/remove",
        lambda c: {"remove": c.marked_hash},
    ),
    "article-media-upload": ("POST", "/articles/{}/media/upload", lambda _c: {}),
    "upload-gate": ("GET", "/upload-gate/{}", lambda _c: {}),
    "article-document-types": ("GET", "/articles/{}/document-types", lambda _c: {}),
}


def _unchanged(c: _MatrixCorpus) -> tuple[object, ...]:
    """What a refused write must leave as it was: every Article, and the marked one's version."""
    return tuple(c.base.articles.list_ulids()), c.base.articles.load(c.marked_ulid).version


@pytest.mark.parametrize("name", _MARKED_REFUSED)
def test_a_marked_article_refuses_every_other_route(
    matrix_corpus: _MatrixCorpus, name: str
) -> None:
    method, path, data = _MARKED_REFUSED[name]
    path = path.format(matrix_corpus.marked_ulid)
    assert resolve(path).url_name == name
    before = _unchanged(matrix_corpus)
    client = client_as(Archivist())
    headers = {"Sec-Fetch-Site": "same-origin"}
    response = (
        client.post(path, data(matrix_corpus), headers=headers)
        if method == "POST"
        else client.get(path, headers=headers)
    )
    assert_denied(response, f"{method} {name} on a marked article")
    assert _unchanged(matrix_corpus) == before


@pytest.mark.parametrize("name", ["article-delete-permanently", "article-restore"])
def test_a_trash_route_refuses_an_unmarked_article(matrix_corpus: _MatrixCorpus, name: str) -> None:
    ulid = matrix_corpus.article_ulid
    before = matrix_corpus.base.articles.load(ulid)
    path = _CONTRACT[name].build_path(matrix_corpus).replace(matrix_corpus.marked_ulid, ulid)
    client = client_as(Archivist())
    assert_denied(client.get(path), f"GET {name} on an unmarked article")
    response = client.post(path, {"expected_version": str(before.version)})
    assert_denied(response, f"POST {name} on an unmarked article")
    assert matrix_corpus.base.articles.load(ulid) == before


@pytest.mark.parametrize("confirmed", ["", "1"])
def test_bulk_edit_leaves_a_marked_article_out(
    matrix_corpus: _MatrixCorpus, confirmed: str
) -> None:
    """The check page does not list it and the commit does not write it: bucketed like an absent
    Article, so nothing says why."""
    before = _unchanged(matrix_corpus)
    response = client_as(Archivist()).post(
        "/articles/bulk-edit",
        {
            **_bulk_post_data(matrix_corpus),
            "selection": [matrix_corpus.marked_ulid],
            "confirmed": confirmed,
        },
    )
    assert response.status_code == OK
    if confirmed:
        assert (response.context["saved"], response.context["missing_count"]) == (0, 1)
    else:
        assert response.context["selection"] == []
    assert _unchanged(matrix_corpus) == before


def test_every_article_route_has_a_trash_contract() -> None:
    """A new route under an Article's ulid must say what it does with a marked one."""
    article_routes = {
        p.name
        for p in get_resolver(_PROD_URLCONF).url_patterns
        if isinstance(p, URLPattern)
        and not (p.name or "").startswith(ALIAS_PREFIX)
        and "<str:ulid>" in str(p.pattern)
        and not str(p.pattern).startswith("collections/")
    }
    covered = {
        *_MARKED_PATHS,
        *_MARKED_REFUSED,
        "article-delete-permanently",
        "article-restore",
    }
    assert article_routes == covered


# --- the anonymous gate: the same walk with production's gate turned on ---------------------------

#: The routes the gate exempts (ADR 0018) — they answer an anonymous request themselves, and the
#: matrix rows above already pin WHAT they answer.
_GATE_EXEMPT = ("login", "oidc-callback", "logout")


@pytest.mark.parametrize("name", [n for n in _CONTRACT if n not in _GATE_EXEMPT])
def test_the_anonymous_gate_shows_the_door_on_every_route(
    matrix_corpus: _MatrixCorpus, name: str
) -> None:
    """With the gate on, nothing about a route or a record is answerable before authentication."""
    path = _CONTRACT[name].build_path(matrix_corpus)
    with override_settings(ANONYMOUS_GATE_ENABLED=True):
        assert_door(client_as(None).get(path), path, name)


@pytest.mark.parametrize("name", _GATE_EXEMPT)
def test_the_gate_never_bounces_the_login_flow(matrix_corpus: _MatrixCorpus, name: str) -> None:
    """The exemption, from the same list: bouncing the login to the login is a loop, and the logout
    must stay usable to a browser whose cookie can no longer be read."""
    with override_settings(ANONYMOUS_GATE_ENABLED=True):
        response = client_as(None).get(_CONTRACT[name].build_path(matrix_corpus))
    assert "workbench/door.html" not in [t.name for t in response.templates], f"{name} is gated"


# --- structural: the contract is exhaustive against the urlconf -----------------------------------


def _prod_route_names() -> set[str]:
    """An ``alias-`` route serves its English twin's view, so the twin's contract covers it."""
    return {name for name in _prod_pattern_names() if not name.startswith(ALIAS_PREFIX)}


def _prod_pattern_names() -> list[str]:
    """Asserts the urlconf stays flat: an ``include()`` would nest routes past the matrix."""
    patterns = get_resolver(_PROD_URLCONF).url_patterns
    assert all(isinstance(p, URLPattern) for p in patterns), "prod urlconf is no longer flat"
    unnamed = [str(p.pattern) for p in patterns if isinstance(p, URLPattern) and p.name is None]
    assert not unnamed, (
        f"prod routes with no name=, invisible to the leak matrix: {unnamed} — every route needs a"
        " name (it is the key the contract and the screen inventory join on)"
    )
    return [p.name for p in patterns if isinstance(p, URLPattern) and p.name is not None]


def test_contract_covers_every_prod_route() -> None:
    assert set(_CONTRACT) == _prod_route_names(), (
        f"contract vs urlconf drift: "
        f"missing from contract = {_prod_route_names() - set(_CONTRACT)}, "
        f"stale in contract = {set(_CONTRACT) - _prod_route_names()}"
    )


def test_every_prod_route_name_is_unique() -> None:
    """A duplicate name would hide inside the exhaustiveness set-equality."""
    names = [name for name in _prod_pattern_names() if name is not None]
    assert len(names) == len(set(names)), f"duplicate route names: {names}"


# --- structural: the dev-only routes are unreachable under the prod urlconf ------------------------

_DEV_ONLY_PATHS = (
    "/favicon.ico",
    "/_dev/viewer/",
    "/_dev/components/",
    "/_dev/layouts/split-narrow/",
)


@pytest.mark.parametrize("path", _DEV_ONLY_PATHS)
def test_dev_routes_absent_from_prod_urlconf(path: str) -> None:
    resolve(path, urlconf=_DEV_URLCONF)  # present in dev — raises here if the assumption is wrong
    with pytest.raises(Resolver404):
        resolve(path, urlconf=_PROD_URLCONF)
