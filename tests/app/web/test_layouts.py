"""Dev-only layout demo pages (``/_dev/layouts/<name>/``) — route + role-token discipline.

Same three seams the component library pins, applied to the layout demos:

- The layout routes render under DEV settings and do NOT resolve under the production URLconf:
  unreachable in prod by absence of a code path, not by a flag.
- The layout whitelist is the only way a name becomes routable (unknown name → 404), and the
  layout-stylesheet route serves ONLY the one whitelisted file (never an arbitrary static server).
- The layout css consumes ROLE tokens only (design-system.md: "a hex value in a component style is
  a defect"): the raw-color sweep from ``test_components`` is reused over ``layouts.css``.

The two server-rendered states (``?vorschau=0|1``) are asserted from the rendered HTML: the preview
pane markup is present only when the pane is open.
"""

from pathlib import Path

import pytest
from django.test import Client, override_settings
from django.urls import Resolver404, resolve
from tests.app.web.test_components import _RAW_COLOR

_WEB = Path(__file__).parents[3] / "src" / "bundesarchiv" / "app" / "web"
_LAYOUTS_CSS = _WEB / "static" / "layouts.css"

_DEV = {
    "ROOT_URLCONF": "bundesarchiv.app.web.dev_urls",
    "MIDDLEWARE": ["bundesarchiv.app.web.dev.DevViewerMiddleware"],
    "DEV_VIEWER_SIGNING_KEY": "test-layouts-dev-key",
}


# --- the dev-only layout routes -----------------------------------------------------


@override_settings(**_DEV)
def test_registered_layouts_render_under_dev_settings() -> None:
    from bundesarchiv.app.web.layouts_demo import LAYOUTS

    assert LAYOUTS, "at least one layout should be registered"
    client = Client()
    for name in LAYOUTS:
        page = client.get(f"/_dev/layouts/{name}/")
        assert page.status_code == 200, f"layout {name} should render"
        body = page.content.decode()
        assert "Layout demo" in body  # English dev chrome
        assert "Archiv durchsuchen" in body  # German product copy inside the atoms
        assert "components/ledger.html" not in body  # includes are resolved, not printed
        assert "{#" not in body  # template-comment hygiene, same rule as the workbench


@override_settings(**_DEV)
def test_unknown_layout_is_404() -> None:
    assert Client().get("/_dev/layouts/woven-nonsense/").status_code == 404


@override_settings(**_DEV)
def test_layout_routes_do_not_resolve_under_prod_urlconf() -> None:
    # Same discipline as the switcher / component library: dev-only by absence of a code path.
    for path in ("/_dev/layouts/split-rail/", "/_dev/layouts/static/layouts.css"):
        with pytest.raises(Resolver404):
            resolve(path, urlconf="bundesarchiv.app.web.urls")


# --- the two server-rendered states (?vorschau) -------------------------------------


@override_settings(**_DEV)
def test_preview_pane_present_only_when_open() -> None:
    client = Client()
    closed = client.get("/_dev/layouts/split-rail/").content.decode()
    opened = client.get("/_dev/layouts/split-rail/?vorschau=1").content.decode()
    assert 'class="wb-pane"' not in closed  # pane absent by default
    assert 'class="wb-pane"' in opened  # ?vorschau=1 renders the pane
    assert "wb--vorschau" in opened and "wb--vorschau" not in closed  # frame state class


@override_settings(**_DEV)
def test_layout_class_reflects_the_layout_name() -> None:
    client = Client()
    for name in ("split-rail", "split-narrow"):
        body = client.get(f"/_dev/layouts/{name}/").content.decode()
        assert f"wb--{name}" in body  # the frame carries its per-layout class


# --- the dev-only layout stylesheet route -------------------------------------------


@override_settings(**_DEV)
def test_layout_stylesheet_route_serves_only_the_whitelisted_file() -> None:
    from bundesarchiv.app.web.layouts_demo import LAYOUT_STYLESHEET

    client = Client()
    css = client.get(f"/_dev/layouts/static/{LAYOUT_STYLESHEET}")
    assert css.status_code == 200
    assert css["Content-Type"] == "text/css"
    # Anything else → 404, so the route can never become an arbitrary-static-file server.
    assert client.get("/_dev/layouts/static/anything-else.css").status_code == 404


# --- layout css consumes roles only -------------------------------------------------


def test_layout_css_carries_no_raw_color_values() -> None:
    assert _LAYOUTS_CSS.is_file(), f"layout stylesheet missing at {_LAYOUTS_CSS}"
    offenders = {
        f"{_LAYOUTS_CSS.name}: {match.group(0)!r}"
        for match in _RAW_COLOR.finditer(_LAYOUTS_CSS.read_text(encoding="utf-8"))
    }
    assert not offenders, (
        "raw color values in the layout stylesheet (role tokens only, design-system.md): "
        f"{sorted(offenders)}"
    )
