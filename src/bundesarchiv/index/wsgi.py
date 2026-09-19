"""The production WSGI entry point — what gunicorn imports (ADR 0016).

Dev runs ``manage.py runserver``, which builds its own handler; nothing but a real app server
reaches this module. Tests never import it either, so this is the one place that may insist on the
environment a public deployment needs, and it does: serving without it is refused here rather than
half-working until the first signature or the first POST.
"""

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bundesarchiv.index.settings")

_missing = [name for name in settings.REQUIRED_SERVING_ENV if not os.environ.get(name)]
if _missing:
    raise ImproperlyConfigured(f"refusing to serve, unset environment: {', '.join(_missing)}")

application = get_wsgi_application()
