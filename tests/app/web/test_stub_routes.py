"""Detail-stub auth discipline for the workbench (Part 4.5-MVP).

``/artikel/<ulid>`` (``artikel-detail``) is the result-link target, a STUB for 4.6 that registers
its URL name now and — critically — ships its VISIBILITY GATE with the workbench, not after it. It
applies the SAME rule the real detail view will: load + resolve the chain + ``can_view``; any deny
(forbidden article, missing article, malformed ulid, broken chain) collapses to a plain 404 with
no leaked content (existence-hiding; the byte-identical-404 law was relaxed by the owner, 2026-08).

``/artikel/neu`` serves the real create form; its archivist gate is pinned by
``test_catalog_create.py``.

These are pure request-handling against a local FS store (load + resolve + can_view) — no Postgres,
so they run with no container (no DB fixture, hence no derived ``requires_pg`` marker).
"""

from collections.abc import Callable

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as, make_article, make_collection

from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public

PUBLIC_COLLECTION = new_ulid()
MEMBERS_COLLECTION = new_ulid()

PUBLIC_ARTICLE = new_ulid()
MEMBERS_ARTICLE = new_ulid()
DRAFT_ARTICLE = new_ulid()


@pytest.fixture
def tiered(make_corpus: Callable[[], Corpus]) -> Corpus:
    """A tiny FS-store archive: one public-published, one members-only, one draft article, each in a
    tiered Collection — enough to exercise the detail stub's can_view gate per viewer."""
    corpus = make_corpus()
    corpus.add_collection(
        make_collection(PUBLIC_COLLECTION, "Public", audience=Audience(AudienceTier.PUBLIC))
    )
    corpus.add_collection(
        make_collection(MEMBERS_COLLECTION, "Members", audience=Audience(AudienceTier.MEMBERS))
    )
    corpus.add_article(
        make_article(PUBLIC_ARTICLE, collection_id=PUBLIC_COLLECTION, title="public Artikel")
    )
    corpus.add_article(
        make_article(MEMBERS_ARTICLE, collection_id=MEMBERS_COLLECTION, title="members Artikel")
    )
    corpus.add_article(
        make_article(
            DRAFT_ARTICLE,
            collection_id=PUBLIC_COLLECTION,
            lifecycle=Lifecycle.DRAFT,
            title="draft Artikel",
        )
    )
    return corpus


# --- /artikel/<ulid> (detail stub, can_view gated) -------------------------------


def test_detail_served_when_can_view(tiered: Corpus) -> None:
    # the gate serves the real 4.6 detail page (the full render is covered by test_detail.py; here we
    # only prove the can_view gate opens for a viewable article).
    response = client_as(Public()).get(f"/artikel/{PUBLIC_ARTICLE}")
    assert response.status_code == 200
    assert "public Artikel" in response.content.decode()  # the article's title renders


def test_detail_stub_denies_forbidden_article_with_404(tiered: Corpus) -> None:
    # A members-only article, viewed as Public → 404, like a nonexistent one (existence-hiding).
    response = client_as(Public()).get(f"/artikel/{MEMBERS_ARTICLE}")
    assert_denied(response)


def test_detail_stub_denies_draft_to_member(tiered: Corpus) -> None:
    response = client_as(Member(groups=())).get(f"/artikel/{DRAFT_ARTICLE}")
    assert_denied(response)


def test_detail_stub_archivist_sees_draft(tiered: Corpus) -> None:
    response = client_as(Archivist()).get(f"/artikel/{DRAFT_ARTICLE}")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "ulid",
    ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"],  # malformed, then well-formed-but-absent
)
def test_detail_stub_malformed_or_missing_is_404(tiered: Corpus, ulid: str) -> None:
    response = client_as(Archivist()).get(f"/artikel/{ulid}")
    assert_denied(response)
