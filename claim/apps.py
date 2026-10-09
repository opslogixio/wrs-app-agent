from django.apps import AppConfig


class ClaimConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'claim'

    def ready(self):
            # Import signal handlers
            from . import signals