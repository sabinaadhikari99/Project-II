# file path: apps/state/apps.py
from django.apps import AppConfig


class StateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.state"
    verbose_name = "Persistent State"

    def ready(self):
        import apps.state.signals  # noqa: F401
