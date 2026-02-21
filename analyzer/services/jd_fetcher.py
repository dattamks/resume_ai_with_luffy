import ipaddress
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from django.conf import settings


class JDFetcher:
    """Fetches and cleans job description content from a URL."""

    HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
    }

    # Private/loopback IP ranges that must not be reachable (SSRF protection)
    _BLOCKED_NETWORKS = [
        ipaddress.ip_network('127.0.0.0/8'),       # loopback
        ipaddress.ip_network('10.0.0.0/8'),         # private class A
        ipaddress.ip_network('172.16.0.0/12'),      # private class B
        ipaddress.ip_network('192.168.0.0/16'),     # private class C
        ipaddress.ip_network('169.254.0.0/16'),     # link-local
        ipaddress.ip_network('::1/128'),             # IPv6 loopback
        ipaddress.ip_network('fc00::/7'),            # IPv6 unique-local
        ipaddress.ip_network('fe80::/10'),           # IPv6 link-local
    ]

    def _validate_url(self, url: str) -> None:
        """
        Raise ValueError if `url` is not a safe, public HTTP(S) URL.
        Prevents SSRF attacks by blocking private/loopback addresses.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError('Only http:// and https:// URLs are allowed.')
        hostname = parsed.hostname
        if not hostname:
            raise ValueError('Invalid URL: missing hostname.')

        # Resolve hostname to IP and check against blocked ranges
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise ValueError(f'Could not resolve hostname "{hostname}": {exc}') from exc

        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            for network in self._BLOCKED_NETWORKS:
                if ip in network:
                    raise ValueError(
                        f'The URL resolves to a private/reserved IP address ({ip}) '
                        'and cannot be fetched.'
                    )

    def fetch(self, url: str) -> str:
        """
        Fetch the page at `url` and return cleaned visible text.
        Raises ValueError on fetch failure or if no content is found.
        """
        self._validate_url(url)

        timeout = getattr(settings, 'JD_FETCH_TIMEOUT', 10)
        try:
            response = requests.get(url, headers=self.HEADERS, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ValueError(f'Failed to fetch job description URL: {exc}') from exc

        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove script/style noise
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()

        text = soup.get_text(separator='\n')
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned = '\n'.join(lines)

        if not cleaned:
            raise ValueError('No readable content found at the provided URL.')

        return cleaned

    def build_from_form(
        self,
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
