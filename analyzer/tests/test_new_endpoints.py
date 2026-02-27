"""
Tests for new analyzer endpoints added in the backend backlog sweep.

Covers:
- POST /api/analyses/<id>/cancel/   — cancel stuck analysis
- POST /api/analyses/bulk-delete/   — bulk soft-delete
- GET  /api/analyses/<id>/export-json/ — JSON export
- GET  /api/account/export/         — GDPR account data export
- GET  /api/dashboard/stats/        — enhanced dashboard stats
- Plan quota enforcement on analyze
"""

from unittest.mock import patch, MagicMock
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from analyzer.models import ResumeAnalysis, Resume


def _ensure_free_plan():
    from accounts.models import Plan
    plan, _ = Plan.objects.get_or_create(
        slug='free',
        defaults={
            'name': 'Free', 'billing_cycle': 'free', 'price': 0,
            'credits_per_month': 2, 'analyses_per_month': 0,
            'max_resumes_stored': 5,
        },
    )
    return plan


def _give_credits(user, amount=100):
    from accounts.models import Wallet
    wallet, _ = Wallet.objects.get_or_create(user=user)
    wallet.balance = amount
    wallet.save(update_fields=['balance'])


def _make_pdf():
    return SimpleUploadedFile('resume.pdf', b'%PDF-1.4 fake content', content_type='application/pdf')


def _auth(client, username='testuser', email='test@example.com'):
    user = User.objects.create_user(username=username, email=email, password='StrongPass123!')
    resp = client.post(
        '/api/auth/login/',
        {'username': username, 'password': 'StrongPass123!'},
        format='json',
    )
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client, user


def _create_done_analysis(user, **kwargs):
    """Create a completed analysis for testing."""
    resume, _ = Resume.get_or_create_from_upload(
        user,
        SimpleUploadedFile('r.pdf', b'%PDF-1.4 fake', content_type='application/pdf'),
    )
    defaults = {
        'user': user,
        'resume_file': resume.file.name,
        'resume': resume,
        'jd_input_type': 'text',
        'jd_text': 'Python developer role',
        'jd_role': 'Backend Engineer',
        'jd_company': 'TestCo',
        'status': ResumeAnalysis.STATUS_DONE,
        'pipeline_step': ResumeAnalysis.STEP_DONE,
        'overall_grade': 'B',
        'ats_score': 78,
        'scores': {'generic_ats': 78, 'workday_ats': 70, 'greenhouse_ats': 72},
        'keyword_analysis': {'matched_keywords': ['Python'], 'missing_keywords': ['Docker']},
        'section_feedback': [{'section_name': 'Skills', 'score': 70, 'feedback': ['Good'], 'ats_flags': []}],
        'sentence_suggestions': [],
        'formatting_flags': [],
        'quick_wins': [{'priority': 1, 'action': 'Add Docker'}],
        'summary': 'Good profile.',
        'ai_provider_used': 'OpenRouterProvider',
    }
    defaults.update(kwargs)
    return ResumeAnalysis.all_objects.create(**defaults)


