"""Component atoms + the dev-only component library page.

Three seams:

- The library route renders under DEV settings (all atoms + swatches in one document) — and does
  NOT resolve under the production URLconf: unreachable in prod by absence of a code path, the
  same discipline the switcher tests pin.
- The components-consume-ROLES-only rule (design-system.md: "a hex value in a component style is
  a defect"): a grep-style sweep over templates/components/*.html AND static/components.css for
  raw color values (hex, oklch(, rgb(/rgba(, hsl(/hsla(). color-mix() over role tokens is
  allowed — it mixes roles, it does not introduce a color.
- The sweep fails loudly if the component directory is missing or unexpectedly empty — an empty
  glob must never pass as "no raw colors found".
"""

import re
from pathlib import Path

import pytest
from django.test import Client, override_settings
from django.urls import Resolver404, resolve

_WEB = Path(__file__).parents[3] / "src" / "bundesarchiv" / "app" / "web"
_COMPONENTS_DIR = _WEB / "templates" / "components"
_COMPONENTS_CSS = _WEB / "static" / "components.css"
#: The Part 4.7 cataloging-form stylesheet — a component stylesheet under the same roles-only law, so
#: it joins the raw-color sweep (spec §4/§6 owner decision: one shared file, token terms only).
_FORMS_CSS = _WEB / "static" / "forms.css"

#: Every atom the design-system brief names — the sweep must see at least these.
_EXPECTED_ATOMS = frozenset(
    {
        "button.html",
        "input.html",
        "select.html",
        "chip.html",
        "badge_lifecycle.html",
        "badge_visibility.html",
        "signatur_tab.html",
        "facet_group.html",
        "card.html",
        "ledger.html",
        "ledger_row.html",
        "pagination.html",
        "empty_state.html",
    }
)

_DEV = {
    "ROOT_URLCONF": "bundesarchiv.app.web.dev_urls",
    "MIDDLEWARE": ["bundesarchiv.app.web.dev.DevViewerMiddleware"],
    "DEV_VIEWER_SIGNING_KEY": "test-components-dev-key",
}

#: Raw color values, any of which in a component file is a defect. Hex needs 3+ hex digits so
#: demo anchors like href="#" stay legal; the function forms catch oklch/rgb/hsl and their
#: alpha variants. var(--…) and color-mix(…) do not match — they carry roles, not colors.
#: The bare CSS named colors black/white are caught too (a color-mix over a role must mix another
#: role, not a raw color) — but ``(?!-)`` spares ``white-space`` etc. (a named color as a value is
#: never followed by a hyphen).
_RAW_COLOR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\boklch\(|\brgba?\(|\bhsla?\(|\b(?:black|white)\b(?!-)",
    re.IGNORECASE,
)


# --- the dev-only library route ---------------------------------------------------


@override_settings(**_DEV)
def test_component_library_renders_under_dev_settings() -> None:
    response = Client().get("/_dev/components/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Component library" in body  # English dev chrome
    assert "Archiv durchsuchen" in body  # German product copy inside the atoms
    assert "components/button.html" in body  # include-path annotations (self-documentation)
    assert "components/ledger.html" in body  # the ledger organism is on the page too
    assert "{#" not in body  # template-comment hygiene, same rule as the workbench


def test_component_library_route_does_not_resolve_under_prod_urlconf() -> None:
    # Same discipline as the switcher: dev-only by absence of a code path, not by a flag.
    with pytest.raises(Resolver404):
        resolve("/_dev/components/", urlconf="bundesarchiv.app.web.urls")


# --- design-variant routes ----------------------------------------------------------


@override_settings(**_DEV)
def test_baseline_links_the_baseline_stylesheet() -> None:
    body = Client().get("/_dev/components/").content.decode()
    assert '<link rel="stylesheet" href="/static/components.css">' in body


@override_settings(**_DEV)
def test_whitelisted_variant_renders_with_its_stylesheet(monkeypatch: pytest.MonkeyPatch) -> None:
    from bundesarchiv.app.web import components_demo

    monkeypatch.setattr(components_demo, "VARIANTS", {"probe": "components-probe.css"})
    response = Client().get("/_dev/components/probe/")
    assert response.status_code == 200
    body = response.content.decode()
    assert '<link rel="stylesheet" href="/_dev/static/components-probe.css">' in body
    assert ">probe</a>" in body  # the variant-switcher nav lists the registered variant


@override_settings(**_DEV)
def test_unknown_variant_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from bundesarchiv.app.web import components_demo

    monkeypatch.setattr(components_demo, "VARIANTS", {"probe": "components-probe.css"})
    assert Client().get("/_dev/components/woven-nonsense/").status_code == 404


@override_settings(**_DEV)
def test_variant_stylesheet_route_serves_only_whitelisted_files() -> None:
    # Not registered -> 404; the route can never become an arbitrary-static-file server.
    assert Client().get("/_dev/static/anything-else.css").status_code == 404


def test_variant_routes_do_not_resolve_under_prod_urlconf() -> None:
    for path in ("/_dev/components/papier/", "/_dev/static/components-papier.css"):
        with pytest.raises(Resolver404):
            resolve(path, urlconf="bundesarchiv.app.web.urls")


@override_settings(**_DEV)
def test_registered_variants_render_and_serve_their_css() -> None:
    from bundesarchiv.app.web.components_demo import VARIANTS

    assert VARIANTS, "at least one design variant should be registered"
    client = Client()
    for name, filename in VARIANTS.items():
        page = client.get(f"/_dev/components/{name}/")
        assert page.status_code == 200, f"variant page {name} should render"
        assert f'href="/_dev/static/{filename}"' in page.content.decode()
        css = client.get(f"/_dev/static/{filename}")
        assert css.status_code == 200, f"variant css {filename} should be served"
        assert css["Content-Type"] == "text/css"


# --- components consume roles only -------------------------------------------------


def _component_files() -> list[Path]:
    files = sorted(_COMPONENTS_DIR.glob("*.html"))
    present = {f.name for f in files}
    missing = _EXPECTED_ATOMS - present
    assert not missing, f"component atoms missing from {_COMPONENTS_DIR}: {sorted(missing)}"
    # Variant stylesheets (static/components-*.css) are components too — every registered AND
    # every on-disk variant css joins the sweep, so an experiment cannot smuggle raw colors.
    variant_css = sorted(_COMPONENTS_CSS.parent.glob("components-*.css"))
    assert _FORMS_CSS.is_file(), f"forms.css missing from {_FORMS_CSS.parent} (Part 4.7)"
    return [*files, _COMPONENTS_CSS, _FORMS_CSS, *variant_css]


def test_components_carry_no_raw_color_values() -> None:
    offenders = {
        f"{path.name}: {match.group(0)!r}"
        for path in _component_files()
        for match in _RAW_COLOR.finditer(path.read_text(encoding="utf-8"))
    }
    assert not offenders, (
        "raw color values in component files (components consume ROLE tokens only, "
        f"design-system.md): {sorted(offenders)}"
    )
