"""Static-assets wiring regressions (ADR 0016): the prod/dev storage split must stay honest.

The web layer serves CSS/JS through django.contrib.staticfiles + WhiteNoise. Prod (this test
gate's settings) uses the manifest storage — hashed names, immutable caching, and a {% static %}
that RAISES on a missing file (fail loud). Dev overrides to the non-manifest backend for runserver
ergonomics. Because ``settings_dev`` does ``from settings import *``, its STORAGES is the SAME dict
object as prod's until it rebinds it; an in-place mutation would silently flip the whole test
process (imported at collection time by conftests) to non-manifest and disarm the fail-loud gate.
"""

from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.test import Client

from bundesarchiv.index import settings as prod_settings
from bundesarchiv.index import settings_dev

_MANIFEST = "whitenoise.storage.CompressedManifestStaticFilesStorage"
_PLAIN = "django.contrib.staticfiles.storage.StaticFilesStorage"

#: The complete, public-by-design asset set WhiteNoise collects from the web package's static/ dir
#: and serves to EVERY viewer. This whitelist is the fail-loud analog of the deleted leak-matrix
#: static rows: a private file added under the static dir (which WhiteNoise would then serve to
#: anonymous users) turns ``test_static_dir_is_exactly_the_known_whitelist`` red. Paths are
#: static-dir-relative POSIX so a file added in a subdirectory is caught too, not just top-level.
_KNOWN_ASSETS = frozenset(
    {
        "catalog_bulk.js",
        "catalog_form.js",
        "components-papier.css",
        "components.css",
        "detail.css",
        "forms.css",
        "htmx.min.js",
        "layouts.css",
        "ledger_pane.js",
        "tokens.css",
    }
)


def test_prod_uses_manifest_storage() -> None:
    """Prod (= the test gate) uses WhiteNoise's manifest storage so {% static %} fails loud."""
    assert prod_settings.STORAGES["staticfiles"]["BACKEND"] == _MANIFEST


def test_dev_uses_non_manifest_storage() -> None:
    """Dev overrides to the plain backend so ``runserver`` needs no collectstatic."""
    assert settings_dev.STORAGES["staticfiles"]["BACKEND"] == _PLAIN


def test_settings_dev_rebinds_rather_than_mutating_prod_storages() -> None:
    """The aliasing trap: settings_dev must REBIND STORAGES, never mutate prod's shared dict in
    place. If it mutated, both would be the same object and prod would read non-manifest — the whole
    gate would stop enforcing ADR 0016's fail-loud {% static %}."""
    assert prod_settings.STORAGES is not settings_dev.STORAGES
    assert prod_settings.STORAGES["staticfiles"]["BACKEND"] == _MANIFEST


# --- /static/ is public-by-design (WhiteNoise middleware, not a urlconf route) --------------------
# The leak matrix (test_leak_matrix.py) walks the urlconf and can no longer see /static/*; these
# tests are its replacement for the static surface (ADR 0016). WhiteNoise serves /static/ BEFORE any
# viewer resolution (it is the first middleware), so serving is structurally viewer-independent — a
# plain anonymous client is the honest probe (a per-tier loop would only re-issue identical anonymous
# requests under the prod settings this gate runs, since no DevViewerMiddleware reads the cookie).


def test_static_dir_is_exactly_the_known_whitelist() -> None:
    """Every file WhiteNoise collects + serves to anonymous users is a known, public-by-design asset.
    A private file added anywhere under the static dir turns this red (the analog of the deleted
    matrix rows). Dotfiles are excluded to match collectstatic's default ``.*`` ignore pattern."""
    static_dir = Path(settings.STATICFILES_DIRS[0])
    on_disk = {
        p.relative_to(static_dir).as_posix()
        for p in static_dir.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    }
    assert on_disk == set(_KNOWN_ASSETS)


def test_collected_asset_is_served_200() -> None:
    """A collected asset is served (WhiteNoise, from STATIC_ROOT), at its manifest-hashed URL."""
    url = staticfiles_storage.url("tokens.css")
    assert url != "/static/tokens.css", "manifest storage should hash the name"
    assert Client().get(url).status_code == 200


def test_uncollected_static_path_is_not_served() -> None:
    """A /static/ path that was never collected is not served (WhiteNoise passes it through to
    Django's default 404), so /static/ exposes only the collected, public-by-design assets."""
    assert Client().get("/static/nope-not-an-asset.css").status_code != 200


def test_unhashed_path_of_a_real_asset_is_not_served() -> None:
    """The fail-loud completed: only the manifest-HASHED URL of a real asset serves.

    ``{% static %}`` raising on a missing asset only protects refs that go through the template tag;
    a hardcoded ``/static/tokens.css`` bypasses it entirely. With
    ``WHITENOISE_KEEP_ONLY_HASHED_FILES`` (ADR 0016) collectstatic keeps no unhashed copy, so such a
    ref 404s in prod instead of quietly working — and prod stops shipping two copies of every
    asset (plus their gzip/brotli variants)."""
    assert Client().get("/static/tokens.css").status_code != 200
