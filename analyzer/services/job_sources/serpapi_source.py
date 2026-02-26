"""
SerpAPI job source — Google Jobs results via SerpAPI.

Docs: https://serpapi.com/google-jobs-api
Env var required: SERPAPI_API_KEY

Uses raw `requests` — no extra pypi package required.
"""
import logging
from typing import List

import requests
from django.conf import settings

from .base import BaseJobSource, RawJobListing

logger = logging.getLogger('analyzer')

_DATE_FILTER_MAP = {
    'day': 'today',
    'week': 'week',
    'month': 'month',
}

_SERPAPI_ENDPOINT = 'https://serpapi.com/search.json'


class SerpAPIJobSource(BaseJobSource):
    """Fetches Google Jobs listings via SerpAPI."""

    def __init__(self, api_key: str = ''):
        self.api_key = api_key or getattr(settings, 'SERPAPI_API_KEY', '')

    def search(
        self,
        queries: List[str],
        location: str = '',
        date_filter: str = 'month',
        max_results: int = 20,
    ) -> List[RawJobListing]:
        if not self.api_key:
            logger.warning('SerpAPIJobSource: SERPAPI_API_KEY not configured — skipping')
            return []

        chips = _DATE_FILTER_MAP.get(date_filter, 'month')
        all_listings: List[RawJobListing] = []

        for query in queries:
            params = {
                'engine': 'google_jobs',
                'q': query,
                'api_key': self.api_key,
                'num': min(max_results, 10),
            }
            if location:
                params['location'] = location
            if chips:
                params['chips'] = f'date_posted:{chips}'

            try:
                resp = requests.get(_SERPAPI_ENDPOINT, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning('SerpAPI request failed for query=%r: %s', query, exc)
                continue

            for job in data.get('jobs_results', []):
                job_id = job.get('job_id') or job.get('title', '') + job.get('company_name', '')
                url = ''
                # Try to get apply link
                for link in job.get('related_links', []):
                    if link.get('link'):
                        url = link['link']
                        break
                if not url:
                    url = job.get('share_link', '') or ''

                salary = ''
                detected_ext = job.get('detected_extensions', {})
                if detected_ext.get('salary'):
                    salary = str(detected_ext['salary'])

                all_listings.append(RawJobListing(
                    source='serpapi',
                    external_id=str(job_id),
                    url=url,
                    title=job.get('title', ''),
                    company=job.get('company_name', ''),
                    location=job.get('location', ''),
                    salary_range=salary,
                    description_snippet=job.get('description', '')[:500],
                    posted_at=detected_ext.get('posted_at'),
                    raw_data=job,
                ))

            logger.info('SerpAPI: found %d jobs for query=%r', len(data.get('jobs_results', [])), query)

        return all_listings

    def name(self) -> str:
        return 'SerpAPI'
