"""The route x tier leak matrix (Part 4.10) — the whole HTTP surface, one exhaustive suite.

Every per-route test already pins its own contract; this suite is the STRUCTURAL backstop that no
route escapes the discipline. It walks the PRODUCTION urlconf (``bundesarchiv.app.web.urls``) and,
for every route, asserts the exact status an anonymous / Public / Member(with & without a matching
group) / Archivist viewer gets under both GET and POST. A deny is ``assert_denied`` — a plain 404
revealing nothing (the byte-identical-404 law was relaxed by the owner, 2026-08); each route's own
tests pin that a deny additionally changes nothing.

The invariant that makes this a GATE, not a snapshot, is **exhaustiveness**: ``_CONTRACT`` carries
one explicit entry per route name, and the suite asserts the contract's key set EQUALS the urlconf's
route names. A future route added to ``urls.py`` without a matrix entry FAILS
``test_contract_covers_every_prod_route`` — you cannot ship a route the leak matrix has never seen.

Method note (contract-shaping fact, verified in the views): no route uses a method guard, so a
disallowed method is NOT a 405 — the POST-only routes 404 on GET and the GET-only routes 404 on POST
via the same shared 404 helper. The dev routes are the exception: they ignore method entirely.

Static assets are NOT in this matrix: ``/static/*`` is served by WhiteNoise middleware (ADR 0016),
never the urlconf. Its public-by-design contract is pinned in ``test_static_assets.py``.

Dev-only routes (``dev_urls.py``) are covered by their own prod-by-absence assertions here:
``test_dev_routes_absent_from_prod_urlconf`` proves each is a ``Resolver404`` under the prod urlconf.

Pure request handling against a local FS store — no Postgres, and the index-write /
worker-enqueue seams are the conftest autouse no-ops.
"""

import io
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from django.test import override_settings
from django.urls import Resolver404, URLPattern, get_resolver, resolve
from PIL import Image
from tests.app.web._asserts import assert_denied, assert_door
from tests.app.web._fixtures import ROOT, Corpus, client_as, make_article, make_collection

from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

_PROD_URLCONF = "bundesarchiv.app.web.urls"
_DEV_URLCONF = "bundesarchiv.app.web.dev_urls"


# --- the corpus: real articles + collections + one media blob, across every tier -----------------


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(buf, format="PNG")
    return buf.getvalue()


class _MatrixCorpus:
    """The shared ``Corpus`` filled with one GROUPS-tier Collection and one published, group-scoped
    Article that carries a real media blob — enough to give an Archivist a 200 on every
    ulid/hash-bearing route and to make the media route's authorization non-trivial. The GROUPS tier
    names ``vorstand`` so a matching-group Member is distinguishable from a non-matching one; the
    frozen standard corpus is PUBLIC and media-free, so the matrix builds its own content."""

    def __init__(self, base: Corpus, thumbnail_root: Path) -> None:
        self.base = base
        self.thumbnail_root = thumbnail_root
        self._build()

    def _build(self) -> None:
        # The editable collection carries a REAL ULID — ``collection_edit`` validates the ulid in-view
        # (a literal like "GRP" would 404 as malformed), so ``bestand-bearbeiten`` needs a valid one.
        self.collection_ulid = new_ulid()
        self.base.add_collection(
            make_collection(
                self.collection_ulid,
                "Gruppen",
                ROOT,
                Audience(AudienceTier.GROUPS, ("vorstand",)),
            )
        )
        # A GROUPS-tier published article: an Archivist sees it, a matching-group Member sees it, a
        # non-matching Member and Public do not — so every ulid/hash route resolves for the Archivist.
        self.article_ulid = new_ulid()
        ref = self.base.articles.add_media(
            self.article_ulid,
            "cover.png",
            io.BytesIO(_png_bytes((30, 60, 90))),
            media_type="image/png",
        )
        self.base.add_article(
            make_article(
                self.article_ulid,
                collection_id=self.collection_ulid,
                lifecycle=Lifecycle.PUBLISHED,
                title="Matrix Artikel",
                media=(ref,),
            )
        )
        self.content_hash = ref.content_hash
        # The CAS version the store landed the article at (a save writes the NEXT version), read back
        # so the lifecycle route's expected_version matches and the retract succeeds (302, not a
        # conflict re-render).
        self.article_version = self.base.articles.load(self.article_ulid).version
        # A Public article in the Papierkorb (ADR 0022): every tier would see it but for the mark.
        self.marked_ulid = new_ulid()
        marked_ref = self.base.articles.add_media(
            self.marked_ulid,
            "cover.png",
            io.BytesIO(_png_bytes((90, 60, 30))),
            media_type="image/png",
        )
        marked = make_article(
            self.marked_ulid,
            collection_id=self.collection_ulid,
            audience=Audience(AudienceTier.PUBLIC),
            media=(marked_ref,),
        )
        self.marked_version = self.base.articles.mark_deleted(
            marked, self.base.add_article(marked), by="tester"
        )
        self.marked_hash = marked_ref.content_hash

    def generate_thumbnail(self, ulid: str, content_hash: str) -> None:
        from bundesarchiv.app import thumbnails

        thumbnails.generate_thumbnail(self.base.store, ulid, content_hash, self.thumbnail_root)


