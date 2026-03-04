"""
Tests for the News Snippet feature:
  - Ingest endpoints (POST /api/v1/ingest/news/, /news/bulk/, /news/deactivate/)
  - Feed endpoints (GET /api/v1/feed/news/, /news/<id>/)
"""
import uuid

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from analyzer.models import NewsSnippet


CRAWLER_KEY = 'test-crawler-key-12345'


def _ensure_free_plan():
    from accounts.models import Plan
    Plan.objects.get_or_create(
        slug='free',
        defaults={'name': 'Free', 'billing_cycle': 'free', 'price': 0, 'credits_per_month': 2},
    )


def _make_snippet_data(**overrides):
    """Return valid news snippet payload with sensible defaults."""
    data = {
        'uuid': str(uuid.uuid4()),
        'headline': 'TCS Announces Mega Hiring Drive for 2026',
        'summary': 'TCS plans to hire 40,000 freshers in 2026, focusing on AI and cloud skills.',
        'source_url': f'https://example.com/news/{uuid.uuid4().hex[:8]}',
        'source_name': 'Economic Times',
        'category': 'hiring',
        'relevance_score': 9,
        'sentiment': 'positive',
        'region': 'India',
        'tags': ['TCS', 'hiring'],
        'company_mentions': ['TCS'],
        'published_at': '2026-03-04T08:00:00Z',
    }
    data.update(overrides)
    return data


# ── Ingest Tests ─────────────────────────────────────────────────────────────


