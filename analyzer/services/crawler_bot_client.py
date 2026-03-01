"""
HTTP client for pushing data to the Crawler Bot's ingest API.

Reads configuration from Django settings / env vars:
  CRAWLER_BOT_INGEST_URL  — e.g. https://<crawler-bot>.up.railway.app/api/ingest
  CRAWLER_API_KEY          — shared secret for X-Crawler-Key header

Usage:
    from analyzer.services.crawler_bot_client import get_crawler_bot_client

    client = get_crawler_bot_client()
    if client:
        client.push_job({...})
"""
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger('analyzer')

_TIMEOUT = 30  # seconds per request
_MAX_RETRIES = 3


class CrawlerBotClient:
    """HTTP client for the Crawler Bot ingest API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'X-Crawler-Key': api_key,
            'Content-Type': 'application/json',
        })

    # ── Health ──────────────────────────────────────────────────────────

    def ping(self) -> dict:
        """GET /ping/ — verify connectivity + auth."""
        return self._get('/ping/')

    # ── Companies ───────────────────────────────────────────────────────

    def push_company(self, data: dict) -> dict:
        """POST /companies/ — upsert a single company."""
        return self._post('/companies/', data)

    def push_companies_bulk(self, companies: list[dict]) -> dict:
        """POST /companies/bulk/ — upsert multiple companies."""
        return self._post('/companies/bulk/', {'companies': companies})

    # ── Career Pages ────────────────────────────────────────────────────

    def push_career_page(self, data: dict) -> dict:
        """POST /career-pages/ — upsert a career page."""
        return self._post('/career-pages/', data)

    # ── Jobs ────────────────────────────────────────────────────────────

    def push_job(self, data: dict) -> dict:
        """POST /jobs/ — upsert a single job."""
        return self._post('/jobs/', data)

    def push_jobs_bulk(self, jobs: list[dict]) -> dict:
        """POST /jobs/bulk/ — upsert multiple jobs (max 500)."""
        return self._post('/jobs/bulk/', {'jobs': jobs})

    # ── Internal ────────────────────────────────────────────────────────

    def _get(self, path: str) -> dict:
        url = f'{self.base_url}{path}'
        resp = self._request_with_retry('GET', url)
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        url = f'{self.base_url}{path}'
        resp = self._request_with_retry('POST', url, json=payload)
        return resp.json()

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """Execute request with exponential backoff retry on transient errors."""
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self.session.request(method, url, timeout=_TIMEOUT, **kwargs)
                if resp.status_code in (429, 500, 502, 503):
                    wait = 2 ** attempt
                    logger.warning(
                        'CrawlerBot %s %s returned %s — retry %d/%d in %ds',
                        method, url, resp.status_code, attempt + 1, _MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning(
                    'CrawlerBot connection error %s %s — retry %d/%d in %ds: %s',
                    method, url, attempt + 1, _MAX_RETRIES, wait, exc,
                )
                time.sleep(wait)
            except requests.exceptions.Timeout as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning(
                    'CrawlerBot timeout %s %s — retry %d/%d in %ds',
                    method, url, attempt + 1, _MAX_RETRIES, wait,
                )
                time.sleep(wait)

        # Final attempt — raise whatever we got
        if last_exc:
            raise last_exc
        resp.raise_for_status()
        return resp


def get_crawler_bot_client() -> CrawlerBotClient | None:
    """
    Factory: returns a CrawlerBotClient if both env vars are configured,
    otherwise returns None (sync is silently skipped).
    """
    base_url = getattr(settings, 'CRAWLER_BOT_INGEST_URL', '') or ''
    api_key = getattr(settings, 'CRAWLER_API_KEY', '') or ''

    if not base_url or not api_key:
        return None

    return CrawlerBotClient(base_url, api_key)
