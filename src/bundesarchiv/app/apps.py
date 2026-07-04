"""App config for the application-service layer.

Installed so Procrastinate autodiscovers ``bundesarchiv/app/tasks.py`` and Django discovers the
``ensure_index_current`` management command. It defines no ORM models (the only model in the system
is the index adapter's ``ArticleIndex``); this app is pure glue + worker tasks.
"""

from django.apps import AppConfig


class AppServicesConfig(AppConfig):
    name = "bundesarchiv.app"
    label = "bundesarchiv_app"  # distinct from the reserved-ish "app"; index owns label "index"
    default_auto_field = "django.db.models.BigAutoField"
