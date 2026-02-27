"""
Firecrawl job source — crawls job board search pages via Firecrawl.

Uses the existing Firecrawl API key (FIRECRAWL_API_KEY) already configured
for JD fetching.

Architecture:
1. Scrape job board search result pages via Firecrawl (markdown output)
2. Single LLM call per page to extract structured job listings
3. Return RawJobListing objects for dedup + storage

Cost: ~$0.005 per page scrape + ~$0.01 per LLM extraction = ~$0.015/page.
"""
import hashlib
import json
import logging
import re
import time
import uuid
from typing import List

from django.conf import settings
from openai import OpenAI

from .base import BaseJobSource, RawJobListing

logger = logging.getLogger('analyzer')

_MD_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', re.DOTALL)

# Default job board search URL templates
_DEFAULT_SOURCES = [
    {
        'name': 'LinkedIn',
        'url_template': 'https://www.linkedin.com/jobs/search/?keywords={query}&location={location}&f_TPR=r86400',
    },
    {
        'name': 'Indeed',
        'url_template': 'https://www.indeed.com/jobs?q={query}&l={location}&fromage=1',
    },
]

# LLM prompt for extracting structured job listings from scraped markdown
_EXTRACTION_SYSTEM_PROMPT = (
    'You are a job listing data extractor. Given the raw markdown content from a '
    'job board search results page, extract each job listing into structured JSON. '
    'Return ONLY valid JSON with no markdown, no code fences, no explanation.'
)

_EXTRACTION_PROMPT = """Extract all job listings from this job board search results page.

PAGE SOURCE: {source_name}
SEARCH QUERY: {query}

PAGE CONTENT (markdown):
{markdown}

Return ONLY a JSON array following this exact schema:

[
  {{
    "title": "<job title>",
    "company": "<company name>",
    "location": "<job location>",
    "url": "<direct link to the job posting, or empty string if not found>",
    "salary": "<salary range if shown, or empty string>",
    "snippet": "<first 200 chars of job description/requirements>",
    "posted": "<posting date if shown, e.g. '2 days ago', 'Jan 15', or empty string>"
  }}
]

Rules:
- Extract ONLY actual job listings, not ads or site navigation
- If a field is not available, use an empty string
- Include ALL distinct job listings on the page
- Do not fabricate or invent job data — only extract what is on the page
- Limit to 30 listings maximum per page
"""


