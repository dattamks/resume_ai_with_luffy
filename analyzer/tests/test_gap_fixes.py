"""
Tests for v0.21.0 features: frontend–backend gap fixes.

Covers:
- P0: first_name/last_name writable on PUT /auth/me/
- P0: keyword_match_percent in dashboard score_trend
- P0: aggregated missing keywords in dashboard
- P0: credit usage history in dashboard
- P1: DELETE /generated-resumes/<id>/
- P1: search/filter/sort on analyses
- P1: search/filter/sort on resumes
- P1: job alert total_matches
- P1: bulk delete resumes
- P1: weekly job match count in dashboard
- P2: social links CRUD on PUT /auth/me/
- P2: resume staleness (days_since_upload, last_analyzed_at)
- P2: wallet CSV export
- P2: shared analysis summary
- P2: analysis comparison endpoint
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Plan, Wallet, WalletTransaction
from analyzer.models import (
    ResumeAnalysis, Resume, GeneratedResume,
    JobAlert, JobMatch, DiscoveredJob, JobSearchProfile,
)


class TestMixin:
    """Shared setup."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.free_plan = Plan.objects.create(
            name='Free', slug='free', billing_cycle='free', price=0,
            credits_per_month=2, max_credits_balance=10,
            analyses_per_month=0, max_resumes_stored=50,
            is_active=True, display_order=0,
        )
        self.user = User.objects.create_user(
            username='gaptest', email='gap@test.com', password='StrongPass123!',
            first_name='John', last_name='Doe',
        )
        self._login()

    def _login(self):
        resp = self.client.post('/api/v1/auth/login/', {
            'username': 'gaptest', 'password': 'StrongPass123!',
        }, format='json')
        self.access = resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access}')

    def _give_credits(self, amount=100):
        wallet, _ = Wallet.objects.get_or_create(user=self.user)
        wallet.balance = amount
        wallet.save(update_fields=['balance'])

    def _make_analysis(self, **kwargs):
        defaults = {
            'user': self.user,
            'status': ResumeAnalysis.STATUS_DONE,
            'ats_score': 75,
            'overall_grade': 'B',
            'jd_role': 'SWE',
            'jd_company': 'TestCo',
            'jd_industry': 'Tech',
            'scores': {
                'generic_ats': 70,
                'workday_ats': 72,
                'greenhouse_ats': 74,
                'keyword_match_percent': 65,
            },
            'keyword_analysis': {
                'matched_keywords': ['python', 'django'],
                'missing_keywords': ['kubernetes', 'terraform', 'docker'],
            },
        }
        defaults.update(kwargs)
        return ResumeAnalysis.objects.create(**defaults)


# ── P0: first_name / last_name writable ─────────────────────────────────────

