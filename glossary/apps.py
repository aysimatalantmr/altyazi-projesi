from django.apps import AppConfig


class GlossaryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "glossary"
    verbose_name = "Terim Sözlüğü"

    def ready(self):
        from . import signals  # noqa: F401
