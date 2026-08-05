"""The route x tier leak matrix (Part 4.10) — the whole HTTP surface, one exhaustive suite.

Every per-route test already pins its own contract; this suite is the STRUCTURAL backstop that no
route escapes the discipline. It walks the PRODUCTION urlconf (``bundesarchiv.app.web.urls``) and,
for every route, asserts the exact status an anonymous / Public / Member(with & without a matching
group) / Archivist viewer gets under both GET and POST. A deny is simply its status code — 404,
with no leaked content (the byte-identical-404 law was relaxed by the owner, 2026-08); each
route's own tests pin that a deny changes/reveals nothing.

The invariant that makes this a GATE, not a snapshot:

- **Exhaustiveness.** ``_CONTRACT`` carries one explicit entry per route name; the suite asserts the
  contract's key set EQUALS the urlconf's route names. A future route added to ``urls.py`` without a
  matrix entry FAILS ``test_contract_covers_every_prod_route`` — you cannot ship a route the leak
  matrix has never seen.

Method note (contract-shaping fact, verified in the views): no route uses a method guard, so a
disallowed method is NOT a 405 — the POST-only routes 404 on GET and the GET-only routes 404 on POST
via the same ``_not_found``. The static/dev routes are the exception: they ignore method entirely.

Dev-only routes (``dev_urls.py``) are covered by their own prod-by-absence assertions here:
``test_dev_routes_absent_from_prod_urlconf`` proves each is a ``Resolver404`` under the prod urlconf.

Pure request handling against a local FS store — no Postgres (the web/ subtree is exempt from
SKIP_PG), and the index-write / worker-enqueue seams are the conftest autouse no-ops.
"""

import io
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from django.core import signing
from django.test import Client, override_settings
from django.urls import Resolver404, URLPattern, get_resolver, resolve
from PIL import Image

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-leak-matrix-dev-key"
_PROD_URLCONF = "bundesarchiv.app.web.urls"
_DEV_URLCONF = "bundesarchiv.app.web.dev_urls"


# --- the corpus: real articles + collections + one media blob, across every tier -----------------


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(buf, format="PNG")
    return buf.getvalue()


class _Corpus:
    """A tiny FS archive with one Collection per tier and one published, group-scoped Article that
    carries a real media blob — enough to give an Archivist a 200 on every ulid/hash-bearing route
    and to make the media route's authorization non-trivial. The GROUPS tier names ``vorstand`` so a
    matching-group Member is distinguishable from a non-matching one."""

    def __init__(self, root: Path, thumbnail_root: Path) -> None:
        self.root = root
        self.thumbnail_root = thumbnail_root
        self.store = LocalFsObjectStore(root)
        self._build()

    def _build(self) -> None:
        collections = CollectionRepository(self.store)
        articles = ArticleRepository(self.store)
        # The editable collection carries a REAL ULID — ``collection_edit`` validates the ulid in-view
        # (a literal like "GRP" would 404 as malformed), so ``bestand-bearbeiten`` needs a valid one.
        self.collection_ulid = new_ulid()
        collections.save(Collection("ROOT", "Wurzel", None), 0)
        collections.save(
            Collection(
                self.collection_ulid,
                "Gruppen",
                "ROOT",
                Audience(AudienceTier.GROUPS, ("vorstand",)),
            ),
            0,
        )
        # A GROUPS-tier published article: an Archivist sees it, a matching-group Member sees it, a
        # non-matching Member and Public do not — so every ulid/hash route resolves for the Archivist.
        self.article_ulid = new_ulid()
        ref = articles.add_media(
            self.article_ulid, "cover.png", _png_bytes((30, 60, 90)), media_type="image/png"
        )
        articles.save(
            Article(
                ulid=self.article_ulid,
                title="Matrix Artikel",
                collection_id=self.collection_ulid,
                lifecycle=Lifecycle.PUBLISHED,
                media=(ref,),
            ),
            0,
        )
        self.content_hash = ref.content_hash
        # The CAS version the store landed the article at (a save writes the NEXT version), read back
        # so the lifecycle route's expected_version matches and the retract succeeds (302, not a
        # conflict re-render).
        self.article_version = articles.load(self.article_ulid).version

    def generate_thumbnail(self) -> None:
        from bundesarchiv.app import thumbnails

        thumbnails.generate_thumbnail(self.store, self.content_hash, self.thumbnail_root)


@pytest.fixture
def corpus(tmp_path: Path) -> _Corpus:
    c = _Corpus(tmp_path / "canonical", tmp_path / "thumbnails")
    c.generate_thumbnail()
    return c


def _settings(corpus: _Corpus, **extra: object) -> dict[str, object]:
    return {
        "ROOT_URLCONF": _PROD_URLCONF,
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(corpus.root),
        "BUNDESARCHIV_THUMBNAIL_ROOT": str(corpus.thumbnail_root),
        "BUNDESARCHIV_X_ACCEL_PREFIX": None,
        **extra,
    }


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


