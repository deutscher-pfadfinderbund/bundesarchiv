"""Django settings, kept small (ADR 0004, ADR 0005)."""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.utils.csp import CSP

_DEFAULT_PG_DSN = "postgresql://postgres:postgres@localhost:5434/bundesarchiv"

# ``app.web`` is not a Django app (ADR 0004), so its templates are found by directory, not
# APP_DIRS.
_WEB_TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"

# Same reason as the template dir above: ``app.web`` is not a Django app, so staticfiles finds these
# via ``STATICFILES_DIRS`` (ADR 0016).
_WEB_STATIC = Path(__file__).resolve().parent.parent / "app" / "web" / "static"

# The one default for gunicorn's thread count: deploy/gunicorn.conf.py reads it from here.
GUNICORN_THREADS = int(os.environ.get("GUNICORN_THREADS") or "8")


def _databases_from_dsn(dsn: str) -> dict[str, dict[str, object]]:
    """No dj-database-url on purpose: the DSN shape is fixed."""
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
            # A pooled connection may have died with a Postgres restart: check it before handing out.
            "CONN_HEALTH_CHECKS": True,
            # Each gunicorn thread holds at most one connection; a pool smaller than the threads
            # makes a request wait for a free one, then fail.
            "OPTIONS": {"pool": {"min_size": 1, "max_size": GUNICORN_THREADS}},
        }
    }


def _mirror_dav_url(url: str | None) -> str | None:
    """The mirror client sends Basic auth on every job, so only https may carry it."""
    if url and urlparse(url).scheme != "https":
        raise ValueError(f"BUNDESARCHIV_MIRROR_DAV_URL must be an https:// URL, got: {url!r}")
    return url or None


DATABASES = _databases_from_dsn(os.environ.get("BUNDESARCHIV_PG_DSN", _DEFAULT_PG_DSN))

# Required to serve; only wsgi.py enforces it, so dev and tests need no env. The empty defaults
# fail closed: Django raises on signing with an empty SECRET_KEY, and an empty ALLOWED_HOSTS
# rejects every request outside DEBUG.
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
    "django.contrib.staticfiles",
    "procrastinate.contrib.django",
    "bundesarchiv.index",
    # The application-service shell — installed so Procrastinate autodiscovers its ``tasks.py`` and
    # Django discovers the ``ensure_index_current`` command.
    "bundesarchiv.app",
]

BUNDESARCHIV_CANONICAL_ROOT = os.environ.get("BUNDESARCHIV_CANONICAL_ROOT", "var/canonical")

# Periodic full index rebuild that bounds any missed incremental update (ADR 0014).
BUNDESARCHIV_RECONCILE_CRON = os.environ.get("BUNDESARCHIV_RECONCILE_CRON", "0 * * * *")
# A request slower than this many ms is logged as one WARNING record (app/web/slow_requests.py).
BUNDESARCHIV_SLOW_REQUEST_MS = int(os.environ.get("BUNDESARCHIV_SLOW_REQUEST_MS", "1000"))

ROOT_URLCONF = "bundesarchiv.app.web.urls"

# No session or auth middleware (ADR 0018). SecurityMiddleware first, so SECURE_* apply to every
# answer; the anonymous gate last, so it sees only requests bound for a view.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "bundesarchiv.app.web.slow_requests.SlowRequestMiddleware",  # times everything below
    # SECURE_CSP below; above CSRF and the gate, so their refusals carry the policy too.
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "bundesarchiv.app.web.viewers.TokenCookieMiddleware",  # outside everything that calls viewer_of
    "bundesarchiv.app.web.viewers.vary_on_request_kind",  # above the gate: the door varies too
    "bundesarchiv.app.web.legacy_params.LegacyParamsMiddleware",  # old German params: 301 to English
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

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(_WEB_TEMPLATES)],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": ["bundesarchiv.app.web.theme.theme"]},
    }
]

# Behind nginx, ``media_response`` answers with an X-Accel-Redirect to ``<prefix>/<key>``
# (ADR 0017); unset (dev), it streams the blob.
BUNDESARCHIV_X_ACCEL_PREFIX = os.environ.get("BUNDESARCHIV_X_ACCEL_PREFIX") or None

# A derived cache, not backed up and freely prunable.
BUNDESARCHIV_THUMBNAIL_ROOT = os.environ.get("BUNDESARCHIV_THUMBNAIL_ROOT", "var/thumbnails")

# The system of record's WebDAV folder (ADR 0020); unset, every push job no-ops.
BUNDESARCHIV_MIRROR_DAV_URL = _mirror_dav_url(os.environ.get("BUNDESARCHIV_MIRROR_DAV_URL"))
BUNDESARCHIV_MIRROR_DAV_USER = os.environ.get("BUNDESARCHIV_MIRROR_DAV_USER") or None
BUNDESARCHIV_MIRROR_DAV_PASSWORD = os.environ.get("BUNDESARCHIV_MIRROR_DAV_PASSWORD") or None

# The reconcile (ADR 0020): pushes what a push missed.
BUNDESARCHIV_MIRROR_RECONCILE_CRON = os.environ.get(
    "BUNDESARCHIV_MIRROR_RECONCILE_CRON", "0 3 * * *"
)

# Per-file upload cap (owner ruling 2026-09-19) of the chunked upload, checked at its creation.
BUNDESARCHIV_MAX_UPLOAD_BYTES = int(
    os.environ.get("BUNDESARCHIV_MAX_UPLOAD_BYTES", str(4 * 1024**3))
)
# Per-file cap of the multipart upload, the no-JS fallback (owner, 2026-10-31; ADR 0026). nginx's
# client_max_body_size sits higher, so its English 413 never pre-empts the view's German error.
BUNDESARCHIV_MAX_MULTIPART_UPLOAD_BYTES = int(
    os.environ.get("BUNDESARCHIV_MAX_MULTIPART_UPLOAD_BYTES", "50000000")
)
# Chunked uploads until their finish (ADR 0026): local disk shared by app and worker, never the archive.
BUNDESARCHIV_UPLOAD_STAGING_ROOT = os.environ.get(
    "BUNDESARCHIV_UPLOAD_STAGING_ROOT", "var/upload-staging"
)
# The media manager renders one caption input per file; raised from Django's 1000.
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
