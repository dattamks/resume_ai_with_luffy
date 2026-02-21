import logging

from django.apps import AppConfig

logger = logging.getLogger('analyzer')


class AnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analyzer'

    def ready(self):
        """Validate required settings at startup so misconfiguration is caught early."""
        from django.conf import settings

        provider = getattr(settings, 'AI_PROVIDER', '').lower()
        if provider == 'claude':
            if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
                logger.warning(
                    'AI_PROVIDER is "claude" but ANTHROPIC_API_KEY is not set. '
                    'Resume analysis will fail until this is configured.'
                )
        elif provider == 'openai':
            if not getattr(settings, 'OPENAI_API_KEY', ''):
                logger.warning(
                    'AI_PROVIDER is "openai" but OPENAI_API_KEY is not set. '
                    'Resume analysis will fail until this is configured.'
                )
        else:
            logger.warning(
                'Unknown AI_PROVIDER "%s". Valid values: "claude", "openai".',
                provider,
            )