@pytest.fixture
def matrix_corpus(make_corpus: Callable[[], Corpus], tmp_path: Path) -> Iterator[_MatrixCorpus]:
    # The two settings ``settings_for`` does not carry stay local: the thumbnail root (per-test tmp
    # dir) and the X-Accel prefix (None = Django serves the bytes, so the media probes read a body).
    # No thumbnail is generated here: only the media-thumb route's allowed probes read it (the test
    # generates it for that route alone) — everything else would pay the PIL round-trip for nothing.
    # Build BEFORE entering the override — ``make_corpus`` enters a settings context of its own that
    # tears down last, so this one has to nest inside it to unwind in order.
    thumbnail_root = tmp_path / "thumbnails"
    built = _MatrixCorpus(make_corpus(), thumbnail_root)
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

# Status classes. A route entry declares, for each of GET and POST, the expected status for a
# NON-archivist and for the Archivist.
FOUR_OH_FOUR = 404
OK = 200
NO_CONTENT = 204
REDIRECT = 302
ALIAS_PREFIX = "alias-"


class Route:
    """One route's leak contract. ``build_path`` maps the corpus to the concrete URL; the four status
    fields are the expected codes; ``post_data`` (if any) is sent on the POST probe; ``skip_post_body
    _check`` marks routes whose archivist-allowed status is method-dependent (documented inline)."""

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
        # stub_search: the workbench route calls the Postgres index (search()); the matrix stubs it
        # to an empty page so the STATUS/tier-chrome path runs DB-free. Content-scoping correctness is
        # test_workbench.py's job (real Postgres) — here we only assert the route 200s for every tier.
        self.stub_search = stub_search


def _p_root(_c: _MatrixCorpus) -> str:
    return "/"


def _p_spalten(_c: _MatrixCorpus) -> str:
    return "/columns"


def _p_trash(_c: _MatrixCorpus) -> str:
    return "/trash"


def _p_login(_c: _MatrixCorpus) -> str:
    return "/login"


def _p_oidc_callback(_c: _MatrixCorpus) -> str:
    return "/oidc/callback"


def _p_logout(_c: _MatrixCorpus) -> str:
    return "/logout"


def _p_artikel_neu(_c: _MatrixCorpus) -> str:
    return "/articles/new"


def _p_bestand_neu(_c: _MatrixCorpus) -> str:
    return "/collections/new"


def _p_bestand_bearbeiten(c: _MatrixCorpus) -> str:
    return f"/collections/{c.collection_ulid}/edit"


def _p_sammel_dok(_c: _MatrixCorpus) -> str:
    return "/articles/bulk-edit/document-types"


def _p_sammel(_c: _MatrixCorpus) -> str:
    return "/articles/bulk-edit"


