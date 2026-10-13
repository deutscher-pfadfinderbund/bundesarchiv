from django.apps import AppConfig


class AppServicesConfig(AppConfig):
    name = "bundesarchiv.app"
    label = "bundesarchiv_app"  # distinct from the reserved-ish "app"; index owns label "index"
    default_auto_field = "django.db.models.BigAutoField"
