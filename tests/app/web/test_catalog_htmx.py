"""HTMX enhancement endpoint (Part 4.7 Slice E, spec §5).

``/articles/<ulid>/document-types?media_type=`` → the Dokumenttyp option list for one Medienart, the
partial the edit form's HTMX layer swaps in (the no-JS baseline renders the same content
server-side and is unchanged).

It is archivist-gated via _load_gated → 404 for Member/Public/anon/malformed/absent,
and must NEVER render partial content for a non-archivist (content-absence asserts — they join the
4.10 leak suite). A pure transform; no mutation. Plus the state-H index-lag hinweis on the save path.
"""

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import DRAFT_ULID, PUB, Corpus, client_as

from bundesarchiv.app.web import vocab
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- /dokumenttypen ----------------------------------------------------------------


def test_document_types_returns_options_for_media_type(corpus: Corpus) -> None:
    response = client_as(Archivist()).get(
        f"/articles/{DRAFT_ULID}/document-types?media_type=Foto(s)"
    )
    assert response.status_code == 200
    assert "Zeitschrift" in response.content.decode()  # a Foto(s) Dokumenttyp


def test_document_types_unknown_media_type_yields_only_empty_option(corpus: Corpus) -> None:
    response = client_as(Archivist()).get(
        f"/articles/{DRAFT_ULID}/document-types?media_type=gibtsnicht"
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "kein Dokumenttyp" in body
    every_type = {t for types in vocab.MEDIA_TYPE_DOCUMENT_TYPES.values() for t in types}
    assert not {t for t in every_type if f'value="{t}"' in body}


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_document_types_denied_is_404_never_content(corpus: Corpus, viewer: Viewer) -> None:
    response = client_as(viewer).get(f"/articles/{DRAFT_ULID}/document-types?media_type=Foto(s)")
    assert_denied(response)
    assert b'value="Zeitschrift"' not in response.content  # no partial content leaked


def test_document_types_post_is_404(corpus: Corpus) -> None:
    assert (
        client_as(Archivist())
        .post(f"/articles/{DRAFT_ULID}/document-types", {"media_type": "Foto(s)"})
        .status_code
        == 404
    )


@pytest.mark.parametrize(
    "path",
    [
        "/articles/not-a-ulid/document-types?media_type=Foto(s)",
        "/articles/01BX5ZZKBKACTAV9WEVGEMMVRZ/document-types?media_type=Foto(s)",  # well-formed absent
    ],
)
def test_htmx_endpoints_malformed_or_absent_ulid_is_404(corpus: Corpus, path: str) -> None:
    response = client_as(Archivist()).get(path)
    assert_denied(response)


# --- HTMX save path (no-JS baseline unchanged) --------------------------------------


def _save_post(corpus: Corpus) -> dict[str, str]:
    """The edit form's metadata POST for the draft, at its current version so CAS passes."""
    return {
        "title": "Lagerchronik",
        "collection_id": PUB,
        "media_type": "Foto(s)",
        "expected_version": str(corpus.articles.load(DRAFT_ULID).version),
    }


def test_htmx_save_success_sends_hx_redirect(corpus: Corpus) -> None:
    # An HTMX save (HX-Request header) that succeeds returns 204 + HX-Redirect (htmx navigates), not
    # a 302 — the destination is identical to the no-JS path, only the mechanism differs.
    response = client_as(Archivist()).post(
        f"/articles/{DRAFT_ULID}/edit",
        _save_post(corpus),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 204
    assert response["HX-Redirect"] == f"/articles/{DRAFT_ULID}"
