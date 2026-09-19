"""The production WSGI entry point — what gunicorn imports (ADR 0016).

Dev runs ``manage.py runserver``, which builds its own handler; nothing but a real app server
reaches this module. Tests never import it either, so this is the one place that may insist on
the environment a public deployment needs.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bundesarchiv.index.settings")

application = get_wsgi_application()
