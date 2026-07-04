"""Development settings — production settings plus the dev-viewer mechanism (Part 4.4).

Production runs on ``bundesarchiv.index.settings``, which stays HTTP-agnostic (no MIDDLEWARE, no
ROOT_URLCONF) and NEVER imports this module. This module imports everything from prod settings and
adds ONLY what the dev-viewer switcher needs:

- ``DEV_VIEWER_SIGNING_KEY`` — a DEDICATED dev-only signing key, deliberately NOT ``SECRET_KEY``.
  ``viewer_of`` signs/verifies the dev cookie with this key alone, so a dev cookie is worthless
  against any production deployment (which defines no such key and thus falls closed to Public).
- ``DevViewerMiddleware`` in ``MIDDLEWARE`` — attaches ``request.viewer``. Absent from prod.
- ``ROOT_URLCONF`` -> ``dev_urls`` — exposes the switcher route. Absent from prod.

Because these live only here and prod never imports this module, the switcher is unreachable in
production by absence of code paths, not by a runtime flag (flags get flipped; missing code cannot).

Run dev with ``DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings_dev``.
"""

import os

from bundesarchiv.index.settings import *  # noqa: F403  (dev = prod + the dev-viewer additions below)

# A DEDICATED dev-only signing key — NOT the production SECRET_KEY (that is the whole point: a
# leaked/replayed dev cookie must be worthless against prod). Fixed value: this file is dev-only and
# never shipped to production, so there is nothing to protect. Overridable via env for a shared dev
# host that wants a per-host key.
DEV_VIEWER_SIGNING_KEY = os.environ.get(
    "BUNDESARCHIV_DEV_VIEWER_SIGNING_KEY", "dev-viewer-signing-key-not-a-secret"
)

# The dev switcher's URLconf and the middleware that reads the signed cookie into ``request.viewer``.
ROOT_URLCONF = "bundesarchiv.app.web.dev_urls"

MIDDLEWARE = [
    "bundesarchiv.app.web.dev.DevViewerMiddleware",
]
