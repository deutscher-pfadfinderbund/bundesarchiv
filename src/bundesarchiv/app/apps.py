"""App config for the application-service layer.

Installed so Procrastinate autodiscovers ``bundesarchiv/app/tasks.py`` and Django discovers the
``ensure_index_current`` management command. Its one model is the push record's row (ADR 0020).
"""

from django.apps import AppConfig


class AppServicesConfig(AppConfig):
    name = "bundesarchiv.app"
    label = "bundesarchiv_app"  # distinct from the reserved-ish "app"; index owns label "index"
    default_auto_field = "django.db.models.BigAutoField"
