from django.conf import settings

from .base import AIProvider
from .openrouter_provider import OpenRouterProvider


def get_ai_provider() -> AIProvider:
    """
    Return the configured AI provider instance.
    Currently only OpenRouter is supported.
    Raises ValueError if the API key is missing.
    """
    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
    if not api_key:
        raise ValueError('OPENROUTER_API_KEY is not configured.')
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')
    base_url = getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    return OpenRouterProvider(api_key=api_key, model=model, base_url=base_url)
