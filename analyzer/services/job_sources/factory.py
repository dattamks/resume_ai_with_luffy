"""
Job source factory — returns configured job source providers.

Phase 12: Primary source is Firecrawl (uses existing FIRECRAWL_API_KEY).
"""
import logging

from django.conf import settings

from .base import BaseJobSource

logger = logging.getLogger('analyzer')


def get_job_sources() -> list:
    """
    Return a list of all configured and available job sources.

    Currently only Firecrawl is supported. Requires FIRECRAWL_API_KEY.
    """
    sources: list[BaseJobSource] = []

    if getattr(settings, 'FIRECRAWL_API_KEY', ''):
        try:
            from .firecrawl_source import FirecrawlJobSource
            sources.append(FirecrawlJobSource())
            logger.debug('JobSourceFactory: Firecrawl source enabled')
        except Exception as exc:
            logger.warning('JobSourceFactory: Firecrawl init failed: %s', exc)

    if not sources:
        logger.warning(
            'JobSourceFactory: No job sources configured. '
            'Set FIRECRAWL_API_KEY env var to enable job crawling.'
        )

    return sources
