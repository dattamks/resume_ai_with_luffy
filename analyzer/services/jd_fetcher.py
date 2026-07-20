import ipaddress
import logging
import socket
from urllib.parse import urlparse

from django.conf import settings
from firecrawl import FirecrawlApp
from firecrawl.v2.types import ScrapeFormats

from ..models import ScrapeResult

logger = logging.getLogger('analyzer')


class JDFetcher:
    """Fetches and cleans job description content from a URL using Firecrawl."""

    def __init__(self):
        api_key = getattr(settings, 'FIRECRAWL_API_KEY', '')
        if not api_key:
            raise ValueError('FIRECRAWL_API_KEY must be configured.')
        self.app = FirecrawlApp(api_key=api_key)

    @staticmethod
    def _ip_is_blocked(ip) -> bool:
        """True if an IP is in a non-public range we must not reach (SSRF)."""
        # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1), which otherwise slips
        # past the IPv6 loopback/private checks.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return (
            ip.is_private or ip.is_reserved or ip.is_loopback
            or ip.is_link_local or ip.is_multicast or ip.is_unspecified
        )

    @staticmethod
    def _validate_url(url: str) -> None:
        """
        Validate URL scheme and ensure hostname does not resolve to a
        private/reserved IP address (SSRF protection).

        Static so it can be exercised without a Firecrawl client. Note: this is
        a best-effort guard — the actual fetch is delegated to Firecrawl (a
        remote service), so this mainly stops obviously-internal targets rather
        than fully closing DNS-rebind/redirect vectors.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError('Only http:// and https:// URLs are allowed.')
        if not parsed.hostname:
            raise ValueError('Invalid URL: missing hostname.')

        # Resolve hostname to IP and check for private/reserved ranges
        hostname = parsed.hostname
        try:
            addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise ValueError(f'Cannot resolve hostname: {hostname}')

        for family, _type, _proto, _canonname, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if JDFetcher._ip_is_blocked(ip):
                raise ValueError(
                    f'URL resolves to a private/reserved IP address ({ip}). '
                    'Only public URLs are allowed.'
                )

    def fetch(self, url: str, user=None) -> tuple:
        """
        Scrape the page at `url` via Firecrawl. Returns (cleaned_text, scrape_result).

        Checks for a cached ScrapeResult first (same URL, < 24h old).
        Creates and persists a ScrapeResult atomically.

        Args:
            url: The URL to scrape.
            user: The Django User who triggered this (for FK linkage).

        Returns:
            Tuple of (cleaned_markdown_text, ScrapeResult instance).
        """
        self._validate_url(url)

        # ── Check cache (scoped to user to avoid cross-user leakage) ──
        if user:
            cached = ScrapeResult.find_cached(url, user=user)
            if cached:
                logger.debug('JDFetcher: reusing cached scrape (id=%s, age=%s)', cached.id, cached.created_at)
                cleaned = self._clean_markdown(cached.markdown)
                return cleaned, cached

        # ── Create pending ScrapeResult ──
        scrape = ScrapeResult.objects.create(
            user=user,
            source_url=url,
            status=ScrapeResult.STATUS_PENDING,
        ) if user else None

        logger.debug('JDFetcher: scraping %s via Firecrawl...', url)
        try:
            result = self.app.scrape(
                url,
                formats=ScrapeFormats(markdown=True, summary=True),
            )
        except Exception as exc:
            logger.error('Firecrawl scrape failed for %s: %s', url, exc)
            if scrape:
                scrape.status = ScrapeResult.STATUS_FAILED
                scrape.error_message = str(exc)[:500]
                scrape.save(update_fields=['status', 'error_message'])
            raise ValueError(
                'Failed to fetch job description from the provided URL. '
                'Please check the URL and try again.'
            ) from exc

        # ── Extract content from Document object ──
        markdown = ''
        json_data = None
        summary = ''

        if hasattr(result, 'markdown'):
            markdown = result.markdown or ''
        elif isinstance(result, dict):
            markdown = result.get('markdown', '') or ''

        if hasattr(result, 'json'):
            json_data = result.json if result.json else None
        elif isinstance(result, dict):
            json_data = result.get('json') or None

        if hasattr(result, 'summary'):
            summary = result.summary or ''
        elif isinstance(result, dict):
            summary = result.get('summary', '') or ''

        if not markdown:
            logger.warning('JDFetcher: no markdown content extracted from %s', url)
            if scrape:
                scrape.status = ScrapeResult.STATUS_FAILED
                scrape.error_message = 'No readable content found at the provided URL.'
                scrape.save(update_fields=['status', 'error_message'])
            raise ValueError('No readable content found at the provided URL.')

        # ── Persist scrape result atomically ──
        if scrape:
            scrape.markdown = markdown
            scrape.json_data = json_data
            scrape.summary = summary
            scrape.status = ScrapeResult.STATUS_DONE
            scrape.save(update_fields=[
                'markdown', 'json_data', 'summary', 'status', 'updated_at',
            ])
            logger.debug('JDFetcher: ScrapeResult saved (id=%s)', scrape.id)

        cleaned = self._clean_markdown(markdown)
        logger.debug('JDFetcher: extracted %d chars', len(cleaned))
        return cleaned, scrape

    @staticmethod
    def _clean_markdown(markdown: str) -> str:
        """Collapse excessive whitespace from markdown."""
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        return '\n'.join(lines)

    @staticmethod
    def build_from_form(
        role: str = '',
        company: str = '',
        skills: str = '',
        experience_years: int = None,
        industry: str = '',
        extra_details: str = '',
    ) -> str:
        """
        Assemble a human-readable job description string from structured form fields.
        """
        parts = []

        if role:
            parts.append(f'Job Title: {role}')
        if company:
            parts.append(f'Company: {company}')
        if industry:
            parts.append(f'Industry: {industry}')
        if experience_years is not None:
            parts.append(f'Required Experience: {experience_years} year(s)')
        if skills:
            parts.append(f'Required Skills / Technologies: {skills}')
        if extra_details:
            parts.append(f'Additional Details:\n{extra_details}')

        if not parts:
            raise ValueError('At least one job description field must be provided.')

        return '\n'.join(parts)
