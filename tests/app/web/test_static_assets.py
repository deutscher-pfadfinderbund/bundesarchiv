"""Static-assets wiring regressions (ADR 0016): the prod/dev storage split must stay honest.

The web layer serves CSS/JS through django.contrib.staticfiles + WhiteNoise. Prod (this test
gate's settings) uses the manifest storage — hashed names, immutable caching, and a {% static %}
that RAISES on a missing file (fail loud). Dev overrides to the non-manifest backend for runserver
ergonomics. Because ``settings_dev`` does ``from settings import *``, its STORAGES is the SAME dict
object as prod's until it rebinds it; an in-place mutation would silently flip the whole test
process (imported at collection time by conftests) to non-manifest and disarm the fail-loud gate.
"""

from bundesarchiv.index import settings as prod_settings
from bundesarchiv.index import settings_dev

_MANIFEST = "whitenoise.storage.CompressedManifestStaticFilesStorage"
_PLAIN = "django.contrib.staticfiles.storage.StaticFilesStorage"


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
