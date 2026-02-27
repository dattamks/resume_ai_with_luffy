"""
SerpAPI job source — Google Jobs results via SerpAPI.

Docs: https://serpapi.com/google-jobs-api
Env var required: SERPAPI_API_KEY

Uses raw `requests` — no extra pypi package required.
"""
import hashlib
import logging
import re
from datetime import timedelta
from typing import List

import requests
from django.conf import settings
from django.utils import timezone

from .base import BaseJobSource, RawJobListing

logger = logging.getLogger('analyzer')

_DATE_FILTER_MAP = {
    'day': 'today',
    'week': 'week',
    'month': 'month',
}

_SERPAPI_ENDPOINT = 'https://serpapi.com/search.json'

# Pattern for "X days/hours ago" style dates from Google Jobs
_RELATIVE_DATE_RE = re.compile(r'(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago', re.IGNORECASE)

_UNIT_TO_TIMEDELTA_KWARGS = {
    'second': 'seconds',
    'minute': 'minutes',
    'hour': 'hours',
    'day': 'days',
    'week': 'weeks',
}


def _parse_relative_date(text: str) -> str | None:
    """Convert 'X days ago' to ISO-8601 string, or return None on failure."""
    if not text:
        return None
    m = _RELATIVE_DATE_RE.search(text)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    kwarg = _UNIT_TO_TIMEDELTA_KWARGS.get(unit)
    if kwarg:
        dt = timezone.now() - timedelta(**{kwarg: amount})
    elif unit == 'month':
        dt = timezone.now() - timedelta(days=amount * 30)
    elif unit == 'year':
        dt = timezone.now() - timedelta(days=amount * 365)
    else:
        return None
    return dt.isoformat()


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
                job_id = job.get('job_id', '')
                if not job_id:
                    # Generate a deterministic hash from title + company + location
                    raw_key = f"{job.get('title', '')}|{job.get('company_name', '')}|{job.get('location', '')}"
                    job_id = hashlib.sha256(raw_key.encode()).hexdigest()[:32]
                url = ''
                # Try to get apply link
                for link in job.get('related_links', []):
                    if link.get('link'):
                        url = link['link']
                        break
                if not url:
                    url = job.get('share_link', '') or ''

                # Skip jobs with no URL — can't link user to anything useful
                if not url:
                    continue

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
                    posted_at=_parse_relative_date(detected_ext.get('posted_at', '')),
                    raw_data=job,
                ))

            logger.info('SerpAPI: found %d jobs for query=%r', len(data.get('jobs_results', [])), query)

        return all_listings

    def name(self) -> str:
        return 'SerpAPI'