# ── Cancel View ──────────────────────────────────────────────────────────────


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class AnalysisCancelViewTests(TestCase):

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='canceluser', email='cancel@test.com')
        _give_credits(self.user)

    def test_cancel_processing_analysis(self):
        analysis = _create_done_analysis(
            self.user,
            status=ResumeAnalysis.STATUS_PROCESSING,
            pipeline_step=ResumeAnalysis.STEP_JD_SCRAPE,
            celery_task_id='fake-celery-id',
            credits_deducted=True,
        )
        with patch('resume_ai.celery.app') as mock_celery:
            resp = self.client.post(f'/api/analyses/{analysis.id}/cancel/')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'failed')
        self.assertIn('cancelled', resp.data['detail'].lower())

    def test_cancel_already_done(self):
        analysis = _create_done_analysis(self.user)
        resp = self.client.post(f'/api/analyses/{analysis.id}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_not_found(self):
        resp = self.client.post('/api/analyses/99999/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_other_users_analysis(self):
        other = User.objects.create_user('other', 'other@test.com', 'StrongPass123!')
        analysis = _create_done_analysis(
            other,
            status=ResumeAnalysis.STATUS_PROCESSING,
            pipeline_step=ResumeAnalysis.STEP_JD_SCRAPE,
        )
        resp = self.client.post(f'/api/analyses/{analysis.id}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_auth(self):
        resp = APIClient().post('/api/analyses/1/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Bulk Delete ──────────────────────────────────────────────────────────────


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class AnalysisBulkDeleteViewTests(TestCase):

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='bulkdeluser', email='bulkdel@test.com')

    def test_bulk_delete_success(self):
        a1 = _create_done_analysis(self.user)
        a2 = _create_done_analysis(self.user, jd_role='Frontend Dev')
        resp = self.client.post(
            '/api/analyses/bulk-delete/',
            {'ids': [a1.id, a2.id]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['deleted'], 2)
        # Verify soft-deleted
        self.assertIsNotNone(ResumeAnalysis.all_objects.get(pk=a1.id).deleted_at)
        self.assertIsNotNone(ResumeAnalysis.all_objects.get(pk=a2.id).deleted_at)

    def test_bulk_delete_empty_list(self):
        resp = self.client.post(
            '/api/analyses/bulk-delete/',
            {'ids': []},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_delete_missing_ids(self):
        resp = self.client.post(
            '/api/analyses/bulk-delete/',
            {},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_delete_over_50(self):
        resp = self.client.post(
            '/api/analyses/bulk-delete/',
            {'ids': list(range(1, 52))},  # 51 IDs
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('50', resp.data['detail'])

    def test_bulk_delete_ignores_others_analyses(self):
        other = User.objects.create_user('other2', 'other2@test.com', 'StrongPass123!')
        other_analysis = _create_done_analysis(other)
        resp = self.client.post(
            '/api/analyses/bulk-delete/',
            {'ids': [other_analysis.id]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['deleted'], 0)  # Can't delete someone else's

    def test_requires_auth(self):
        resp = APIClient().post('/api/analyses/bulk-delete/', {'ids': [1]}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Export JSON ──────────────────────────────────────────────────────────────


class AnalysisExportJSONViewTests(TestCase):

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='jsonuser', email='json@test.com')

    def test_export_json_success(self):
        analysis = _create_done_analysis(self.user)
        resp = self.client.get(f'/api/analyses/{analysis.id}/export-json/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('application/json', resp['Content-Type'])
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertIn('Backend_Engineer', resp['Content-Disposition'])

    def test_export_json_incomplete_analysis(self):
        analysis = _create_done_analysis(
            self.user,
            status=ResumeAnalysis.STATUS_PROCESSING,
            pipeline_step=ResumeAnalysis.STEP_JD_SCRAPE,
        )
        resp = self.client.get(f'/api/analyses/{analysis.id}/export-json/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_export_json_not_found(self):
        resp = self.client.get('/api/analyses/99999/export-json/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_auth(self):
        resp = APIClient().get('/api/analyses/1/export-json/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Account Data Export (GDPR) ───────────────────────────────────────────────


class AccountDataExportViewTests(TestCase):

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='gdpruser', email='gdpr@test.com')

    def test_export_account_data_success(self):
        _create_done_analysis(self.user)
        resp = self.client.get('/api/account/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('application/json', resp['Content-Type'])
        self.assertIn('attachment', resp['Content-Disposition'])

        import json
        data = json.loads(resp.content)
        self.assertIn('profile', data)
        self.assertIn('analyses', data)
        self.assertIn('resumes', data)
        self.assertIn('wallet', data)
        self.assertIn('consent_logs', data)
        self.assertIn('notifications', data)
        self.assertEqual(data['profile']['username'], 'gdpruser')
        self.assertEqual(data['profile']['email'], 'gdpr@test.com')

    def test_export_empty_account(self):
        """User with no analyses should still export successfully."""
        resp = self.client.get('/api/account/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        import json
        data = json.loads(resp.content)
        self.assertEqual(data['analyses'], [])

    def test_requires_auth(self):
        resp = APIClient().get('/api/account/export/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Dashboard Stats (enhanced) ──────────────────────────────────────────────


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class DashboardStatsEnhancedTests(TestCase):

    def setUp(self):
        _ensure_free_plan()
        cache.clear()
        self.client = APIClient()
        self.client, self.user = _auth(self.client, username='dashuser', email='dash@test.com')

    def test_dashboard_stats_empty(self):
        resp = self.client.get('/api/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_analyses'], 0)
        self.assertIsNone(resp.data['average_ats_score'])
        self.assertEqual(resp.data['grade_distribution'], {})
        self.assertEqual(resp.data['top_industries'], [])

    def test_dashboard_stats_with_data(self):
        _create_done_analysis(self.user, overall_grade='A', ats_score=90, jd_industry='Technology')
        _create_done_analysis(self.user, overall_grade='B', ats_score=75, jd_industry='Technology')
        _create_done_analysis(self.user, overall_grade='B', ats_score=72, jd_industry='Finance')

        cache.clear()
        resp = self.client.get('/api/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_analyses'], 3)
        self.assertIsNotNone(resp.data['average_ats_score'])

        # Grade distribution
        grades = resp.data['grade_distribution']
        self.assertEqual(grades.get('B'), 2)
        self.assertEqual(grades.get('A'), 1)

        # Top industries
        industries = resp.data['top_industries']
        self.assertTrue(len(industries) >= 1)
        self.assertEqual(industries[0]['jd_industry'], 'Technology')
        self.assertEqual(industries[0]['count'], 2)

    def test_score_trend_includes_per_ats(self):
        _create_done_analysis(
            self.user,
            scores={'generic_ats': 85, 'workday_ats': 70, 'greenhouse_ats': 75},
        )
        cache.clear()
        resp = self.client.get('/api/dashboard/stats/')
        trend = resp.data['score_trend']
        self.assertEqual(len(trend), 1)
        self.assertEqual(trend[0]['generic_ats'], 85)
        self.assertEqual(trend[0]['workday_ats'], 70)
        self.assertEqual(trend[0]['greenhouse_ats'], 75)

    def test_dashboard_stats_cached(self):
        """Second request should be cached (no extra DB queries)."""
        _create_done_analysis(self.user)
        cache.clear()
        resp1 = self.client.get('/api/dashboard/stats/')
        resp2 = self.client.get('/api/dashboard/stats/')
        self.assertEqual(resp1.data, resp2.data)

    def test_requires_auth(self):
        resp = APIClient().get('/api/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Plan Quota Enforcement ───────────────────────────────────────────────────


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class PlanQuotaTests(TestCase):
    """Test plan-based quotas on AnalyzeResumeView."""

    def setUp(self):
        from accounts.models import Plan
        self.plan = Plan.objects.create(
            name='Limited', slug='limited', billing_cycle='monthly',
            price=99, is_active=True, credits_per_month=10,
            analyses_per_month=2, max_resumes_stored=3,
            max_resume_size_mb=1,
        )
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user('quotauser', 'quota@test.com', 'StrongPass123!')
        # Assign plan
        profile = self.user.profile
        profile.plan = self.plan
        profile.save(update_fields=['plan'])
        _give_credits(self.user)
        resp = self.client.post(
            '/api/auth/login/',
            {'username': 'quotauser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    @patch('analyzer.views.run_analysis_task')
    def test_monthly_quota_enforced(self, mock_task):
        mock_task.delay.return_value = MagicMock(id='fake-id')
        # Create 2 analyses (the limit)
        for i in range(2):
            _create_done_analysis(self.user, jd_role=f'Role {i}')

        # 3rd should be blocked
        cache.clear()
        resp = self.client.post(
            '/api/analyze/',
            {'resume_file': _make_pdf(), 'jd_input_type': 'text', 'jd_text': 'Dev role'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('limit', resp.data['detail'].lower())

    def test_pdf_export_feature_flag(self):
        """When plan.pdf_export is False, export should be blocked."""
        self.plan.pdf_export = False
        self.plan.save(update_fields=['pdf_export'])

        analysis = _create_done_analysis(self.user)
        resp = self.client.get(f'/api/analyses/{analysis.id}/export-pdf/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_share_feature_flag(self):
        """When plan.share_analysis is False, sharing should be blocked."""
        self.plan.share_analysis = False
        self.plan.save(update_fields=['share_analysis'])

        analysis = _create_done_analysis(self.user)
        resp = self.client.post(f'/api/analyses/{analysis.id}/share/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