def _client(tier: str) -> Client:
    """A test client for ``tier``: no cookie for ``anonymous``, else a valid dev-viewer cookie signed
    with the test dev key exactly as the switcher would."""
    client = Client()
    viewer = _TIERS[tier]
    if viewer is not None:
        signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
        client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


# --- the contract: expected status per route x method, and how to reach each -----------------------

# Status classes. A route entry declares, for each of GET and POST, the expected status for a
# NON-archivist and for the Archivist.
FOUR_OH_FOUR = 404
OK = 200
REDIRECT = 302


class Route:
    """One route's leak contract. ``build_path`` maps the corpus to the concrete URL; the four status
    fields are the expected codes; ``post_data`` (if any) is sent on the POST probe; ``skip_post_body
    _check`` marks routes whose archivist-allowed status is method-dependent (documented inline)."""

    def __init__(
        self,
        *,
        build_path: Callable[[_Corpus], str],
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


def _p_root(_c: _Corpus) -> str:
    return "/"


#: Each static route's literal path (the route names carry no captures — a plain constant per route).
_STATIC_PATHS = {
    "static-htmx": "/static/htmx.min.js",
    "static-ledger-pane": "/static/ledger_pane.js",
    "static-catalog-form": "/static/catalog_form.js",
    "static-catalog-bulk": "/static/catalog_bulk.js",
    "static-tokens": "/static/tokens.css",
    "static-components": "/static/components.css",
    "static-layouts": "/static/layouts.css",
    "static-forms": "/static/forms.css",
    "static-detail": "/static/detail.css",
}


def _p_static(name: str) -> Callable[[_Corpus], str]:
    """The path-builder for a static route: a corpus-independent constant lookup by route name."""
    path = _STATIC_PATHS[name]
    return lambda _c: path


def _p_artikel_neu(_c: _Corpus) -> str:
    return "/artikel/neu"


def _p_bestand_neu(_c: _Corpus) -> str:
    return "/bestand/neu"


def _p_bestand_bearbeiten(c: _Corpus) -> str:
    return f"/bestand/{c.collection_ulid}/bearbeiten"


def _p_sammel_dok(_c: _Corpus) -> str:
    return "/artikel/sammelbearbeitung/dokumenttypen"


def _p_sammel(_c: _Corpus) -> str:
    return "/artikel/sammelbearbeitung"


def _p_edit(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/bearbeiten"


def _p_kopieren(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/kopieren"


def _p_loeschen(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/loeschen"


def _p_lebenszyklus(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/lebenszyklus"


def _p_vorschau(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/vorschau"


def _p_medien_verschieben(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/medien/verschieben"


def _p_medien_entfernen(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/medien/entfernen"


def _p_medien_hochladen(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/medien/hochladen"


def _p_dokumenttypen(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/dokumenttypen"


def _p_datierung_echo(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}/datierung-echo"


def _p_detail(c: _Corpus) -> str:
    return f"/artikel/{c.article_ulid}"


def _p_media(c: _Corpus) -> str:
    return f"/media/{c.article_ulid}/{c.content_hash}"


def _p_media_thumb(c: _Corpus) -> str:
    return f"/media/{c.article_ulid}/{c.content_hash}/thumb"


# The exhaustive contract — ONE entry per prod route name. Keeping it a dict keyed by route name lets
# ``test_contract_covers_every_prod_route`` assert exhaustiveness against the urlconf.
_CONTRACT: dict[str, Route] = {
    # Open pages/assets — 200 for every tier, method-blind (no guard). Never a deny path here.
    "workbench": Route(
        build_path=_p_root,
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
        stub_search=True,
    ),
    "static-htmx": Route(
        build_path=_p_static("static-htmx"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
    ),
    "static-ledger-pane": Route(
        build_path=_p_static("static-ledger-pane"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
    ),
    "static-catalog-form": Route(
        build_path=_p_static("static-catalog-form"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
    ),
    "static-catalog-bulk": Route(
        build_path=_p_static("static-catalog-bulk"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
    ),
    "static-tokens": Route(
        build_path=_p_static("static-tokens"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
    ),
    "static-components": Route(
        build_path=_p_static("static-components"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
    ),
    "static-layouts": Route(
        build_path=_p_static("static-layouts"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
    ),
    "static-forms": Route(
        build_path=_p_static("static-forms"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
    ),
    "static-detail": Route(
        build_path=_p_static("static-detail"),
        get_nonarch=OK,
        get_arch=OK,
        post_nonarch=OK,
        post_arch=OK,
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
        post_data={"bestaetigt": "1"},
    ),
    "artikel-lebenszyklus": Route(
        build_path=_p_lebenszyklus,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=REDIRECT,  # retract (zurueckziehen) + CAS version → 302 to the read view
        post_data=None,  # filled at probe time (needs the corpus version) — see _lifecycle_post_data
    ),
    "artikel-vorschau": Route(
        build_path=_p_vorschau,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=FOUR_OH_FOUR,  # GET disallowed
        post_nonarch=FOUR_OH_FOUR,
        post_arch=OK,  # preview panel
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
    "artikel-dokumenttypen": Route(
        build_path=_p_dokumenttypen,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,  # options partial
        post_nonarch=FOUR_OH_FOUR,
        post_arch=FOUR_OH_FOUR,  # POST disallowed
    ),
    "artikel-datierung-echo": Route(
        build_path=_p_datierung_echo,
        get_nonarch=FOUR_OH_FOUR,
        get_arch=OK,  # echo partial
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


def _sammel_post_data(c: _Corpus) -> dict[str, object]:
    """A valid confirm-phase bulk POST: one real ulid selected + a field + its value → the confirm
    page (200) for an archivist. Non-archivists never reach validation (gate denies first)."""
    return {"auswahl": [c.article_ulid], "feld": "creator", "wert_creator": "Jemand"}


def _lifecycle_post_data(c: _Corpus) -> dict[str, object]:
    """A valid retract POST: ``zurueckziehen`` needs no over-exposure confirm, and the CAS version
    matches the corpus article → the archivist gets a 302 to the read view. Non-archivists deny at
    the gate before the verb is read."""
    return {"aktion": "zurueckziehen", "expected_version": str(c.article_version)}


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


def _matrix_cases() -> Iterator[tuple[str, str, str]]:
    for name in _CONTRACT:
        if name in _STATIC_PATHS:
            # Static assets carry no per-tier behavior (200 for everyone, method-blind): one probe
            # (Public GET → 200) suffices. The routes stay in _CONTRACT so the exhaustiveness gate
            # still covers them.
            yield name, "public", "GET"
            continue
        for tier in _TIERS:
            for method in ("GET", "POST"):
                yield name, tier, method


#: Routes whose POST payload needs the corpus (a real ulid / version), filled at probe time.
_POST_DATA_BUILDERS = {
    "artikel-sammelbearbeitung": _sammel_post_data,
    "artikel-lebenszyklus": _lifecycle_post_data,
}


@pytest.mark.parametrize(("name", "tier", "method"), list(_matrix_cases()))
def test_route_tier_matrix(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch, name: str, tier: str, method: str
) -> None:
    route = _CONTRACT[name]
    expected = _expected_for(route, tier, method)
    path = route.build_path(corpus)
    data: dict[str, object] = route.post_data
    if name in _POST_DATA_BUILDERS:
        data = _POST_DATA_BUILDERS[name](corpus)
    if route.stub_search:
        # The workbench's only DB dependency is search(); stub it so the STATUS/tier-chrome path runs
        # DB-free. The real view code (viewer resolution, template render, archivist-chrome gating)
        # still executes — only the index query is replaced with an empty page.
        monkeypatch.setattr(
            "bundesarchiv.app.web.browse_views.search", lambda *a, **k: _empty_search_page()
        )
    with override_settings(**_settings(corpus)):
        client = _client(tier)
        response = client.post(path, data=data) if method == "POST" else client.get(path)
    assert response.status_code == expected, (
        f"{method} {name} as {tier}: expected {expected}, got {response.status_code}"
    )


# --- structural: the contract is exhaustive against the urlconf -----------------------------------


def _prod_route_names() -> set[str]:
    return {name for name in _prod_pattern_names() if name is not None}


def _prod_pattern_names() -> list[str | None]:
    """The ``.name`` of every prod pattern. The prod urlconf is deliberately FLAT (all ``path()``, no
    ``include()``), so every entry is a ``URLPattern``; asserting that here doubles as a guard that a
    future ``include()`` (which would nest routes past the leak matrix) is a deliberate change."""
    patterns = get_resolver(_PROD_URLCONF).url_patterns
    assert all(isinstance(p, URLPattern) for p in patterns), "prod urlconf is no longer flat"
    return [p.name for p in patterns if isinstance(p, URLPattern)]


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
    "/_dev/components/papier/",
    "/_dev/layouts/split-narrow/",
    "/_dev/static/components.css",
    "/_dev/layouts/static/layouts.css",
)


@pytest.mark.parametrize("path", _DEV_ONLY_PATHS)
def test_dev_routes_absent_from_prod_urlconf(path: str) -> None:
    """Every dev-only route resolves under the DEV urlconf but is a ``Resolver404`` under the PROD
    urlconf — dev is gated by ABSENCE of the urlconf, not by a runtime flag, so a production process
    (which points ROOT_URLCONF at ``...urls``) can never reach the switcher, the demo pages, or the
    dev stylesheet servers."""
    resolve(path, urlconf=_DEV_URLCONF)  # present in dev — raises here if the assumption is wrong
    with pytest.raises(Resolver404):
        resolve(path, urlconf=_PROD_URLCONF)