class FirstLastNameTests(TestMixin, TestCase):
    def test_update_first_last_name(self):
        resp = self.client.put('/api/v1/auth/me/', {
            'username': 'gaptest',
            'first_name': 'Jane',
            'last_name': 'Smith',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Jane')
        self.assertEqual(self.user.last_name, 'Smith')

    def test_first_last_name_in_response(self):
        resp = self.client.get('/api/v1/auth/me/')
        self.assertEqual(resp.data['first_name'], 'John')
        self.assertEqual(resp.data['last_name'], 'Doe')


# ── P0: Dashboard enhancements ─────────────────────────────────────────────

class DashboardEnhancementTests(TestMixin, TestCase):
    def test_keyword_match_in_score_trend(self):
        self._make_analysis()
        resp = self.client.get('/api/v1/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        trend = resp.data['score_trend']
        self.assertEqual(len(trend), 1)
        self.assertEqual(trend[0]['keyword_match_percent'], 65)

    def test_top_missing_keywords(self):
        for i in range(3):
            self._make_analysis(
                keyword_analysis={
                    'matched_keywords': ['python'],
                    'missing_keywords': ['kubernetes', 'terraform'],
                },
            )
        resp = self.client.get('/api/v1/dashboard/stats/')
        keywords = resp.data['top_missing_keywords']
        self.assertGreater(len(keywords), 0)
        kw_names = [k['keyword'] for k in keywords]
        self.assertIn('kubernetes', kw_names)
        self.assertIn('terraform', kw_names)

    def test_credit_usage_in_dashboard(self):
        wallet, _ = Wallet.objects.get_or_create(user=self.user)
        WalletTransaction.objects.create(
            wallet=wallet, amount=-1, balance_after=99,
            transaction_type='analysis_debit', description='Test',
        )
        resp = self.client.get('/api/v1/dashboard/stats/')
        self.assertIn('credit_usage', resp.data)

    def test_weekly_job_matches_in_dashboard(self):
        resp = self.client.get('/api/v1/dashboard/stats/')
        self.assertIn('weekly_job_matches', resp.data)
        self.assertEqual(resp.data['weekly_job_matches'], 0)


# ── P1: Search/filter on analyses ───────────────────────────────────────────

class AnalysisSearchFilterTests(TestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_analysis(jd_role='Backend Engineer', ats_score=85)
        self._make_analysis(jd_role='Frontend Developer', ats_score=60)
        self._make_analysis(jd_role='Backend Developer', ats_score=92)

    def test_search_by_role(self):
        resp = self.client.get('/api/v1/analyses/?search=Backend')
        self.assertEqual(resp.data['count'], 2)

    def test_filter_by_status(self):
        resp = self.client.get('/api/v1/analyses/?status=done')
        self.assertEqual(resp.data['count'], 3)

    def test_score_min_filter(self):
        resp = self.client.get('/api/v1/analyses/?score_min=80')
        self.assertEqual(resp.data['count'], 2)

    def test_score_max_filter(self):
        resp = self.client.get('/api/v1/analyses/?score_max=70')
        self.assertEqual(resp.data['count'], 1)

    def test_ordering_by_score_desc(self):
        resp = self.client.get('/api/v1/analyses/?ordering=-ats_score')
        results = resp.data['results']
        self.assertEqual(results[0]['ats_score'], 92)

    def test_combined_filters(self):
        resp = self.client.get('/api/v1/analyses/?search=Backend&score_min=90')
        self.assertEqual(resp.data['count'], 1)


# ── P1: Search/filter on resumes ────────────────────────────────────────────

class ResumeSearchFilterTests(TestMixin, TestCase):
    def setUp(self):
        super().setUp()
        Resume.objects.create(
            user=self.user, original_filename='resume_john.pdf',
            file_hash='aaa', file_size_bytes=1024,
        )
        Resume.objects.create(
            user=self.user, original_filename='cv_jane.pdf',
            file_hash='bbb', file_size_bytes=2048,
        )

    def test_search_by_filename(self):
        resp = self.client.get('/api/v1/resumes/?search=john')
        self.assertEqual(resp.data['count'], 1)

    def test_ordering_by_size(self):
        resp = self.client.get('/api/v1/resumes/?ordering=-file_size_bytes')
        results = resp.data['results']
        self.assertEqual(results[0]['original_filename'], 'cv_jane.pdf')


# ── P1: DELETE generated resume ─────────────────────────────────────────────

class GeneratedResumeDeleteTests(TestMixin, TestCase):
    def test_delete_generated_resume(self):
        analysis = self._make_analysis()
        gen = GeneratedResume.objects.create(
            user=self.user, analysis=analysis,
            template='ats_classic', format='pdf',
            status='done',
        )
        resp = self.client.delete(f'/api/v1/generated-resumes/{gen.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GeneratedResume.objects.filter(pk=gen.pk).exists())

    def test_delete_other_users_resume_fails(self):
        other = User.objects.create_user(username='other', password='Pass123!!')
        analysis = ResumeAnalysis.objects.create(
            user=other, status='done', ats_score=70,
        )
        gen = GeneratedResume.objects.create(
            user=other, analysis=analysis,
            template='ats_classic', format='pdf', status='done',
        )
        resp = self.client.delete(f'/api/v1/generated-resumes/{gen.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ── P1: Bulk delete resumes ─────────────────────────────────────────────────

class ResumeBulkDeleteTests(TestMixin, TestCase):
    def test_bulk_delete_resumes(self):
        r1 = Resume.objects.create(
            user=self.user, original_filename='a.pdf',
            file_hash='aaa', file_size_bytes=100,
        )
        r2 = Resume.objects.create(
            user=self.user, original_filename='b.pdf',
            file_hash='bbb', file_size_bytes=200,
        )
        resp = self.client.post('/api/v1/resumes/bulk-delete/', {
            'ids': [str(r1.pk), str(r2.pk)],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['deleted'], 2)

    def test_bulk_delete_skips_with_active_analyses(self):
        resume = Resume.objects.create(
            user=self.user, original_filename='c.pdf',
            file_hash='ccc', file_size_bytes=300,
        )
        ResumeAnalysis.objects.create(
            user=self.user, resume=resume, status='done', ats_score=70,
        )
        resp = self.client.post('/api/v1/resumes/bulk-delete/', {
            'ids': [str(resume.pk)],
        }, format='json')
        self.assertEqual(resp.data['deleted'], 0)
        self.assertEqual(len(resp.data['skipped']), 1)

    def test_bulk_delete_empty_list_rejected(self):
        resp = self.client.post('/api/v1/resumes/bulk-delete/', {'ids': []}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── P1: Job alert total_matches ─────────────────────────────────────────────

class JobAlertTotalMatchesTests(TestMixin, TestCase):
    def test_total_matches_in_response(self):
        resume = Resume.objects.create(
            user=self.user, original_filename='test.pdf',
            file_hash='abc', file_size_bytes=100,
        )
        alert = JobAlert.objects.create(
            user=self.user, resume=resume, is_active=True,
        )
        # Create some matches
        for i in range(3):
            job = DiscoveredJob.objects.create(
                title=f'Job {i}', source='test', external_id=f'ext_{i}',
            )
            JobMatch.objects.create(
                job_alert=alert, discovered_job=job,
                relevance_score=80,
            )

        resp = self.client.get('/api/v1/job-alerts/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['total_matches'], 3)


# ── P2: Social links CRUD ──────────────────────────────────────────────────

class SocialLinksTests(TestMixin, TestCase):
    def test_update_social_links(self):
        resp = self.client.put('/api/v1/auth/me/', {
            'username': 'gaptest',
            'website_url': 'https://mysite.com',
            'github_url': 'https://github.com/user',
            'linkedin_url': 'https://linkedin.com/in/user',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_social_links_in_response(self):
        profile = self.user.profile
        profile.website_url = 'https://example.com'
        profile.save(update_fields=['website_url'])

        resp = self.client.get('/api/v1/auth/me/')
        self.assertEqual(resp.data['website_url'], 'https://example.com')

    def test_clear_social_links(self):
        profile = self.user.profile
        profile.github_url = 'https://github.com/user'
        profile.save(update_fields=['github_url'])

        resp = self.client.put('/api/v1/auth/me/', {
            'username': 'gaptest',
            'github_url': '',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        profile.refresh_from_db()
        self.assertEqual(profile.github_url, '')


# ── P2: Resume staleness ───────────────────────────────────────────────────

class ResumeStalenessTests(TestMixin, TestCase):
    def test_days_since_upload_in_response(self):
        resume = Resume.objects.create(
            user=self.user, original_filename='old.pdf',
            file_hash='old', file_size_bytes=100,
        )
        # Backdate the upload
        Resume.objects.filter(pk=resume.pk).update(
            uploaded_at=timezone.now() - timedelta(days=45),
        )
        resp = self.client.get('/api/v1/resumes/')
        r = resp.data['results'][0]
        self.assertIn('days_since_upload', r)
        self.assertGreaterEqual(r['days_since_upload'], 44)

    def test_last_analyzed_at_in_response(self):
        resume = Resume.objects.create(
            user=self.user, original_filename='r.pdf',
            file_hash='rrr', file_size_bytes=100,
        )
        self._make_analysis(resume=resume)
        resp = self.client.get('/api/v1/resumes/')
        r = resp.data['results'][0]
        self.assertIn('last_analyzed_at', r)
        self.assertIsNotNone(r['last_analyzed_at'])


# ── P2: Wallet CSV export ──────────────────────────────────────────────────

class WalletExportTests(TestMixin, TestCase):
    def test_csv_export(self):
        wallet, _ = Wallet.objects.get_or_create(user=self.user)
        WalletTransaction.objects.create(
            wallet=wallet, amount=-1, balance_after=99,
            transaction_type='analysis_debit', description='Analysis',
        )
        resp = self.client.get('/api/v1/auth/wallet/transactions/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('attachment', resp['Content-Disposition'])
        content = resp.content.decode()
        self.assertIn('Date', content)
        self.assertIn('analysis_debit', content)

    def test_csv_export_empty(self):
        resp = self.client.get('/api/v1/auth/wallet/transactions/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        content = resp.content.decode()
        # Header row is always present
        self.assertIn('Date,Type,Amount', content)


# ── P2: Shared analysis summary ───────────────────────────────────────────

class SharedAnalysisSummaryTests(TestMixin, TestCase):
    def test_summary_endpoint(self):
        analysis = self._make_analysis()
        analysis.share_token = uuid.uuid4()
        analysis.save(update_fields=['share_token'])

        # No auth needed for public endpoint
        self.client.credentials()
        resp = self.client.get(f'/api/v1/shared/{analysis.share_token}/summary/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['ats_score'], 75)
        self.assertEqual(resp.data['overall_grade'], 'B')
        self.assertIn('scores', resp.data)

    def test_summary_invalid_token(self):
        self.client.credentials()
        resp = self.client.get(f'/api/v1/shared/{uuid.uuid4()}/summary/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ── P2: Analysis comparison ────────────────────────────────────────────────

class AnalysisCompareTests(TestMixin, TestCase):
    def test_compare_two_analyses(self):
        a1 = self._make_analysis(jd_role='SWE', ats_score=80)
        a2 = self._make_analysis(jd_role='DevOps', ats_score=90)

        resp = self.client.get(f'/api/v1/analyses/compare/?ids={a1.pk},{a2.pk}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 2)
        self.assertEqual(len(resp.data['analyses']), 2)

    def test_compare_requires_at_least_two(self):
        a1 = self._make_analysis()
        resp = self.client.get(f'/api/v1/analyses/compare/?ids={a1.pk}')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_compare_max_five(self):
        ids = []
        for i in range(6):
            a = self._make_analysis()
            ids.append(str(a.pk))
        resp = self.client.get(f'/api/v1/analyses/compare/?ids={",".join(ids)}')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_compare_other_users_analysis_not_found(self):
        other = User.objects.create_user(username='other2', password='Pass123!!')
        a1 = self._make_analysis()
        a2 = ResumeAnalysis.objects.create(user=other, status='done', ats_score=70)
        resp = self.client.get(f'/api/v1/analyses/compare/?ids={a1.pk},{a2.pk}')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ── P2: Avatar upload ──────────────────────────────────────────────────────

class AvatarUploadTests(TestMixin, TestCase):
    def _make_image(self, name='avatar.png', content_type='image/png'):
        from PIL import Image
        import io
        img = Image.new('RGB', (100, 100), color='red')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type=content_type)

    def test_upload_avatar(self):
        avatar = self._make_image()
        resp = self.client.post('/api/v1/auth/avatar/', {'avatar': avatar}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('avatar_url', resp.data)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.avatar_url)

    def test_upload_no_file(self):
        resp = self.client.post('/api/v1/auth/avatar/', {}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_invalid_type(self):
        f = SimpleUploadedFile('doc.pdf', b'%PDF-1.4 content', content_type='application/pdf')
        resp = self.client.post('/api/v1/auth/avatar/', {'avatar': f}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid file type', resp.data['detail'])

    def test_upload_too_large(self):
        # 3 MB file
        f = SimpleUploadedFile('big.png', b'x' * (3 * 1024 * 1024), content_type='image/png')
        resp = self.client.post('/api/v1/auth/avatar/', {'avatar': f}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('too large', resp.data['detail'])

    def test_delete_avatar(self):
        self.user.profile.avatar_url = 'https://example.com/pic.jpg'
        self.user.profile.save(update_fields=['avatar_url'])

        resp = self.client.delete('/api/v1/auth/avatar/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.avatar_url, '')

    def test_delete_no_avatar(self):
        resp = self.client.delete('/api/v1/auth/avatar/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ── P2: Industry benchmark ─────────────────────────────────────────────────

class IndustryBenchmarkTests(TestMixin, TestCase):
    def test_benchmark_in_dashboard(self):
        self._make_analysis(ats_score=80)
        resp = self.client.get('/api/v1/dashboard/stats/')
        self.assertIn('industry_benchmark_percentile', resp.data)

    def test_benchmark_with_multiple_users(self):
        # Current user has high score
        self._make_analysis(ats_score=90)

        # Create another user with a lower score
        other = User.objects.create_user(username='low', password='Pass123!!')
        ResumeAnalysis.objects.create(user=other, status='done', ats_score=50)

        resp = self.client.get('/api/v1/dashboard/stats/')
        # Our user should be above the other user
        self.assertGreaterEqual(resp.data['industry_benchmark_percentile'], 50)

    def test_benchmark_none_without_analyses(self):
        resp = self.client.get('/api/v1/dashboard/stats/')
        self.assertIsNone(resp.data['industry_benchmark_percentile'])