@override_settings(CRAWLER_API_KEY=CRAWLER_KEY)
class NewsSnippetIngestTests(TestCase):
    """Tests for POST /api/v1/ingest/news/ (single upsert)."""

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_X_CRAWLER_KEY=CRAWLER_KEY)

    def test_single_ingest_creates_snippet(self):
        data = _make_snippet_data()
        resp = self.client.post('/api/v1/ingest/news/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['uuid'], data['uuid'])
        self.assertTrue(NewsSnippet.objects.filter(uuid=data['uuid']).exists())

    def test_single_ingest_upsert_updates(self):
        data = _make_snippet_data()
        self.client.post('/api/v1/ingest/news/', data, format='json')
        data['headline'] = 'Updated Headline'
        resp = self.client.post('/api/v1/ingest/news/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        snippet = NewsSnippet.objects.get(uuid=data['uuid'])
        self.assertEqual(snippet.headline, 'Updated Headline')
        # Should not create a duplicate
        self.assertEqual(NewsSnippet.objects.filter(uuid=data['uuid']).count(), 1)

    def test_single_ingest_requires_auth(self):
        client = APIClient()  # no key
        data = _make_snippet_data()
        resp = client.post('/api/v1/ingest/news/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_single_ingest_validates_category(self):
        data = _make_snippet_data(category='invalid_category')
        resp = self.client.post('/api/v1/ingest/news/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_single_ingest_validates_required_fields(self):
        resp = self.client.post('/api/v1/ingest/news/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_single_ingest_validates_relevance_range(self):
        data = _make_snippet_data(relevance_score=15)
        resp = self.client.post('/api/v1/ingest/news/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(CRAWLER_API_KEY=CRAWLER_KEY)
class NewsSnippetBulkIngestTests(TestCase):
    """Tests for POST /api/v1/ingest/news/bulk/."""

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_X_CRAWLER_KEY=CRAWLER_KEY)

    def test_bulk_ingest_success(self):
        snippets = [_make_snippet_data() for _ in range(3)]
        resp = self.client.post(
            '/api/v1/ingest/news/bulk/',
            {'snippets': snippets},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['ingested'], 3)
        self.assertEqual(resp.data['failed'], 0)
        self.assertEqual(NewsSnippet.objects.count(), 3)

    def test_bulk_ingest_partial_failure(self):
        good = _make_snippet_data()
        bad = _make_snippet_data(category='INVALID')
        resp = self.client.post(
            '/api/v1/ingest/news/bulk/',
            {'snippets': [good, bad]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['ingested'], 1)
        self.assertEqual(resp.data['failed'], 1)
        self.assertEqual(len(resp.data['errors']), 1)

    def test_bulk_ingest_rejects_non_list(self):
        resp = self.client.post(
            '/api/v1/ingest/news/bulk/',
            {'snippets': 'not-a-list'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_ingest_max_200(self):
        snippets = [_make_snippet_data() for _ in range(201)]
        resp = self.client.post(
            '/api/v1/ingest/news/bulk/',
            {'snippets': snippets},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_ingest_requires_auth(self):
        client = APIClient()
        resp = client.post(
            '/api/v1/ingest/news/bulk/',
            {'snippets': [_make_snippet_data()]},
            format='json',
        )
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


@override_settings(CRAWLER_API_KEY=CRAWLER_KEY)
class NewsSnippetDeactivateTests(TestCase):
    """Tests for POST /api/v1/ingest/news/deactivate/."""

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_X_CRAWLER_KEY=CRAWLER_KEY)

    def _create_snippet(self, **kwargs):
        data = _make_snippet_data(**kwargs)
        snippet_uuid = data.pop('uuid')
        return NewsSnippet.objects.create(uuid=snippet_uuid, **data)

    def test_deactivate_marks_inactive(self):
        s1 = self._create_snippet()
        s2 = self._create_snippet()
        resp = self.client.post(
            '/api/v1/ingest/news/deactivate/',
            {'uuids': [str(s1.uuid), str(s2.uuid)]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['deactivated'], 2)
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertFalse(s1.is_active)
        self.assertFalse(s2.is_active)

    def test_deactivate_idempotent(self):
        s = self._create_snippet()
        s.is_active = False
        s.save()
        resp = self.client.post(
            '/api/v1/ingest/news/deactivate/',
            {'uuids': [str(s.uuid)]},
            format='json',
        )
        self.assertEqual(resp.data['deactivated'], 0)

    def test_deactivate_rejects_non_list(self):
        resp = self.client.post(
            '/api/v1/ingest/news/deactivate/',
            {'uuids': 'not-a-list'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── Feed Tests ───────────────────────────────────────────────────────────────


class NewsFeedTests(TestCase):
    """Tests for GET /api/v1/feed/news/ and /api/v1/feed/news/<id>/."""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user(username='newsuser', password='StrongPass123!')
        self.client = APIClient()
        token_resp = self.client.post(
            '/api/v1/auth/login/',
            {'username': 'newsuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_resp.data["access"]}')

    def _create_snippet(self, **kwargs):
        data = _make_snippet_data(**kwargs)
        snippet_uuid = data.pop('uuid')
        return NewsSnippet.objects.create(uuid=snippet_uuid, **data)

    # ── List endpoint ────────────────────────────────────────────────

    def test_feed_list_returns_active_approved(self):
        self._create_snippet()
        self._create_snippet(is_active=False)      # inactive
        self._create_snippet(is_approved=False)     # not approved
        self._create_snippet(is_flagged=True)       # flagged
        resp = self.client.get('/api/v1/feed/news/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(len(resp.data['results']), 1)

    def test_feed_list_pagination(self):
        for _ in range(25):
            self._create_snippet()
        resp = self.client.get('/api/v1/feed/news/?page=1&page_size=10')
        self.assertEqual(resp.data['page'], 1)
        self.assertEqual(resp.data['page_size'], 10)
        self.assertEqual(len(resp.data['results']), 10)
        self.assertEqual(resp.data['count'], 25)
        self.assertEqual(resp.data['total_pages'], 3)

    def test_feed_list_filter_category(self):
        self._create_snippet(category='hiring')
        self._create_snippet(category='ai_automation')
        resp = self.client.get('/api/v1/feed/news/?category=hiring')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['category'], 'hiring')

    def test_feed_list_filter_region(self):
        self._create_snippet(region='India')
        self._create_snippet(region='US')
        resp = self.client.get('/api/v1/feed/news/?region=India')
        self.assertEqual(resp.data['count'], 1)

    def test_feed_list_filter_sentiment(self):
        self._create_snippet(sentiment='positive')
        self._create_snippet(sentiment='negative')
        resp = self.client.get('/api/v1/feed/news/?sentiment=positive')
        self.assertEqual(resp.data['count'], 1)

    def test_feed_list_search(self):
        self._create_snippet(headline='Python demand surges in 2026')
        self._create_snippet(headline='Layoffs at BigCorp')
        resp = self.client.get('/api/v1/feed/news/?search=python')
        self.assertEqual(resp.data['count'], 1)

    def test_feed_list_requires_auth(self):
        unauthed = APIClient()
        resp = unauthed.get('/api/v1/feed/news/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── Detail endpoint ──────────────────────────────────────────────

    def test_feed_detail_returns_snippet(self):
        s = self._create_snippet()
        resp = self.client.get(f'/api/v1/feed/news/{s.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['headline'], s.headline)

    def test_feed_detail_404_for_inactive(self):
        s = self._create_snippet(is_active=False)
        resp = self.client.get(f'/api/v1/feed/news/{s.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_feed_detail_404_for_missing(self):
        fake_id = uuid.uuid4()
        resp = self.client.get(f'/api/v1/feed/news/{fake_id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_feed_detail_requires_auth(self):
        s = self._create_snippet()
        unauthed = APIClient()
        resp = unauthed.get(f'/api/v1/feed/news/{s.id}/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── Response shape ───────────────────────────────────────────────

    def test_feed_list_response_shape(self):
        self._create_snippet()
        resp = self.client.get('/api/v1/feed/news/')
        self.assertIn('count', resp.data)
        self.assertIn('page', resp.data)
        self.assertIn('page_size', resp.data)
        self.assertIn('total_pages', resp.data)
        self.assertIn('results', resp.data)
        item = resp.data['results'][0]
        for key in ('id', 'uuid', 'headline', 'summary', 'source_url',
                     'source_name', 'category', 'tags', 'sentiment',
                     'relevance_score', 'region', 'published_at'):
            self.assertIn(key, item, f'Missing key: {key}')
        # Should NOT expose internal fields
        for key in ('is_active', 'is_approved', 'is_flagged', 'flag_reason'):
            self.assertNotIn(key, item, f'Unexpected key: {key}')