class FirecrawlJobSource(BaseJobSource):
    """
    Scrapes job board search pages via Firecrawl and extracts
    structured listings using a single LLM call per page.
    """

    def __init__(self):
        from firecrawl import FirecrawlApp

        api_key = getattr(settings, 'FIRECRAWL_API_KEY', '')
        if not api_key:
            raise ValueError('FIRECRAWL_API_KEY not configured.')
        self.app = FirecrawlApp(api_key=api_key)

        self.sources = self._load_sources()

    @staticmethod
    def _load_sources():
        """
        Load crawl sources from the CrawlSource DB table.
        Falls back to settings.JOB_CRAWL_SOURCES → _DEFAULT_SOURCES.
        """
        try:
            from analyzer.models import CrawlSource
            db_sources = list(
                CrawlSource.objects
                .filter(is_active=True)
                .order_by('priority', 'name')
                .values('name', 'url_template', 'source_type')
            )
            if db_sources:
                return db_sources
        except Exception:
            pass  # DB not ready / table doesn't exist yet
        return getattr(settings, 'JOB_CRAWL_SOURCES', _DEFAULT_SOURCES)

    def name(self) -> str:
        return 'FirecrawlJobSource'

    def search(
        self,
        queries: List[str],
        location: str = '',
        date_filter: str = 'day',
        max_results: int = 20,
    ) -> List[RawJobListing]:
        """
        Search all configured job board sources for each query.

        Args:
            queries: Job title search queries (e.g. ['Python Developer', 'Django Engineer'])
            location: Geographic location filter
            date_filter: Recency filter (not directly used — URL templates handle this)
            max_results: Max results per query per source

        Returns:
            List of RawJobListing objects from all sources.
        """
        all_listings: List[RawJobListing] = []
        max_total = getattr(settings, 'MAX_CRAWL_JOBS_PER_RUN', 200)

        for source_config in self.sources:
            source_name = source_config['name']
            url_template = source_config['url_template']
            source_type = source_config.get('source_type', 'job_board')

            if source_type == 'company':
                # Company career pages — scrape once, no query/location substitution
                if len(all_listings) >= max_total:
                    break
                try:
                    listings = self._scrape_and_extract(url_template, source_name, 'careers')
                    all_listings.extend(listings[:max_results])
                    logger.info(
                        'FirecrawlJobSource: %s (company) → %d listings',
                        source_name, len(listings),
                    )
                except Exception as exc:
                    logger.warning(
                        'FirecrawlJobSource: %s (company) failed: %s',
                        source_name, exc,
                    )
                continue

            # Job board — iterate queries × location
            for query in queries:
                if len(all_listings) >= max_total:
                    logger.info(
                        'FirecrawlJobSource: hit max_total=%d, stopping crawl',
                        max_total,
                    )
                    return all_listings

                try:
                    url = url_template.format(
                        query=query.replace(' ', '+'),
                        location=location.replace(' ', '+') if location else '',
                    )
                    listings = self._scrape_and_extract(url, source_name, query)
                    all_listings.extend(listings[:max_results])
                    logger.info(
                        'FirecrawlJobSource: %s query=%r → %d listings',
                        source_name, query, len(listings),
                    )
                except Exception as exc:
                    logger.warning(
                        'FirecrawlJobSource: %s failed for query=%r: %s',
                        source_name, query, exc,
                    )
                    continue

        return all_listings[:max_total]

    def _scrape_and_extract(
        self, url: str, source_name: str, query: str,
    ) -> List[RawJobListing]:
        """
        Scrape a single search results page and extract job listings.

        1. Firecrawl scrapes the page → markdown
        2. LLM parses markdown → structured JSON
        3. Convert to RawJobListing objects
        """
        from firecrawl.v2.types import ScrapeFormats

        logger.debug('FirecrawlJobSource: scraping %s', url)
        start = time.monotonic()

        try:
            result = self.app.scrape(
                url,
                formats=ScrapeFormats(markdown=True),
            )
        except Exception as exc:
            logger.error('Firecrawl scrape failed for %s: %s', url, exc)
            raise ValueError(f'Firecrawl scrape failed: {exc}') from exc

        # Extract markdown from response
        markdown = ''
        if hasattr(result, 'markdown'):
            markdown = result.markdown or ''
        elif isinstance(result, dict):
            markdown = result.get('markdown', '') or ''

        scrape_duration = time.monotonic() - start
        logger.debug(
            'FirecrawlJobSource: scraped %s in %.2fs (%d chars)',
            url, scrape_duration, len(markdown),
        )

        if not markdown or len(markdown) < 100:
            logger.warning('FirecrawlJobSource: no meaningful content from %s', url)
            return []

        # Truncate markdown to avoid blowing up the LLM context
        if len(markdown) > 15000:
            markdown = markdown[:15000]

        # LLM extraction
        jobs_data = self._extract_via_llm(markdown, source_name, query)

        # Convert to RawJobListing
        listings = []
        for job in jobs_data:
            if not isinstance(job, dict):
                continue
            title = str(job.get('title', '')).strip()
            if not title:
                continue

            # Generate a stable external_id from source + title + company
            ext_id = self._generate_external_id(source_name, title, job.get('company', ''), job.get('url', ''))

            listings.append(RawJobListing(
                source='firecrawl',
                external_id=ext_id,
                url=str(job.get('url', '')).strip(),
                title=title,
                company=str(job.get('company', '')).strip(),
                location=str(job.get('location', '')).strip(),
                salary_range=str(job.get('salary', '')).strip(),
                description_snippet=str(job.get('snippet', '')).strip()[:500],
                posted_at=None,  # Relative dates not reliably parseable; embedding handles recency
                raw_data=job,
            ))

        return listings

    def _extract_via_llm(self, markdown: str, source_name: str, query: str) -> list:
        """Use LLM to extract structured job listings from scraped markdown."""
        api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
        base_url = getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
        model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

        if not api_key:
            raise ValueError('OPENROUTER_API_KEY not configured for job extraction.')

        prompt = _EXTRACTION_PROMPT.format(
            source_name=source_name,
            query=query,
            markdown=markdown,
        )

        client = OpenAI(api_key=api_key, base_url=base_url)
        start = time.monotonic()

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'system', 'content': _EXTRACTION_SYSTEM_PROMPT},
                    {'role': 'user', 'content': prompt},
                ],
                temperature=0.1,
                max_tokens=4096,
                timeout=60,
            )
        except Exception as exc:
            logger.error('LLM extraction failed: %s', exc)
            return []

        duration = time.monotonic() - start
        raw = (response.choices[0].message.content or '').strip() if response.choices else ''
        logger.debug('LLM job extraction: duration=%.2fs raw_length=%d', duration, len(raw))

        if not raw:
            return []

        # Strip markdown fences
        fence_match = _MD_FENCE_RE.match(raw)
        if fence_match:
            raw = fence_match.group(1).strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            try:
                from .ai_providers.json_repair import repair_json
                repaired = repair_json(raw)
                parsed = json.loads(repaired)
            except Exception:
                logger.warning(
                    'FirecrawlJobSource: LLM returned non-JSON (raw length=%d)',
                    len(raw),
                )
                return []

        if not isinstance(parsed, list):
            logger.warning('FirecrawlJobSource: LLM returned non-list type=%s', type(parsed))
            return []

        return parsed[:30]  # Cap at 30 per page

    @staticmethod
    def _generate_external_id(source_name: str, title: str, company: str, url: str) -> str:
        """
        Generate a stable external_id for deduplication.

        If the job has a URL, hash the URL for a stable ID.
        Otherwise, hash source + title + company.
        """
        if url:
            # Normalize URL — strip tracking params, fragment
            clean_url = url.split('?')[0].split('#')[0].lower().strip()
            return hashlib.sha256(clean_url.encode()).hexdigest()[:32]

        key = f'{source_name}|{title}|{company}'.lower().strip()
        return hashlib.sha256(key.encode()).hexdigest()[:32]
