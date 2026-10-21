"""Prod never imports this module, so the dev realm and its login page are absent from prod as
code, not behind a flag.
"""

import os

from bundesarchiv.index.settings import *

# Not SECRET_KEY: a dev token must be worthless against prod.
DEV_VIEWER_SIGNING_KEY = os.environ.get(
    "BUNDESARCHIV_DEV_VIEWER_SIGNING_KEY", "dev-viewer-signing-key-not-a-secret"
)
VIEWER_SIGNING_KEY = VIEWER_SIGNING_KEY or "viewer-signing-key-not-a-secret"

# Dev logs in through the dev realm (ADR 0025) and browses as Public until then.
BUNDESARCHIV_REALM = "bundesarchiv.app.web.dev_realm.DevRealm"
ANONYMOUS_GATE_ENABLED = False

ROOT_URLCONF = "bundesarchiv.app.web.dev_urls"

# Non-manifest, so runserver needs no collectstatic. Rebind, never mutate: ``import *`` aliases
# prod's STORAGES and conftests import this module, so a mutation would flip the whole test process.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
SECRET_KEY = "dev-secret-key-not-a-secret"  # noqa: S105 — dev-only, prod never imports this
# Dev serves plain http, so a Secure CSRF cookie would never come back, and a ``__Host-`` one
# needs Secure (ADR 0025).
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_NAME = "bundesarchiv_csrftoken"
