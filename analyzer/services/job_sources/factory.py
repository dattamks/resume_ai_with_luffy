"""
Job source factory — selects active providers based on configuration.

Returns a list of all configured sources so the discovery pipeline
can fan-out across multiple APIs and merge results.
"""
import logging

from django.conf import settings

from .base import BaseJobSource
from .serpapi_source import SerpAPIJobSource
from .adzuna_source import AdzunaJobSource

logger = logging.getLogger('analyzer')


def get_job_sources() -> list:
    """
    Return a list of all configured and available job sources.

    A source is included if its required env vars are present.
    This allows graceful degradation when some APIs are not configured.
    """
    sources: list[BaseJobSource] = []

    if getattr(settings, 'SERPAPI_API_KEY', ''):
        sources.append(SerpAPIJobSource())
        logger.debug('JobSourceFactory: SerpAPI source enabled')

    if getattr(settings, 'ADZUNA_APP_ID', '') and getattr(settings, 'ADZUNA_APP_KEY', ''):
        sources.append(AdzunaJobSource())
        logger.debug('JobSourceFactory: Adzuna source enabled')

    if not sources:
        logger.warning(
            'JobSourceFactory: No job sources configured. '
            'Set SERPAPI_API_KEY and/or ADZUNA_APP_ID+ADZUNA_APP_KEY env vars.'
        )

    return sources
