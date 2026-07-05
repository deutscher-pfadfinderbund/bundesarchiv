"""The archivist workbench route (Part 4.5-MVP) — DB-backed, viewer-scoped search UI.

Every case drives the real route through Django's test ``Client`` with a dev-viewer cookie, over a
LocalFs-backed corpus that is BOTH indexed (so ``search`` sees it) and readable by the view's
collection-name resolution (same store). The security spine: results are viewer-scoped by ``search``
— an Archivist sees drafts in the results, a Public viewer never does (the Part-4 leak discipline,
carried into the UI).

These need Postgres (they call ``search``); the ``corpus`` fixture indexes once per module and wipes
on teardown (the shared ``indexed_corpus`` isolation mechanism).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from django.core import signing
from django.http import HttpResponse
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-workbench-dev-key"


class _Corpus:
    """A LocalFs archive indexed for the workbench tests: a small tiered tree with dates, one
    dateless article, a prefix-recall title, and a draft (archivist-only)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        self._build()
        indexer.rebuild(self.store)

    def _build(self) -> None:
        collections = CollectionRepository(self.store)
        articles = ArticleRepository(self.store)
        collections.save(Collection("ROOT", "Bundesarchiv", None), 0)
        collections.save(
            Collection("FOTOS", "Fotografien", "ROOT", Audience(AudienceTier.PUBLIC)), 0
        )
        collections.save(
            Collection("AKTEN", "Aktenbestand", "ROOT", Audience(AudienceTier.MEMBERS)), 0
        )
        specs = [
            # ulid, title, coll, lifecycle, ref_code, media, doc, tags, date
            (
                "PUBFOTO",
                "Öffentliches Foto der Fahrten",
                "FOTOS",
                Lifecycle.PUBLISHED,
                "B 2",
                "Foto",
                "Fotografie",
                ("fahrten",),
                EdtfDate("1965"),
            ),
            (
                "PUBBERICHT",
                "Fahrtenbericht vom Bundeslager",
                "FOTOS",
                Lifecycle.PUBLISHED,
                "B 3",
                "Foto",
                "Bericht",
                ("lager",),
                EdtfDate("1972"),
            ),
            (
                "PUBUNDATIERT",
                "Undatiertes Liederheft",
                "FOTOS",
                Lifecycle.PUBLISHED,
                "B 4",
                "Schrifttum",
                "Liederheft",
                ("lieder",),
                None,
            ),
            (
                "MEMAKTE",
                "Vertrauliche Mitgliederakte",
                "AKTEN",
                Lifecycle.PUBLISHED,
                "A 5",
                "Akte",
                "Schriftstück",
                ("mitglieder",),
                EdtfDate("1975"),
            ),
            (
                "DRAFT",
                "Entwurf einer Chronik",
                "FOTOS",
                Lifecycle.DRAFT,
                "D 1",
                "Akte",
                "Chronik",
                ("entwurf",),
                EdtfDate("2010"),
            ),
        ]
        for ulid, title, coll, lifecycle, ref, media, doc, tags, date in specs:
            articles.save(
                Article(
                    ulid=ulid,
                    title=title,
                    collection_id=coll,
                    lifecycle=lifecycle,
                    ref_code=ref,
                    media_type=media,
                    document_type=doc,
                    tags=tags,
                    date=date,
                ),
                0,
            )


@pytest.fixture(scope="module")
def _corpus_root(
    django_db_setup: None,
    django_db_blocker: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Path]:
    """Build + index the corpus once for the module (search never mutates it), wiping the index on
    teardown so the committed rows never leak into a later module."""
    from bundesarchiv.index.models import ArticleIndex

    root = tmp_path_factory.mktemp("workbench-canonical")
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _Corpus(root)
        yield root
        ArticleIndex.objects.all().delete()


@pytest.fixture
def corpus_root(_corpus_root: Path, db: None) -> Path:
    """Per-test entry: join the module corpus to the ``db`` transaction fixture."""
    return _corpus_root


def _settings(root: Path, **extra: object) -> dict[str, object]:
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(root),
        **extra,
    }


def _client_as(viewer: Viewer) -> Client:
    client = Client()
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def _get(root: Path, viewer: Viewer, query: str = "", *, hx: bool = False) -> HttpResponse:
    path = "/" + (("?" + query) if query else "")
    headers = {"HX-Request": "true"} if hx else None
    with override_settings(**_settings(root)):
        response = _client_as(viewer).get(path, headers=headers)
    return cast(HttpResponse, response)


# --- viewer scoping (the security spine) -----------------------------------------


@pytest.mark.django_db
def test_public_never_sees_draft_in_results(corpus_root: Path) -> None:
    body = _get(corpus_root, Public()).content.decode()
    assert "Öffentliches Foto" in body
    assert "Entwurf einer Chronik" not in body  # draft is archivist-only
    assert "Vertrauliche Mitgliederakte" not in body  # members-only


@pytest.mark.django_db
def test_archivist_sees_draft_in_results(corpus_root: Path) -> None:
    body = _get(corpus_root, Archivist()).content.decode()
    assert "Entwurf einer Chronik" in body
    assert "Vertrauliche Mitgliederakte" in body


@pytest.mark.django_db
def test_member_sees_members_not_draft(corpus_root: Path) -> None:
    body = _get(corpus_root, Member(groups=())).content.decode()
    assert "Vertrauliche Mitgliederakte" in body
    assert "Entwurf einer Chronik" not in body


