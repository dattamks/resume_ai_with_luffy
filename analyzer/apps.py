import logging

from django.apps import AppConfig

logger = logging.getLogger('analyzer')


class AnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analyzer'

    def ready(self):
        """Validate required settings at startup so misconfiguration is caught early."""
        import analyzer.signals  # noqa: F401 — register signal handlers

        from django.conf import settings

        if not getattr(settings, 'OPENROUTER_API_KEY', ''):
            logger.warning(
                'OPENROUTER_API_KEY is not set. '
                'Resume analysis will fail until this is configured.'
            )
