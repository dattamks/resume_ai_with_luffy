"""
Tests for Phase 11 — Smart Job Alerts.

Covers:
  - JobAlert CRUD endpoints (plan gating, quota, create, detail, update, delete)
  - JobAlertMatch list + feedback endpoints
  - Manual run endpoint
  - Job search profile extraction task
  - Job source providers (mocked)
  - Job matcher service (mocked LLM)
  - Discover jobs task (mocked sources)
"""
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import Plan, Wallet
from analyzer.models import (
    Resume, JobAlert, DiscoveredJob, JobMatch,
    JobAlertRun, JobSearchProfile,
)


def _make_pdf(content=b'%PDF-1.4 fake content'):
    return SimpleUploadedFile('resume.pdf', content, content_type='application/pdf')


def _ensure_plans():
    """Create free + pro plans with appropriate settings."""
    Plan.objects.get_or_create(
        slug='free',
        defaults={
            'name': 'Free', 'billing_cycle': 'free', 'price': 0,
            'credits_per_month': 2, 'job_notifications': False, 'max_job_alerts': 0,
        },
    )
    Plan.objects.get_or_create(
        slug='pro',
        defaults={
            'name': 'Pro', 'billing_cycle': 'monthly', 'price': 499,
            'credits_per_month': 25, 'job_notifications': True, 'max_job_alerts': 3,
        },
    )


def _give_credits(user, amount=100):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    wallet.balance = amount
    wallet.save(update_fields=['balance'])


def _set_plan(user, slug):
    plan = Plan.objects.get(slug=slug)
    profile = user.profile
    profile.plan = plan
    profile.save(update_fields=['plan'])


def _auth(client, username='alertuser', password='StrongPass123!'):
    user = User.objects.create_user(username=username, password=password)
    resp = client.post(
        '/api/auth/login/',
        {'username': username, 'password': password},
        format='json',
    )
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client, user


