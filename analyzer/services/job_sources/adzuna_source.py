"""
Adzuna job source — Adzuna Jobs API (free tier, 250 req/day).

Docs: https://developer.adzuna.com/docs/search
Env vars required:
  ADZUNA_APP_ID
  ADZUNA_APP_KEY
  ADZUNA_COUNTRY  (optional, default: 'gb')

Uses raw `requests`.
"""
import logging
from typing import List

import requests
from django.conf import settings

from .base import BaseJobSource, RawJobListing

logger = logging.getLogger('analyzer')

_ADZUNA_BASE = 'https://api.adzuna.com/v1/api/jobs'

# Map Adzuna country codes to currency symbols
_COUNTRY_CURRENCY = {
    'gb': '£', 'us': '$', 'au': 'A$', 'ca': 'C$', 'in': '₹',
    'de': '€', 'fr': '€', 'nl': '€', 'it': '€', 'es': '€', 'at': '€',
    'br': 'R$', 'za': 'R', 'sg': 'S$', 'nz': 'NZ$', 'pl': 'zł',
}


class AdzunaJobSource(BaseJobSource):
    """Fetches job listings from the Adzuna API."""

    def __init__(self, app_id: str = '', app_key: str = '', country: str = ''):
        self.app_id = app_id or getattr(settings, 'ADZUNA_APP_ID', '')
        self.app_key = app_key or getattr(settings, 'ADZUNA_APP_KEY', '')
        self.country = country or getattr(settings, 'ADZUNA_COUNTRY', 'gb')

    def search(
        self,
        queries: List[str],
        location: str = '',
        date_filter: str = 'month',
        max_results: int = 20,
    ) -> List[RawJobListing]:
        if not self.app_id or not self.app_key:
            logger.warning('AdzunaJobSource: ADZUNA_APP_ID/KEY not configured — skipping')
            return []

        # Adzuna supports max_days_old filter
        max_days = {'day': 1, 'week': 7, 'month': 30}.get(date_filter, 30)
        all_listings: List[RawJobListing] = []

        for query in queries:
            url = f'{_ADZUNA_BASE}/{self.country}/search/1'
            params = {
                'app_id': self.app_id,
                'app_key': self.app_key,
                'what': query,
                'results_per_page': min(max_results, 20),
                'max_days_old': max_days,
                'content-type': 'application/json',
            }
            if location:
                params['where'] = location

            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning('Adzuna request failed for query=%r: %s', query, exc)
                continue

            for job in data.get('results', []):
                job_id = str(job.get('id', ''))
                currency = _COUNTRY_CURRENCY.get(self.country, '$')
                salary_parts = []
                if job.get('salary_min'):
                    salary_parts.append(f"{currency}{job['salary_min']:.0f}")
                if job.get('salary_max'):
                    salary_parts.append(f"{currency}{job['salary_max']:.0f}")
                salary = '–'.join(salary_parts)

                all_listings.append(RawJobListing(
                    source='adzuna',
                    external_id=job_id,
                    url=job.get('redirect_url', ''),
                    title=job.get('title', ''),
                    company=job.get('company', {}).get('display_name', ''),
                    location=job.get('location', {}).get('display_name', ''),
                    salary_range=salary,
                    description_snippet=job.get('description', '')[:500],
                    posted_at=job.get('created'),
                    raw_data=job,
                ))

            logger.info('Adzuna: found %d jobs for query=%r', len(data.get('results', [])), query)

        return all_listings

    def name(self) -> str:
        return 'Adzuna'
