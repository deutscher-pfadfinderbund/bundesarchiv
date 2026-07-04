"""Minimal Django settings — deliberately kept tiny, forever (ADR 0004, 0005).

Django is present ONLY as an adapter for the derived Postgres search index. Nothing
here serves HTTP: no admin, auth, sessions, middleware, URLconf, templates, or static
files. The only installed apps are ``django.contrib.postgres`` (for ``ArrayField`` /
FTS / trigram expressions used by the index) and our own ``bundesarchiv.index``.

The database is configured from the ``BUNDESARCHIV_PG_DSN`` environment variable so dev,
tests, and (later) the VPS all point at the same connection string. It defaults to the
local dev container published on ``localhost:5434`` (see README dev setup).
"""

import os
from urllib.parse import unquote, urlparse

_DEFAULT_PG_DSN = "postgresql://postgres:postgres@localhost:5434/bundesarchiv"


def _databases_from_dsn(dsn: str) -> dict[str, dict[str, object]]:
    """Parse a libpq-style ``postgresql://`` URL into Django's DATABASES config.

    Kept dependency-free (no dj-database-url): the DSN shape is fixed and simple, and a
    decade-maintenance project prefers one obvious stdlib parse over an extra dependency.
    """
    url = urlparse(dsn)
    if url.scheme not in {"postgres", "postgresql"}:
        raise ValueError(f"BUNDESARCHIV_PG_DSN must be a postgresql:// URL, got: {dsn!r}")
    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(url.path.lstrip("/")),
            "USER": unquote(url.username or ""),
            "PASSWORD": unquote(url.password or ""),
            "HOST": url.hostname or "",
            "PORT": str(url.port or ""),
        }
    }


DATABASES = _databases_from_dsn(os.environ.get("BUNDESARCHIV_PG_DSN", _DEFAULT_PG_DSN))

INSTALLED_APPS = [
    "django.contrib.postgres",
    "bundesarchiv.index",
]

# BigAutoField is the 6.0 default; the index model uses an explicit ULID text PK anyway.
USE_TZ = True
