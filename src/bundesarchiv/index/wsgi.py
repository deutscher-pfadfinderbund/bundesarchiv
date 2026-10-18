"""The production WSGI entry point (gunicorn, ADR 0016): the one place that refuses to serve
without ``REQUIRED_SERVING_ENV``, with the index or the login realm replaced (ADR 0024), or with
``DEBUG`` on, since neither runserver nor the tests import it.
"""

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bundesarchiv.index.settings")

_missing = [name for name in settings.REQUIRED_SERVING_ENV if not os.environ.get(name)]
if _missing:
    raise ImproperlyConfigured(f"refusing to serve, unset environment: {', '.join(_missing)}")
if hasattr(settings, "BUNDESARCHIV_INDEX"):
    raise ImproperlyConfigured("refusing to serve, BUNDESARCHIV_INDEX replaces the Postgres index")
if hasattr(settings, "BUNDESARCHIV_REALM"):
    raise ImproperlyConfigured("refusing to serve, BUNDESARCHIV_REALM replaces the Keycloak realm")
if settings.DEBUG:
    raise ImproperlyConfigured("refusing to serve with DEBUG on")

application = get_wsgi_application()
