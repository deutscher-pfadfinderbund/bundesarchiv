"""Minimal Django settings — deliberately kept tiny, forever (ADR 0004, 0005).

Django is present as a thin adapter (ADR 0004, 0005): the derived Postgres search index
plus the server-rendered workbench — templates, one CSRF middleware, a URLconf, and static
CSS/JS via staticfiles + WhiteNoise (ADR 0016). No admin, auth, or sessions.

The database is configured from the ``BUNDESARCHIV_PG_DSN`` environment variable so dev,
tests, and (later) the VPS all point at the same connection string. It defaults to the
local dev container published on ``localhost:5434`` (see README dev setup).
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.utils.csp import CSP

_DEFAULT_PG_DSN = "postgresql://postgres:postgres@localhost:5434/bundesarchiv"

# The web layer's template dir (Part 4.5 workbench). Kept as an explicit DIRS entry rather than
# APP_DIRS: ``app.web`` is not a Django app (ADR 0004/0005 — Django is an adapter), so templates are
# addressed by directory, not by app autodiscovery.
_WEB_TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"

# Same reason as the template dir above: ``app.web`` is not a Django app, so staticfiles finds these
# via ``STATICFILES_DIRS`` (ADR 0016).
_WEB_STATIC = Path(__file__).resolve().parent.parent / "app" / "web" / "static"


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

# What an HTTP-serving deploy cannot boot without. Enforced in ``wsgi.py`` — the entry point a real
# app server imports and neither ``runserver`` nor the test suite ever does — so serving fails loudly
# on a forgotten variable while dev and the suite need no environment at all. Both values below stay
# empty by default and are fail-closed in that state: Django raises on an empty SECRET_KEY the moment
# anything signs, and an empty ALLOWED_HOSTS rejects every request outside DEBUG.
REQUIRED_SERVING_ENV = ("BUNDESARCHIV_SECRET_KEY", "BUNDESARCHIV_ALLOWED_HOSTS")

SECRET_KEY = os.environ.get("BUNDESARCHIV_SECRET_KEY", "")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("BUNDESARCHIV_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

# Two proxies terminate and forward: Traefik does TLS, nginx passes its ``X-Forwarded-Proto`` on
# (deploy/nginx/nginx.conf). Without this Django reads every request as http and refuses each POST
# on the CSRF origin check against an https ``Referer``.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.postgres",
    "django.contrib.staticfiles",  # CSS/JS collected + served by WhiteNoise (ADR 0016)
    "procrastinate.contrib.django",  # Postgres-table-only worker queue (ADR 0014, Part 4.2)
    "bundesarchiv.index",
    # The application-service shell — installed so Procrastinate autodiscovers its ``tasks.py`` and
    # Django discovers the ``ensure_index_current`` command.
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

# A deliberately short stack — this bends the "tiny settings, no middleware" stance (ADR 0004), and
# every entry is here for a hole that has no other home. No SessionMiddleware (CsrfViewMiddleware
# uses the cookie token, CSRF_USE_SESSIONS=False; viewer auth is a separately-signed cookie, not a
# Django session), no auth/admin.
# CSRF protects the Part 4.7 write forms — create, edit-save, kopieren, loeschen, the media POSTs
# and the bulk apply are all POSTs, and without it those destructive POSTs accept cross-site
# requests despite their {% csrf_token %}.
# SecurityMiddleware is first because its request phase (the SECURE_* family) must precede anything
# that can answer, WhiteNoise second: it serves /static/* (ADR 0016) and short-circuits before CSRF.
# ...and the ADR 0018 anonymous gate, LAST: WhiteNoise short-circuits /static/* above it, and CSRF
# keeps its request-phase place ahead of it, so the gate only ever sees requests that are about to
# reach a view. It is the ONE place the app decides an unauthenticated request is not answered.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # SECURE_CSP below; above CSRF and the gate, so their refusals carry the policy too.
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "bundesarchiv.app.web.viewers.TokenCookieMiddleware",  # outside everything that calls viewer_of
    "bundesarchiv.app.web.anonymous_gate.AnonymousGateMiddleware",
]

# Authentication (ADR 0018): OIDC against the DPB Keycloak realm. The browser keeps Keycloak's tokens
# in two cookies; the server stores none — no Django sessions, no contrib.auth. Every value arrives
# from the deploy environment and every one of them is OPTIONAL HERE ON PURPOSE: absent settings must
# fall closed (nobody can log in, every token check fails -> Public). VIEWER_SIGNING_KEY signs the
# transient login cookie.
VIEWER_SIGNING_KEY = os.environ.get("BUNDESARCHIV_VIEWER_SIGNING_KEY") or None
OIDC_ISSUER = os.environ.get("BUNDESARCHIV_OIDC_ISSUER") or None
OIDC_CLIENT_ID = os.environ.get("BUNDESARCHIV_OIDC_CLIENT_ID") or None
OIDC_CLIENT_SECRET = os.environ.get("BUNDESARCHIV_OIDC_CLIENT_SECRET") or None

# The page policy; media keep their own ``sandbox`` (ADR 0017). Keycloak in form-action: ADR 0018.
_KEYCLOAK_ORIGINS = [f"{u.scheme}://{u.netloc}" for u in [urlparse(OIDC_ISSUER or "")] if u.netloc]
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:"],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "form-action": [CSP.SELF, *_KEYCLOAK_ORIGINS],
}

# The anonymous gate (ADR 0018): an anonymous request gets the door (the way to the login) instead of
# being answered. ON here, in the base settings, and disabled ONLY in ``settings_dev`` — the
# fail-closed direction: a production deploy that forgets its OIDC env vars still cannot fall open
# to anonymous browsing, its door leads to a login that itself falls closed.
ANONYMOUS_GATE_ENABLED = True

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

# The upload ceiling for the Part 4.7 media manager (spec §8): ONE number, 4 GiB by owner ruling
# (2026-09-19), enforced per file by the upload view, which turns an oversize file into a clean
# German error rather than a 500. Django's two memory settings keep their defaults on purpose —
# neither caps a file: DATA_UPLOAD_MAX_MEMORY_SIZE sizes the NON-file part of a request body, and
# FILE_UPLOAD_MAX_MEMORY_SIZE only picks where an upload moves from RAM to a temp file. nginx's
# client_max_body_size (deploy/nginx/nginx.conf) bounds the whole request instead, and is set higher
# so a batch of legal files never trips nginx's English 413 in place of this German error.
BUNDESARCHIV_MAX_UPLOAD_BYTES = int(
    os.environ.get("BUNDESARCHIV_MAX_UPLOAD_BYTES", str(4 * 1024**3))
)
# A generous ceiling on the number of form fields (the media manager renders one caption input per
# file); the default 1000 is fine for a v1 item, set explicitly so a large item never trips it.
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.environ.get("BUNDESARCHIV_MAX_FORM_FIELDS", "2000"))

# Static assets via staticfiles + WhiteNoise (ADR 0016); ``collectstatic`` is a deploy step. Manifest
# storage hashes names and makes {% static %} RAISE on a missing file. Dev overrides to non-manifest.
STATIC_URL = "/static/"
STATIC_ROOT = os.environ.get(
    "BUNDESARCHIV_STATIC_ROOT",
    str(Path(__file__).resolve().parent.parent.parent.parent / "var" / "static"),
)
STATICFILES_DIRS = [str(_WEB_STATIC)]
# STORAGES replaces Django's whole default dict, so ``default`` must be restated alongside the
# WhiteNoise staticfiles backend.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Completes the fail-loud: a hardcoded "/static/tokens.css" bypasses {% static %} and would
# otherwise serve from the unhashed copy. No-op under dev's non-manifest backend.
WHITENOISE_KEEP_ONLY_HASHED_FILES = True

# BigAutoField is the 6.0 default; the index model uses an explicit ULID text PK anyway.
USE_TZ = True

# Every log record is one JSON line on stdout (app, worker, gunicorn's error log; the format and its
# fields: docs/runbook.md "Logs"). `gunicorn.error` is named so gunicorn's own handler is replaced.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "bundesarchiv.app.jsonlog.JsonFormatter"}},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        }
    },
    "root": {"handlers": ["stdout"], "level": "INFO"},
    "loggers": {
        "gunicorn.error": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        # one line per WebDAV request would drown the one summary per mirror job (and name every key)
        "httpx2": {"level": "WARNING"},
    },
}
