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
from pathlib import Path
from urllib.parse import unquote, urlparse

_DEFAULT_PG_DSN = "postgresql://postgres:postgres@localhost:5434/bundesarchiv"

# The web layer's template dir (Part 4.5 workbench). Kept as an explicit DIRS entry rather than
# APP_DIRS: ``app.web`` is not a Django app (ADR 0004/0005 — Django is an adapter), so templates are
# addressed by directory, not by app autodiscovery.
_WEB_TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"


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
    "procrastinate.contrib.django",  # Postgres-table-only worker queue (ADR 0014, Part 4.2)
    "bundesarchiv.index",
    # The application-service shell — installed so Procrastinate autodiscovers its ``tasks.py`` and
    # Django discovers the ``ensure_index_current`` command. Its ``__init__`` resolves the service
    # functions lazily (PEP 562), so app-``populate()`` never imports the ORM model early.
    "bundesarchiv.app",
]

# The canonical files-store root (ADR 0005). Worker jobs are references — they carry only a ulid —
# so a job re-reads canonical truth from THIS store at execution (ADR 0014). Defaults to a local
# dev path; the VPS deploy points it at the real archive root.
BUNDESARCHIV_CANONICAL_ROOT = os.environ.get("BUNDESARCHIV_CANONICAL_ROOT", "var/canonical")

# Procrastinate scheduled reconcile (ADR 0014): a periodic full rebuild that bounds every missed
# incremental update. Hourly by default — the rebuild is seconds at this archive's scale, so hourly
# keeps the worst-case staleness window at an hour, matching the archive's own risk language. Cron
# expression, overridable by the deploy for a different cadence.
BUNDESARCHIV_RECONCILE_CRON = os.environ.get("BUNDESARCHIV_RECONCILE_CRON", "0 * * * *")

# The production HTTP surface (Part 4.3): the authorized media-serving routes and nothing else.
# Prod stays deliberately minimal (ADR 0004/0005) — no admin/auth/sessions/templates. The dev
# viewer switcher is NOT here (it lives in settings_dev, which composes these prod routes WITH the
# switcher); prod is unreachable-by-absence for anything dev-only.
ROOT_URLCONF = "bundesarchiv.app.web.urls"

# Templates for the server-rendered workbench (Part 4.5). The Django template backend only — no
# context processors that need auth/sessions (this project has none): the viewer is passed in the
# view's context, never read from ``request.user``. Autoescape is on (the default), so German UI
# strings and index values render safely.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(_WEB_TEMPLATES)],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": []},
    }
]

# Media-serving seam config (Part 4.3, roadmap "Media authorization"). When set (prod behind nginx),
# ``media_response`` returns an X-Accel-Redirect to ``<prefix>/<store-relative blob path>`` and nginx
# serves the bytes from an ``internal;`` location over the media tree (handling Range itself); the
# media tree is never web-root reachable. When UNSET (dev, no nginx), the seam streams the blob
# directly via FileResponse. Kept as ONE setting behind the ``media_response`` seam so the Part 7
# tiering miss-path can grow there without any caller learning where bytes live (roadmap rule).
BUNDESARCHIV_X_ACCEL_PREFIX = os.environ.get("BUNDESARCHIV_X_ACCEL_PREFIX") or None

# The LOCAL derived thumbnail cache root (Part 4.3). Thumbnails are content-hash-keyed WebP files
# regenerated by a worker job from canonical blobs: NOT the ObjectStore, NOT canonical, NOT mirrored,
# NOT backed up, and freely prunable (README runbook). Defaults to a local dev path; the deploy
# points it at a cache dir on the same host that serves media.
BUNDESARCHIV_THUMBNAIL_ROOT = os.environ.get("BUNDESARCHIV_THUMBNAIL_ROOT", "var/thumbnails")

# WebDAV mirror (Part 4.9) — an OPTIONAL, browse-only convenience copy of the canonical store on a
# Nextcloud/WebDAV endpoint. It is NEVER a read path and NEVER counted as durability (restic is the
# backup; roadmap rule, changed only by Part 7 tiering). UNSET is the common dev case: when
# ``BUNDESARCHIV_MIRROR_DAV_URL`` is empty, ALL mirror machinery no-ops cleanly (no store is built,
# no jobs enqueue, the reconcile is a no-op). Credentials are read from env alongside the URL.
BUNDESARCHIV_MIRROR_DAV_URL = os.environ.get("BUNDESARCHIV_MIRROR_DAV_URL") or None
BUNDESARCHIV_MIRROR_DAV_USER = os.environ.get("BUNDESARCHIV_MIRROR_DAV_USER") or None
BUNDESARCHIV_MIRROR_DAV_PASSWORD = os.environ.get("BUNDESARCHIV_MIRROR_DAV_PASSWORD") or None

# The scheduled mirror reconcile cadence (Part 4.9): a periodic full sweep that re-pushes anything
# the async replay missed and deletes mirror-only stragglers, so the mirror self-heals. Daily by
# default — the mirror is a convenience, so a coarser cadence than the hourly index reconcile is
# right (a briefly-stale browse copy harms nothing). Cron expression, overridable by the deploy.
BUNDESARCHIV_MIRROR_RECONCILE_CRON = os.environ.get(
    "BUNDESARCHIV_MIRROR_RECONCILE_CRON", "0 3 * * *"
)

# BigAutoField is the 6.0 default; the index model uses an explicit ULID text PK anyway.
USE_TZ = True
