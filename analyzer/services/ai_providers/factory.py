import functools
import logging

from django.conf import settings
from openai import OpenAI, APITimeoutError, RateLimitError, APIConnectionError, APIStatusError
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from .base import AIProvider
from .openrouter_provider import OpenRouterProvider

logger = logging.getLogger('analyzer')


@functools.lru_cache(maxsize=4)
def _get_openai_client(api_key: str, base_url: str) -> OpenAI:
    """
    Return a cached OpenAI client instance.

    Keyed by (api_key, base_url) so the same TCP connection pool is
    reused across all callers (analysis, resume generation, job matching,
    profile extraction). Avoids creating a new client per request.
    """
    return OpenAI(api_key=api_key, base_url=base_url)


def get_openai_client() -> OpenAI:
    """
    Return a shared OpenAI client using the configured settings.
    Raises ValueError if OPENROUTER_API_KEY is not set.
    """
    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
    if not api_key:
        raise ValueError('OPENROUTER_API_KEY is not configured.')
    base_url = getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    return _get_openai_client(api_key, base_url)


def _is_retryable_api_error(exc: BaseException) -> bool:
    """Return True for transient API errors worth retrying (5xx server errors)."""
    return isinstance(exc, APIStatusError) and exc.status_code >= 500


# Shared retry decorator for all LLM API calls.
# Retries on rate limits (429), timeouts, connection errors, and 5xx.
# Exponential backoff: 2s → 4s → 8s (3 attempts total).
llm_retry = retry(
    retry=(
        retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError, ConnectionError, OSError))
        | retry_if_exception(_is_retryable_api_error)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


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
