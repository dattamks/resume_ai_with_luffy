from django.conf import settings

from .base import AIProvider
from .claude_provider import ClaudeProvider
from .openai_provider import OpenAIProvider


def get_ai_provider() -> AIProvider:
    """
    Return the configured AI provider instance based on settings.AI_PROVIDER.
    Raises ValueError if the provider is unknown or its API key is missing.
    """
    provider_name = getattr(settings, 'AI_PROVIDER', 'claude').lower()

    if provider_name == 'claude':
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY is not configured.')
        model = getattr(settings, 'CLAUDE_MODEL', 'claude-sonnet-4-6')
        return ClaudeProvider(api_key=api_key, model=model)

    if provider_name == 'openai':
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError('OPENAI_API_KEY is not configured.')
        model = getattr(settings, 'OPENAI_MODEL', 'gpt-4o')
        return OpenAIProvider(api_key=api_key, model=model)

    raise ValueError(
        f'Unknown AI_PROVIDER "{provider_name}". Valid choices: "claude", "openai".'
    )
