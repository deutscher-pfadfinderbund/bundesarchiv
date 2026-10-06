"""Static-assets wiring regressions (ADR 0016): the prod/dev staticfiles storage split.

Prod (this gate) uses manifest storage — hashed names, fail-loud {% static %}; dev overrides to the
plain backend. See ``settings_dev`` for the rebind-not-mutate trap the rebind test guards.
"""

from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.test import Client

from bundesarchiv.index import settings as prod_settings
from bundesarchiv.index import settings_dev

_MANIFEST = "whitenoise.storage.CompressedManifestStaticFilesStorage"
_PLAIN = "django.contrib.staticfiles.storage.StaticFilesStorage"

#: The public-by-design asset set — WhiteNoise serves every one of these to anonymous users. A
#: private file dropped under the static dir must turn this red (it replaces the leak-matrix rows).
_KNOWN_ASSETS = frozenset(
    {
        "catalog_bulk.js",
        "catalog_form.js",
        "components.css",
        "detail.css",
        "error_banner.js",
        "forms.css",
        "htmx.min.js",
        "hx-browser-indicator.min.js",
        "layouts.css",
        "list_address.js",
        "media.js",
        "menu.js",
        "theme.js",
        "tokens.css",
    }
)


def test_dev_uses_non_manifest_storage() -> None:
    assert settings_dev.STORAGES["staticfiles"]["BACKEND"] == _PLAIN


def test_settings_dev_rebinds_rather_than_mutating_prod_storages() -> None:
    """settings_dev must REBIND STORAGES — mutating prod's dict disarms the fail-loud gate."""
    assert prod_settings.STORAGES is not settings_dev.STORAGES
    assert prod_settings.STORAGES["staticfiles"]["BACKEND"] == _MANIFEST


# --- /static/ is public-by-design (WhiteNoise middleware, not a urlconf route) --------------------
# WhiteNoise answers before any viewer resolution, so an anonymous client is the honest probe.


def test_static_dir_is_exactly_the_known_whitelist() -> None:
    """Dotfiles are excluded to match collectstatic's default ``.*`` ignore pattern."""
    static_dir = Path(settings.STATICFILES_DIRS[0])
    on_disk = {
        p.relative_to(static_dir).as_posix()
        for p in static_dir.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    }
    assert on_disk == set(_KNOWN_ASSETS)


def test_collected_asset_is_served_200() -> None:
    url = staticfiles_storage.url("tokens.css")
    assert url != "/static/tokens.css", "manifest storage should hash the name"
    assert Client().get(url).status_code == 200


def test_uncollected_static_path_is_not_served() -> None:
    assert Client().get("/static/nope-not-an-asset.css").status_code != 200


def test_unhashed_path_of_a_real_asset_is_not_served() -> None:
    """A real asset's UNHASHED path does not serve (WHITENOISE_KEEP_ONLY_HASHED_FILES, ADR 0016)."""
    assert Client().get("/static/tokens.css").status_code != 200