class JobAlertCRUDTests(TestCase):
    """Test JobAlert list, create, detail, update, delete endpoints."""

    def setUp(self):
        _ensure_plans()
        self.client = APIClient()
        self.client, self.user = _auth(self.client)
        _give_credits(self.user)
        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())

    def test_list_empty(self):
        resp = self.client.get('/api/job-alerts/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])

    def test_create_requires_pro(self):
        """Free plan users cannot create job alerts."""
        resp = self.client.post('/api/job-alerts/', {
            'resume': str(self.resume.id),
            'frequency': 'weekly',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Pro plan', resp.data['detail'])

    @patch('analyzer.views.extract_job_search_profile_task')
    def test_create_success_pro(self, mock_task):
        """Pro plan users can create job alerts."""
        _set_plan(self.user, 'pro')
        mock_task.delay.return_value = MagicMock()

        resp = self.client.post('/api/job-alerts/', {
            'resume': str(self.resume.id),
            'frequency': 'weekly',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('id', resp.data)
        self.assertEqual(resp.data['frequency'], 'weekly')
        self.assertTrue(resp.data['is_active'])
        # Verify profile extraction task was triggered
        mock_task.delay.assert_called_once()

    @patch('analyzer.views.extract_job_search_profile_task')
    def test_create_max_alerts_quota(self, mock_task):
        """Pro users cannot exceed max_job_alerts."""
        _set_plan(self.user, 'pro')
        mock_task.delay.return_value = MagicMock()

        # Create 3 alerts (Pro max = 3)
        for i in range(3):
            resume, _ = Resume.get_or_create_from_upload(
                self.user, _make_pdf(f'%PDF-1.4 fake content {i}'.encode()),
            )
            resp = self.client.post('/api/job-alerts/', {
                'resume': str(resume.id),
                'frequency': 'daily',
            }, format='json')
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        # 4th should fail
        resume4, _ = Resume.get_or_create_from_upload(
            self.user, _make_pdf(b'%PDF-1.4 fake content 4th'),
        )
        resp = self.client.post('/api/job-alerts/', {
            'resume': str(resume4.id),
            'frequency': 'daily',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('maximum', resp.data['detail'])

    @patch('analyzer.views.extract_job_search_profile_task')
    def test_detail_and_update(self, mock_task):
        """GET and PUT on a job alert."""
        _set_plan(self.user, 'pro')
        mock_task.delay.return_value = MagicMock()

        # Create
        resp = self.client.post('/api/job-alerts/', {
            'resume': str(self.resume.id),
            'frequency': 'daily',
        }, format='json')
        alert_id = resp.data['id']

        # GET detail
        resp = self.client.get(f'/api/job-alerts/{alert_id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['frequency'], 'daily')

        # PUT — change frequency
        resp = self.client.put(f'/api/job-alerts/{alert_id}/', {
            'frequency': 'weekly',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['frequency'], 'weekly')

    @patch('analyzer.views.extract_job_search_profile_task')
    def test_delete_deactivates(self, mock_task):
        """DELETE deactivates the alert (soft delete)."""
        _set_plan(self.user, 'pro')
        mock_task.delay.return_value = MagicMock()

        resp = self.client.post('/api/job-alerts/', {
            'resume': str(self.resume.id),
            'frequency': 'weekly',
        }, format='json')
        alert_id = resp.data['id']

        resp = self.client.delete(f'/api/job-alerts/{alert_id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Verify deactivated
        alert = JobAlert.objects.get(id=alert_id)
        self.assertFalse(alert.is_active)

    def test_detail_404_wrong_user(self):
        """Users can't see other users' alerts."""
        resp = self.client.get(f'/api/job-alerts/{uuid.uuid4()}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @patch('analyzer.views.extract_job_search_profile_task')
    def test_create_with_preferences(self, mock_task):
        """Alert can be created with custom preferences."""
        _set_plan(self.user, 'pro')
        mock_task.delay.return_value = MagicMock()

        resp = self.client.post('/api/job-alerts/', {
            'resume': str(self.resume.id),
            'frequency': 'daily',
            'preferences': {
                'remote_ok': True,
                'location': 'London, UK',
                'salary_min': 50000,
                'excluded_companies': ['BadCorp'],
            },
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['preferences']['location'], 'London, UK')


class JobAlertMatchTests(TestCase):
    """Test match listing, feedback, and manual run endpoints."""

    def setUp(self):
        _ensure_plans()
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='matchuser')
        _give_credits(self.user)
        _set_plan(self.user, 'pro')
        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())

        # Create alert + search profile + discovered job + match
        self.alert = JobAlert.objects.create(
            user=self.user,
            resume=self.resume,
            frequency='weekly',
            is_active=True,
            next_run_at=timezone.now() + timedelta(days=7),
        )
        self.profile = JobSearchProfile.objects.create(
            resume=self.resume,
            titles=['Python Developer'],
            skills=['Python', 'Django'],
            seniority='senior',
        )
        self.dj = DiscoveredJob.objects.create(
            source='serpapi',
            external_id='test-job-1',
            url='https://example.com/job/1',
            title='Senior Python Developer',
            company='Acme Corp',
            location='London',
        )
        self.match = JobMatch.objects.create(
            job_alert=self.alert,
            discovered_job=self.dj,
            relevance_score=85,
            match_reason='Strong Python + Django match',
        )

    def test_list_matches(self):
        resp = self.client.get(f'/api/job-alerts/{self.alert.id}/matches/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['relevance_score'], 85)
        self.assertEqual(resp.data['results'][0]['job']['title'], 'Senior Python Developer')

    def test_list_matches_filter_feedback(self):
        resp = self.client.get(f'/api/job-alerts/{self.alert.id}/matches/?feedback=pending')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

        resp = self.client.get(f'/api/job-alerts/{self.alert.id}/matches/?feedback=applied')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)

    def test_feedback_success(self):
        resp = self.client.post(
            f'/api/job-alerts/{self.alert.id}/matches/{self.match.id}/feedback/',
            {'user_feedback': 'relevant'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.match.refresh_from_db()
        self.assertEqual(self.match.user_feedback, 'relevant')

    def test_feedback_invalid(self):
        resp = self.client.post(
            f'/api/job-alerts/{self.alert.id}/matches/{self.match.id}/feedback/',
            {'user_feedback': 'pending'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_feedback_applied(self):
        resp = self.client.post(
            f'/api/job-alerts/{self.alert.id}/matches/{self.match.id}/feedback/',
            {'user_feedback': 'applied'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.match.refresh_from_db()
        self.assertEqual(self.match.user_feedback, 'applied')

    def test_feedback_404_wrong_match(self):
        resp = self.client.post(
            f'/api/job-alerts/{self.alert.id}/matches/{uuid.uuid4()}/feedback/',
            {'user_feedback': 'relevant'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @patch('analyzer.tasks.discover_jobs_for_alert_task')
    def test_manual_run_trigger(self, mock_discover):
        mock_discover.delay.return_value = MagicMock()
        resp = self.client.post(f'/api/job-alerts/{self.alert.id}/run/')
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        mock_discover.delay.assert_called_once_with(str(self.alert.id))

    @patch('analyzer.tasks.discover_jobs_for_alert_task')
    def test_manual_run_inactive_alert(self, mock_discover):
        self.alert.is_active = False
        self.alert.save(update_fields=['is_active'])
        resp = self.client.post(f'/api/job-alerts/{self.alert.id}/run/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        mock_discover.delay.assert_not_called()


class JobSearchProfileExtractionTest(TestCase):
    """Test the extract_job_search_profile_task (mocked LLM)."""

    def setUp(self):
        _ensure_plans()
        self.user = User.objects.create_user(username='profileuser', password='StrongPass123!')
        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())

    @patch('analyzer.services.job_search_profile.OpenAI')
    def test_extraction_success(self, MockOpenAI):
        """Mock LLM returns valid profile JSON."""
        # Create an analysis with resume_text for the profile extractor to use
        from analyzer.models import ResumeAnalysis
        ResumeAnalysis.objects.create(
            user=self.user,
            resume_file=_make_pdf(),
            resume=self.resume,
            resume_text='John Doe, 5 years Python developer at Acme Corp...',
            jd_input_type='text',
            jd_text='Test JD',
            status=ResumeAnalysis.STATUS_DONE,
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''{
            "titles": ["Senior Python Developer", "Backend Engineer"],
            "skills": ["Python", "Django", "PostgreSQL"],
            "seniority": "senior",
            "industries": ["Technology", "FinTech"],
            "locations": ["London"],
            "experience_years": 5
        }'''
        MockOpenAI.return_value.chat.completions.create.return_value = mock_response

        from analyzer.tasks import extract_job_search_profile_task
        extract_job_search_profile_task(str(self.resume.id))

        # Verify profile was created
        profile = JobSearchProfile.objects.get(resume=self.resume)
        self.assertEqual(profile.seniority, 'senior')
        self.assertIn('Python', profile.skills)
        self.assertEqual(profile.experience_years, 5)
        self.assertEqual(len(profile.titles), 2)


class JobSourceProvidersTest(TestCase):
    """Test job source providers with mocked API responses."""

    @patch('analyzer.services.job_sources.serpapi_source.requests.get')
    def test_serpapi_source(self, mock_get):
        from analyzer.services.job_sources.serpapi_source import SerpAPIJobSource

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'jobs_results': [
                {
                    'job_id': 'test-123',
                    'title': 'Python Developer',
                    'company_name': 'Acme Corp',
                    'location': 'London, UK',
                    'description': 'Build awesome things with Python...',
                    'related_links': [{'link': 'https://example.com/job'}],
                    'detected_extensions': {'salary': '$120k'},
                },
            ],
        }
        mock_get.return_value = mock_response

        source = SerpAPIJobSource(api_key='test-key')
        results = source.search(queries=['Python Developer'], location='London')

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, 'serpapi')
        self.assertEqual(results[0].title, 'Python Developer')
        self.assertEqual(results[0].company, 'Acme Corp')
        self.assertEqual(results[0].external_id, 'test-123')

    @patch('analyzer.services.job_sources.adzuna_source.requests.get')
    def test_adzuna_source(self, mock_get):
        from analyzer.services.job_sources.adzuna_source import AdzunaJobSource

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'results': [
                {
                    'id': 98765,
                    'title': 'Django Developer',
                    'company': {'display_name': 'TechCo'},
                    'location': {'display_name': 'Manchester'},
                    'description': 'Django web development...',
                    'redirect_url': 'https://adzuna.com/job/98765',
                    'salary_min': 45000,
                    'salary_max': 65000,
                    'created': '2026-02-25T00:00:00Z',
                },
            ],
        }
        mock_get.return_value = mock_response

        source = AdzunaJobSource(app_id='test-id', app_key='test-key', country='gb')
        results = source.search(queries=['Django Developer'], location='Manchester')

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, 'adzuna')
        self.assertEqual(results[0].title, 'Django Developer')
        self.assertEqual(results[0].company, 'TechCo')
        self.assertEqual(results[0].external_id, '98765')

    def test_serpapi_no_key(self):
        from analyzer.services.job_sources.serpapi_source import SerpAPIJobSource
        source = SerpAPIJobSource(api_key='')
        results = source.search(queries=['Python'])
        self.assertEqual(results, [])

    def test_adzuna_no_key(self):
        from analyzer.services.job_sources.adzuna_source import AdzunaJobSource
        source = AdzunaJobSource(app_id='', app_key='')
        results = source.search(queries=['Python'])
        self.assertEqual(results, [])


class JobMatcherServiceTest(TestCase):
    """Test the LLM batch matcher with mocked LLM responses."""

    def setUp(self):
        _ensure_plans()
        self.user = User.objects.create_user(username='matcheruser', password='StrongPass123!')
        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())
        self.alert = JobAlert.objects.create(
            user=self.user, resume=self.resume,
            frequency='weekly', is_active=True,
        )
        self.profile = JobSearchProfile.objects.create(
            resume=self.resume,
            titles=['Python Developer'],
            skills=['Python', 'Django'],
            seniority='mid',
        )

    @patch('analyzer.services.job_matcher.OpenAI')
    def test_match_jobs_success(self, MockOpenAI):
        dj1 = DiscoveredJob.objects.create(
            source='serpapi', external_id='match-1',
            url='https://example.com/1', title='Python Dev',
            company='Acme',
        )
        dj2 = DiscoveredJob.objects.create(
            source='serpapi', external_id='match-2',
            url='https://example.com/2', title='Java Dev',
            company='OtherCo',
        )

        import json
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {'id': str(dj1.id), 'score': 85, 'reason': 'Strong Python match'},
            {'id': str(dj2.id), 'score': 30, 'reason': 'Wrong language'},
        ])
        MockOpenAI.return_value.chat.completions.create.return_value = mock_response

        from analyzer.services.job_matcher import match_jobs
        results = match_jobs(self.alert, [dj1, dj2])

        # Only dj1 should be above threshold (60)
        above_threshold = [r for r in results if r['score'] >= 60]
        self.assertEqual(len(above_threshold), 1)
        self.assertEqual(above_threshold[0]['score'], 85)


class DiscoverJobsTaskTest(TestCase):
    """Test the periodic discover_jobs_task with mocked sources."""

    def setUp(self):
        _ensure_plans()
        self.user = User.objects.create_user(username='discoveruser', password='StrongPass123!')
        _give_credits(self.user)
        _set_plan(self.user, 'pro')
        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())

        self.alert = JobAlert.objects.create(
            user=self.user,
            resume=self.resume,
            frequency='daily',
            is_active=True,
            next_run_at=timezone.now() - timedelta(hours=1),  # Due
        )
        self.profile = JobSearchProfile.objects.create(
            resume=self.resume,
            titles=['Backend Developer', 'Python Engineer'],
            skills=['Python', 'Django'],
            seniority='senior',
            locations=['Remote'],
        )

    @patch('analyzer.tasks.match_jobs_task')
    @patch('analyzer.services.job_sources.factory.get_job_sources')
    def test_discover_creates_jobs_and_chains_matcher(self, mock_sources, mock_match):
        from analyzer.services.job_sources.base import RawJobListing

        mock_source = MagicMock()
        mock_source.name.return_value = 'MockSource'
        mock_source.search.return_value = [
            RawJobListing(
                source='serpapi',
                external_id='disc-1',
                url='https://example.com/job/disc-1',
                title='Backend Dev',
                company='GoodCo',
            ),
            RawJobListing(
                source='serpapi',
                external_id='disc-2',
                url='https://example.com/job/disc-2',
                title='Python Lead',
                company='GreatCo',
            ),
        ]
        mock_sources.return_value = [mock_source]
        mock_match.delay.return_value = MagicMock()

        from analyzer.tasks import discover_jobs_task
        discover_jobs_task()

        # Verify DiscoveredJob records created
        self.assertEqual(DiscoveredJob.objects.count(), 2)

        # Verify match_jobs_task was chained
        mock_match.delay.assert_called_once()
        _, call_kwargs = mock_match.delay.call_args
        # Should pass alert_id and list of job_ids
        call_args = mock_match.delay.call_args[0]
        self.assertEqual(call_args[0], str(self.alert.id))
        self.assertEqual(len(call_args[1]), 2)

        # Verify alert timestamps updated
        self.alert.refresh_from_db()
        self.assertIsNotNone(self.alert.last_run_at)
        self.assertIsNotNone(self.alert.next_run_at)

    @patch('analyzer.tasks.match_jobs_task')
    @patch('analyzer.services.job_sources.factory.get_job_sources')
    def test_discover_respects_excluded_companies(self, mock_sources, mock_match):
        from analyzer.services.job_sources.base import RawJobListing

        self.alert.preferences = {'excluded_companies': ['BadCorp']}
        self.alert.save(update_fields=['preferences'])

        mock_source = MagicMock()
        mock_source.name.return_value = 'MockSource'
        mock_source.search.return_value = [
            RawJobListing(
                source='serpapi', external_id='excl-1',
                url='https://example.com/excl-1', title='Dev',
                company='BadCorp',
            ),
            RawJobListing(
                source='serpapi', external_id='excl-2',
                url='https://example.com/excl-2', title='Dev',
                company='GoodCorp',
            ),
        ]
        mock_sources.return_value = [mock_source]
        mock_match.delay.return_value = MagicMock()

        from analyzer.tasks import discover_jobs_task
        discover_jobs_task()

        # Only 1 job should be saved (BadCorp excluded)
        self.assertEqual(DiscoveredJob.objects.count(), 1)
        self.assertEqual(DiscoveredJob.objects.first().company, 'GoodCorp')

    @patch('analyzer.services.job_sources.factory.get_job_sources')
    def test_discover_skips_alert_without_profile(self, mock_sources):
        """If search profile doesn't exist, skip alert and update next_run_at."""
        self.profile.delete()

        from analyzer.tasks import discover_jobs_task
        discover_jobs_task()

        # Alert should still be updated
        self.alert.refresh_from_db()
        self.assertIsNotNone(self.alert.next_run_at)


class EdgeCaseTests(TestCase):
    """Test edge cases identified during audit."""

    def setUp(self):
        _ensure_plans()
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='edgeuser')
        _give_credits(self.user)
        _set_plan(self.user, 'pro')
        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())

    def test_invalid_page_param(self):
        """?page=abc should not crash — defaults to page 1."""
        alert = JobAlert.objects.create(
            user=self.user, resume=self.resume, frequency='daily',
            is_active=True, next_run_at=timezone.now() + timedelta(days=1),
        )
        resp = self.client.get(f'/api/job-alerts/{alert.id}/matches/?page=abc')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['page'], 1)

    def test_invalid_feedback_filter_rejected(self):
        """?feedback=xyz should return 400."""
        alert = JobAlert.objects.create(
            user=self.user, resume=self.resume, frequency='daily',
            is_active=True, next_run_at=timezone.now() + timedelta(days=1),
        )
        resp = self.client.get(f'/api/job-alerts/{alert.id}/matches/?feedback=xyz')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('analyzer.views.extract_job_search_profile_task')
    def test_duplicate_resume_alert_rejected(self, mock_task):
        """Cannot create two active alerts for the same resume."""
        mock_task.delay.return_value = MagicMock()

        # First alert succeeds
        resp = self.client.post('/api/job-alerts/', {
            'resume': str(self.resume.id), 'frequency': 'daily',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        # Second alert for same resume fails
        resp = self.client.post('/api/job-alerts/', {
            'resume': str(self.resume.id), 'frequency': 'weekly',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already exists', str(resp.data))

    def test_resume_delete_blocked_by_active_alert(self):
        """Cannot delete a resume that has active job alerts."""
        JobAlert.objects.create(
            user=self.user, resume=self.resume, frequency='daily',
            is_active=True, next_run_at=timezone.now() + timedelta(days=1),
        )
        resp = self.client.delete(f'/api/resumes/{self.resume.id}/')
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('job alert', resp.data['detail'].lower())

    def test_update_preferences_must_be_dict(self):
        """PUT with non-dict preferences should be rejected."""
        alert = JobAlert.objects.create(
            user=self.user, resume=self.resume, frequency='daily',
            is_active=True, next_run_at=timezone.now() + timedelta(days=1),
        )
        resp = self.client.put(f'/api/job-alerts/{alert.id}/', {
            'preferences': 'not-a-dict',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('analyzer.tasks.discover_jobs_for_alert_task')
    def test_manual_run_insufficient_credits(self, mock_discover):
        """Manual run with 0 credits should return 402."""
        from accounts.models import Wallet
        wallet = Wallet.objects.get(user=self.user)
        wallet.balance = 0
        wallet.save(update_fields=['balance'])

        alert = JobAlert.objects.create(
            user=self.user, resume=self.resume, frequency='daily',
            is_active=True, next_run_at=timezone.now() + timedelta(days=1),
        )
        JobSearchProfile.objects.create(
            resume=self.resume,
            titles=['Dev'],
            skills=['Python'],
            seniority='mid',
        )
        resp = self.client.post(f'/api/job-alerts/{alert.id}/run/')
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        mock_discover.delay.assert_not_called()

    def test_create_alert_for_other_users_resume(self):
        """Cannot create alert for another user's resume."""
        _set_plan(self.user, 'pro')
        other_user = User.objects.create_user(username='otheruser', password='StrongPass123!')
        other_resume, _ = Resume.get_or_create_from_upload(
            other_user, _make_pdf(b'%PDF-1.4 other content'),
        )
        resp = self.client.post('/api/job-alerts/', {
            'resume': str(other_resume.id), 'frequency': 'daily',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_experience_years_float_parsing(self):
        """LLM returning '5.5' for experience_years should parse to 5."""
        from analyzer.services.job_search_profile import _parse_experience_years
        self.assertEqual(_parse_experience_years(5.5), 5)
        self.assertEqual(_parse_experience_years('7'), 7)
        self.assertIsNone(_parse_experience_years('N/A'))
        self.assertIsNone(_parse_experience_years(None))
        self.assertEqual(_parse_experience_years(0), 0)
