"""App config for the derived search index."""

from django.apps import AppConfig


class IndexConfig(AppConfig):
    name = "bundesarchiv.index"
    label = "index"
    default_auto_field = "django.db.models.BigAutoField"