def _p_edit(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/edit"


def _p_kopieren(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/copy"


def _p_loeschen(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/delete"


def _p_delete_permanently(c: _MatrixCorpus) -> str:
    return f"/articles/{c.marked_ulid}/delete-permanently"


def _p_restore(c: _MatrixCorpus) -> str:
    return f"/articles/{c.marked_ulid}/restore"


def _p_veroeffentlichen(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/publish"


def _p_medien_verschieben(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/media/move"


def _p_medien_entfernen(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/media/remove"


def _p_medien_hochladen(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/media/upload"


def _p_upload_gate(c: _MatrixCorpus) -> str:
    return f"/upload-gate/{c.article_ulid}"


def _p_dokumenttypen(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}/document-types"


def _p_tag_suggestions(_c: _MatrixCorpus) -> str:
    return "/tags/suggestions"


def _p_detail(c: _MatrixCorpus) -> str:
    return f"/articles/{c.article_ulid}"


def _p_media(c: _MatrixCorpus) -> str:
    return f"/media/{c.article_ulid}/{c.content_hash}"


def _p_media_thumb(c: _MatrixCorpus) -> str:
    return f"/media/{c.article_ulid}/{c.content_hash}/thumb"


# The exhaustive contract — ONE entry per prod route name. Keeping it a dict keyed by route name lets
# ``test_contract_covers_every_prod_route`` assert exhaustiveness against the urlconf.
_CONTRACT: dict[str, Route] = {
    # Open page — 200 for every tier, method-blind (no guard). Never a deny path here.
    "workbench": Route(
        build_path=_p_root,
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
        stub_search=True,
    ),
    # The "Spalten …" choice: a viewer's own preference, kept in a cookie — every tier may make it
    # (302 back to the list), and GET is the plain 404. It reads and writes no record.
    "spalten": Route(
        build_path=_p_spalten,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,
        post_nonarch=REDIRECT,
        post_arch=REDIRECT,
    ),
    # The Papierkorb (ADR 0022): the Archivist's alone, GET only. Its rows come from search(), whose
    # Papierkorb scoping is test_leaks_papierkorb.py's; here the gate.
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
    "artikel-neu": Route(
        build_path=_p_artikel_neu,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # empty POST → validation re-render (200)
    ),
    "bestand-neu": Route(
        build_path=_p_bestand_neu,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # empty POST → validation re-render (200)
    ),
    "bestand-bearbeiten": Route(
        build_path=_p_bestand_bearbeiten,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # blank-name POST → error re-render (200)
    ),
    "artikel-bearbeiten": Route(
        build_path=_p_edit,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # invalid POST → validation re-render (200)
    ),
    "artikel-kopieren": Route(
        build_path=_p_kopieren,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed → 404 even for archivist
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # copy → 302 to the copy's edit form
    ),
    "artikel-loeschen": Route(
        build_path=_p_loeschen,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,  # GET = confirm page
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # confirmed delete → 302 to /
        post_data=None,  # filled at probe time (the confirm's version) — see _POST_DATA_BUILDERS
    ),
    # The Papierkorb's two routes, probed on the marked article (ADR 0022); an unmarked one is
    # refused to the Archivist too — see test_a_papierkorb_route_refuses_an_unmarked_article.
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
    "artikel-veroeffentlichen": Route(
        build_path=_p_veroeffentlichen,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # the corpus article is published: refused, back to its page
    ),
    "artikel-medien-verschieben": Route(
        build_path=_p_medien_verschieben,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # re-render edit form
    ),
    "artikel-medien-entfernen": Route(
        build_path=_p_medien_entfernen,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # confirm step / re-render
    ),
    "artikel-medien-hochladen": Route(
        build_path=_p_medien_hochladen,
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
    "artikel-dokumenttypen": Route(
        build_path=_p_dokumenttypen,
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
    "artikel-sammelbearbeitung": Route(
        build_path=_p_sammel,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # confirm page for a real selection + field
        post_data=None,  # filled at probe time (needs the corpus ulid) — see _sammel_post_data
    ),
    "artikel-sammelbearbeitung-dokumenttypen": Route(
        build_path=_p_sammel_dok,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,  # ULID-free options partial
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,  # POST disallowed
    ),
    # Read routes — group-sensitive. Non-matching tiers get a 404; the matching-group Member and
    # Archivist get 200. Method-blind (POST runs the GET path).
    "artikel-detail": Route(
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
}


def _sammel_post_data(c: _MatrixCorpus) -> dict[str, object]:
    """A valid confirm-phase bulk POST: one real ulid selected + a field + its value → the confirm
    page (200) for an archivist. Non-archivists never reach validation (gate denies first)."""
    return {"auswahl": [c.article_ulid], "feld": "creator", "wert_creator": "Jemand"}


def _loeschen_post_data(c: _MatrixCorpus) -> dict[str, object]:
    """The confirm as its page hands it out: against the article's current version."""
    return {"expected_version": str(c.article_version)}


def _marked_post_data(c: _MatrixCorpus) -> dict[str, object]:
    return {"expected_version": str(c.marked_version)}


def _empty_search_page() -> object:
    """An empty ``SearchPage`` for the workbench stub: no hits, no facets — enough for the template to
    render the (empty) ledger for any tier so the matrix can assert the route's status DB-free."""
    from bundesarchiv.index.query import SearchPage

    return SearchPage(hits=(), total=0, facets={}, dateless_count=0)


def _expected_for(route: Route, tier: str, method: str) -> int | None:
    """The expected status for ``route`` at ``tier`` under ``method``, resolving the tier-sensitive
    read routes (matching-group Member is allowed like the Archivist)."""
    is_arch = tier == "archivist"
    if route.tier_sensitive and tier == "member_matching":
        is_arch = True  # a matching-group Member sees the GROUPS-tier corpus article
    if method == "GET":
        return route.get_arch if is_arch else route.get_nonarch
    return route.post_arch if is_arch else route.post_nonarch


# --- the matrix -----------------------------------------------------------------------------------


def _tier_invariant(route: Route) -> bool:
    """A route whose contract declares the SAME status for every tier x method cell (and no
    tier-sensitive resolution) has exactly one distinct cell — one probe proves it. Derived from
    the declared statuses, so a future route with any tier-varying cell is probed in full."""
    statuses = {route.get_nonarch, route.get_arch, route.post_nonarch, route.post_arch}
    return len(statuses) == 1 and not route.tier_sensitive


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
    "artikel-sammelbearbeitung": _sammel_post_data,
    "artikel-loeschen": _loeschen_post_data,
    "article-delete-permanently": _marked_post_data,
    "article-restore": _marked_post_data,
}


@pytest.mark.parametrize(("name", "tier", "method"), list(_matrix_cases()))
def test_route_tier_matrix(
    matrix_corpus: _MatrixCorpus, monkeypatch: pytest.MonkeyPatch, name: str, tier: str, method: str
) -> None:
    route = _CONTRACT[name]
    expected = _expected_for(route, tier, method)
    if name == "media-thumb":
        matrix_corpus.generate_thumbnail(matrix_corpus.article_ulid, matrix_corpus.content_hash)
    path = route.build_path(matrix_corpus)
    data: dict[str, object] = route.post_data
    if name in _POST_DATA_BUILDERS:
        data = _POST_DATA_BUILDERS[name](matrix_corpus)
    if route.stub_search:
        # The workbench's only DB dependency is search(); stub it so the STATUS/tier-chrome path runs
        # DB-free. The real view code (viewer resolution, template render, archivist-chrome gating)
        # still executes — only the index query is replaced with an empty page.
        monkeypatch.setattr(
            "bundesarchiv.app.web.browse_views.search", lambda *a, **k: _empty_search_page()
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
    "artikel-detail": lambda c: f"/articles/{c.marked_ulid}",
    "media": lambda c: f"/media/{c.marked_ulid}/{c.marked_hash}",
    "media-thumb": lambda c: f"/media/{c.marked_ulid}/{c.marked_hash}/thumb",
}


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("name", _MARKED_PATHS)
def test_a_marked_article_answers_the_archivist_alone(
    matrix_corpus: _MatrixCorpus, name: str, tier: str
) -> None:
    if name == "media-thumb":
        matrix_corpus.generate_thumbnail(matrix_corpus.marked_ulid, matrix_corpus.marked_hash)
    response = client_as(_TIERS[tier]).get(_MARKED_PATHS[name](matrix_corpus))
    if tier == "archivist":
        assert response.status_code == OK, f"{name} of a marked article as the archivist"
    else:
        assert_denied(response, f"{name} of a marked article as {tier}")


#: Every other Article route refuses a marked Article to the Archivist too (ADR 0022: restore it
#: first), writing nothing. Each probe is one that answers something other than the 404 without
#: the refusal, so it bites.
_MARKED_REFUSED: dict[str, tuple[str, str, Callable[[_MatrixCorpus], dict[str, object]]]] = {
    "artikel-bearbeiten": ("POST", "/articles/{}/edit", _marked_post_data),
    "artikel-kopieren": ("POST", "/articles/{}/copy", lambda _c: {}),
    "artikel-loeschen": ("POST", "/articles/{}/delete", _marked_post_data),
    "artikel-veroeffentlichen": ("POST", "/articles/{}/publish", lambda _c: {}),
    "artikel-medien-verschieben": (
        "POST",
        "/articles/{}/media/move",
        lambda c: {"hash": c.marked_hash, "richtung": "runter"},
    ),
    "artikel-medien-entfernen": (
        "POST",
        "/articles/{}/media/remove",
        lambda c: {"entfernen": c.marked_hash},
    ),
    "artikel-medien-hochladen": ("POST", "/articles/{}/media/upload", lambda _c: {}),
    "upload-gate": ("GET", "/upload-gate/{}", lambda _c: {}),
    "artikel-dokumenttypen": ("GET", "/articles/{}/document-types", lambda _c: {}),
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
def test_a_papierkorb_route_refuses_an_unmarked_article(
    matrix_corpus: _MatrixCorpus, name: str
) -> None:
    ulid = matrix_corpus.article_ulid
    before = matrix_corpus.base.articles.load(ulid)
    path = _CONTRACT[name].build_path(matrix_corpus).replace(matrix_corpus.marked_ulid, ulid)
    client = client_as(Archivist())
    assert_denied(client.get(path), f"GET {name} on an unmarked article")
    response = client.post(path, {"expected_version": str(before.version)})
    assert_denied(response, f"POST {name} on an unmarked article")
    assert matrix_corpus.base.articles.load(ulid) == before


@pytest.mark.parametrize("bestaetigt", ["", "1"])
def test_bulk_edit_leaves_a_marked_article_out(
    matrix_corpus: _MatrixCorpus, bestaetigt: str
) -> None:
    """The check page does not list it and the commit does not write it: bucketed like an absent
    Article, so nothing says why."""
    before = _unchanged(matrix_corpus)
    response = client_as(Archivist()).post(
        "/articles/bulk-edit",
        {
            **_sammel_post_data(matrix_corpus),
            "auswahl": [matrix_corpus.marked_ulid],
            "bestaetigt": bestaetigt,
        },
    )
    assert response.status_code == OK
    if bestaetigt:
        assert (response.context["saved"], response.context["missing_count"]) == (0, 1)
    else:
        assert response.context["auswahl"] == []
    assert _unchanged(matrix_corpus) == before


def test_every_article_route_has_a_papierkorb_contract() -> None:
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
    """With the gate on (the production setting), an anonymous visitor gets the door on EVERY route
    — the 200s and the 404s alike, so nothing about a route or a record is answerable before
    authentication. Derived from the same contract as the matrix, so a new route is walked here the
    day it is registered."""
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
    """The canonical routes. The ``alias-`` routes (the old German paths) serve the SAME view callable
    as their English twin, which ``test_old_paths.py`` pins, so the twin's contract covers them."""
    return {name for name in _prod_pattern_names() if not name.startswith(ALIAS_PREFIX)}


def _prod_pattern_names() -> list[str]:
    """The ``.name`` of every prod pattern. Two structural asserts guard the exhaustiveness gate below,
    because both of them are ways for a live route to leave its scope:

    The prod urlconf is deliberately FLAT (all ``path()``, no ``include()``), so every entry is a
    ``URLPattern``; asserting that doubles as a guard that a future ``include()`` — which would nest
    routes past the leak matrix — is a deliberate change.

    And every pattern must be NAMED. ``name`` is the handle the contract joins on, so an unnamed live
    route was un-gated and un-leak-tested: this function used to drop ``None`` from the list, and the
    set-equality then dropped it from BOTH sides and reported no drift at all. A route with no
    ``name=`` is not an exception to the matrix, it is a route the matrix cannot see."""
    patterns = get_resolver(_PROD_URLCONF).url_patterns
    assert all(isinstance(p, URLPattern) for p in patterns), "prod urlconf is no longer flat"
    unnamed = [str(p.pattern) for p in patterns if isinstance(p, URLPattern) and p.name is None]
    assert not unnamed, (
        f"prod routes with no name=, invisible to the leak matrix: {unnamed} — every route needs a"
        " name (it is the key the contract and the screen inventory join on)"
    )
    return [p.name for p in patterns if isinstance(p, URLPattern) and p.name is not None]


def test_contract_covers_every_prod_route() -> None:
    """The GATE: every route in the production urlconf has a leak-matrix contract, and the contract
    names no route the urlconf lacks. Add a route to ``urls.py`` and this fails until the matrix
    grows an entry for it — a future route cannot ship un-leak-tested."""
    assert set(_CONTRACT) == _prod_route_names(), (
        f"contract vs urlconf drift: "
        f"missing from contract = {_prod_route_names() - set(_CONTRACT)}, "
        f"stale in contract = {set(_CONTRACT) - _prod_route_names()}"
    )


def test_every_prod_route_name_is_unique() -> None:
    """No two prod patterns share a name (the exhaustiveness set-equality would otherwise mask a
    duplicate). Guards against a copy-paste route registration."""
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
    """Every dev-only route resolves under the DEV urlconf but is a ``Resolver404`` under the PROD
    urlconf — dev is gated by ABSENCE of the urlconf, not by a runtime flag, so a production process
    (which points ROOT_URLCONF at ``...urls``) can never reach the switcher or the demo pages."""
    resolve(path, urlconf=_DEV_URLCONF)  # present in dev — raises here if the assumption is wrong
    with pytest.raises(Resolver404):
        resolve(path, urlconf=_PROD_URLCONF)
