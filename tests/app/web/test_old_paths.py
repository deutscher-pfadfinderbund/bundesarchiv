"""The German paths of before 2026-10-01 stay as aliases of the English ones
(owner-interview-2026-08.md, "Ruling of 2026-10-01 (URLs)"): same view, no redirect. The English
path is canonical: it is the only one ``reverse`` can yield."""

import pytest
from django.test import override_settings
from django.urls import URLPattern, resolve, reverse
from tests.app.web._asserts import assert_door
from tests.app.web._fixtures import Corpus, client_as

from bundesarchiv.app.web.urls import urlpatterns

_U = "01HZX3K8M2N4P6Q8R0S2T4V6W8"

_OLD_TO_NEW = {
    "/artikel/neu": "/articles/new",
    f"/artikel/{_U}": f"/articles/{_U}",
    f"/artikel/{_U}/bearbeiten": f"/articles/{_U}/edit",
    f"/artikel/{_U}/kopieren": f"/articles/{_U}/copy",
    f"/artikel/{_U}/loeschen": f"/articles/{_U}/delete",
    f"/artikel/{_U}/veroeffentlichen": f"/articles/{_U}/publish",
    f"/artikel/{_U}/dokumenttypen": f"/articles/{_U}/document-types",
    f"/artikel/{_U}/medien/verschieben": f"/articles/{_U}/media/move",
    f"/artikel/{_U}/medien/entfernen": f"/articles/{_U}/media/remove",
    f"/artikel/{_U}/medien/hochladen": f"/articles/{_U}/media/upload",
    f"/artikel/{_U}/restore": f"/articles/{_U}/restore",
    f"/artikel/{_U}/delete-permanently": f"/articles/{_U}/delete-permanently",
    "/artikel/sammelbearbeitung": "/articles/bulk-edit",
    "/artikel/sammelbearbeitung/dokumenttypen": "/articles/bulk-edit/document-types",
    "/bestand/neu": "/collections/new",
    f"/bestand/{_U}/bearbeiten": f"/collections/{_U}/edit",
    "/spalten": "/columns",
}


@pytest.mark.parametrize(("old", "new"), _OLD_TO_NEW.items())
def test_an_old_path_reaches_the_view_of_its_english_path(old: str, new: str) -> None:
    assert resolve(old).func is resolve(new).func
    assert resolve(old).kwargs == resolve(new).kwargs


def test_the_alias_table_above_is_every_alias() -> None:
    aliases = {r.name for r in urlpatterns if (r.name or "").startswith("alias-")}
    assert len(aliases) == len(_OLD_TO_NEW)


def test_reverse_yields_the_english_path_for_every_route() -> None:
    for route in urlpatterns:
        assert isinstance(route, URLPattern)
        if (route.name or "").startswith("alias-"):
            continue
        args = [_U] * str(route.pattern).count("<")
        assert not reverse(str(route.name), args=args).startswith(
            ("/artikel", "/bestand", "/spalten")
        )


@pytest.mark.parametrize("old", _OLD_TO_NEW)
def test_an_anonymous_visitor_gets_the_door_on_an_old_path(corpus: Corpus, old: str) -> None:
    with override_settings(ANONYMOUS_GATE_ENABLED=True):
        assert_door(client_as(None).get(old), old)
