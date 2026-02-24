from unittest.mock import patch
from django.test import TestCase

from analyzer.services.jd_fetcher import JDFetcher


class JDFetcherSSRFTests(TestCase):
    def setUp(self):
        self.fetcher = JDFetcher()

    def test_rejects_localhost(self):
        with self.assertRaises(ValueError, msg='localhost should be blocked'):
            self.fetcher._validate_url('http://localhost/internal')

    def test_rejects_127_0_0_1(self):
        with self.assertRaises(ValueError):
            self.fetcher._validate_url('http://127.0.0.1/secret')

    def test_rejects_private_10_range(self):
        with self.assertRaises(ValueError):
            self.fetcher._validate_url('http://10.0.0.1/admin')

    def test_rejects_private_192_168_range(self):
        with self.assertRaises(ValueError):
            self.fetcher._validate_url('http://192.168.1.1/')

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(ValueError):
            self.fetcher._validate_url('ftp://example.com/file')

    def test_rejects_file_scheme(self):
        with self.assertRaises(ValueError):
            self.fetcher._validate_url('file:///etc/passwd')

    def test_accepts_public_url(self):
        # Should not raise — just validates, doesn't fetch
        # We mock getaddrinfo to return a public IP
        with patch('analyzer.services.jd_fetcher.socket.getaddrinfo') as mock_dns:
            mock_dns.return_value = [(2, 1, 6, '', ('93.184.216.34', 0))]
            # Should not raise
            self.fetcher._validate_url('https://example.com/jobs/123')


class JDFetcherBuildFromFormTests(TestCase):
    def setUp(self):
        self.fetcher = JDFetcher()

    def test_builds_with_all_fields(self):
        result = self.fetcher.build_from_form(
            role='Backend Engineer',
            company='Acme Corp',
            skills='Python, Django',
            experience_years=3,
            industry='SaaS',
            extra_details='Remote friendly',
        )
        self.assertIn('Backend Engineer', result)
        self.assertIn('Acme Corp', result)
        self.assertIn('Python, Django', result)
        self.assertIn('3 year(s)', result)
        self.assertIn('SaaS', result)
        self.assertIn('Remote friendly', result)

    def test_raises_if_no_fields(self):
        with self.assertRaises(ValueError):
            self.fetcher.build_from_form()

    def test_builds_with_only_role(self):
        result = self.fetcher.build_from_form(role='Data Scientist')
        self.assertIn('Data Scientist', result)
