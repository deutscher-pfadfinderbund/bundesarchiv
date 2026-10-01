"""The pages Django renders outside any view: a refused CSRF check, an uncaught error and an
unmatched path. All render without a database or request state, and repeat nothing the request carried."""

import pytest
from django.urls import reverse
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import PUBLISHED_ULID, client_as

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.viewer import Archivist

_TYPED = "Quisenberry-Zephyroth"


@pytest.mark.usefixtures("corpus")
def test_a_refused_form_gets_the_expired_page_and_repeats_nothing() -> None:
    response = client_as(Archivist(), enforce_csrf=True).post(
        f"/collections/new?q={_TYPED}", {"name": _TYPED}
    )
    assert response.status_code == 403
    body = response.content.decode()
    assert f'href="{reverse("workbench")}"' in body
    assert _TYPED not in body
    assert "/collections/new" not in body


@pytest.mark.usefixtures("corpus")
def test_an_uncaught_error_gets_the_error_page_and_repeats_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> Archive:
        raise RuntimeError(_TYPED)

    monkeypatch.setattr(Archive, "canonical", fail)
    client = client_as(Archivist())
    client.raise_request_exception = False
    response = client.get(f"/articles/{PUBLISHED_ULID}/edit?q={_TYPED}")
    assert response.status_code == 500
    body = response.content.decode()
    assert f'href="{reverse("workbench")}"' in body
    assert _TYPED not in body
    assert PUBLISHED_ULID not in body


@pytest.mark.usefixtures("corpus")
def test_an_unmatched_path_gets_the_same_page_as_a_deny_and_repeats_nothing() -> None:
    response = client_as(Archivist()).get(f"/no/such/page?q={_TYPED}")
    assert_denied(response)
    body = response.content.decode()
    assert "Nicht gefunden" in body
    assert f'href="{reverse("workbench")}"' in body
    assert _TYPED not in body
    assert "/no/such/page" not in body