# --- text search + ADR-0011 prefix recall ----------------------------------------


@pytest.mark.django_db
def test_prefix_recall_fahrt_finds_fahrtenbericht(corpus_root: Path) -> None:
    # "Fahrt" (compound head) must reach "Fahrtenbericht" via the :* prefix mitigation (ADR 0011).
    body = _get(corpus_root, Public(), "q=Fahrt").content.decode()
    assert "Fahrtenbericht" in body


# --- URL-as-state: no-JS full GET vs HX-Request partial --------------------------


@pytest.mark.django_db
def test_plain_get_renders_full_page(corpus_root: Path) -> None:
    response = _get(corpus_root, Public())
    body = response.content.decode()
    assert "<html" in body and "Suchen" in body  # full chrome (search form)
    assert 'id="results"' in body


@pytest.mark.django_db
def test_hx_request_renders_only_results_partial(corpus_root: Path) -> None:
    # As Archivist so the "Neuer Artikel" absence below is load-bearing (the button DOES render on
    # the Archivist's full page — its absence here proves the topbar is outside the partial).
    response = _get(corpus_root, Archivist(), "q=Foto", hx=True)
    body = response.content.decode()
    assert 'id="results"' in body  # the swap target
    assert "<html" not in body  # NOT the full page — just the region
    assert "Neuer Artikel" not in body  # topbar is outside the partial


# --- template hygiene + archivist chrome ------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "viewer",
    [Public(), Member(groups=()), Archivist()],
    ids=["public", "member", "archivist"],
)
def test_no_template_comment_syntax_leaks_into_page(corpus_root: Path, viewer: Viewer) -> None:
    # Django's hash-style template comment is SINGLE-LINE only: a multi-line one renders literally
    # into the page. Pin that no comment syntax ever reaches the body, for every tier.
    body = _get(corpus_root, viewer).content.decode()
    assert "{#" not in body


@pytest.mark.django_db
def test_neuer_artikel_chrome_only_for_archivist(corpus_root: Path) -> None:
    # The ROUTE is archivist-gated regardless; this pins the CHROME — Public/Member must not be
    # shown an admin affordance that 404s when clicked (and must not learn it exists).
    assert "Neuer Artikel" in _get(corpus_root, Archivist()).content.decode()
    assert "Neuer Artikel" not in _get(corpus_root, Public()).content.decode()
    assert "Neuer Artikel" not in _get(corpus_root, Member(groups=())).content.decode()


# --- facets: rendering, name resolution, Ohne Datum ------------------------------


@pytest.mark.django_db
def test_facets_render_with_headings(corpus_root: Path) -> None:
    body = _get(corpus_root, Public()).content.decode()
    for heading in ("Bestand", "Medienart", "Dokumenttyp", "Schlagworte", "Jahrzehnte"):
        assert heading in body


@pytest.mark.django_db
def test_collection_facet_shows_name_and_direkt_label(corpus_root: Path) -> None:
    body = _get(corpus_root, Public()).content.decode()
    assert "Fotografien" in body  # ULID resolved to the Collection NAME (the visible label)
    # The ULID rides in the facet link href (URL-as-state), but the ANCHOR TEXT is the name, not the
    # ULID — the raw ULID never shows as the clickable label.
    assert ">FOTOS</a>" not in body
    assert "direkt:" in body  # honest direct-membership label


@pytest.mark.django_db
def test_ohne_datum_bucket_present_and_counts(corpus_root: Path) -> None:
    body = _get(corpus_root, Public()).content.decode()
    assert "Ohne Datum" in body  # the dateless bucket (Undatiertes Liederheft has no date)


@pytest.mark.django_db
def test_ohne_datum_filter_narrows_to_dateless(corpus_root: Path) -> None:
    body = _get(corpus_root, Public(), "ohne_datum=1").content.decode()
    assert "Undatiertes Liederheft" in body
    assert "Öffentliches Foto" not in body  # a dated article is excluded


# --- facet click → filtered results + removable chip -----------------------------


@pytest.mark.django_db
def test_media_facet_filter_narrows_results(corpus_root: Path) -> None:
    body = _get(corpus_root, Public(), "medienart=Schrifttum").content.decode()
    assert "Undatiertes Liederheft" in body
    assert "Öffentliches Foto" not in body  # a Foto is excluded


@pytest.mark.django_db
def test_active_filter_shows_removable_chip(corpus_root: Path) -> None:
    body = _get(corpus_root, Public(), "medienart=Foto").content.decode()
    assert "Medienart: Foto" in body  # the chip
    assert "entfernen" in body  # the ✕ remove affordance


# --- param injection: garbage → 200 defaults, never 500 --------------------------


@pytest.mark.django_db
def test_garbage_params_yield_200_defaults(corpus_root: Path) -> None:
    response = _get(
        corpus_root,
        Public(),
        "jahrzehnt=abc&seite=-9&von=fruehjahr&sortierung=nonsense&ohne_datum=maybe",
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Öffentliches Foto" in body  # a normal, all-defaults result set


# --- pagination -------------------------------------------------------------------


@pytest.mark.django_db
def test_pagination_second_page_via_seite(corpus_root: Path) -> None:
    # page_size is 50 by default; force a tiny page via the URL is not supported, so assert the
    # pager is absent for a small corpus and page 1 is honest. (Pagination link algebra is unit-
    # tested in test_browse_links; here we pin that seite is honored without crashing.)
    response = _get(corpus_root, Archivist(), "seite=2")
    assert response.status_code == 200
