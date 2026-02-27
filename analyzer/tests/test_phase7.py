"""
Tests for Phase 7: Resume model, soft-delete, and dashboard analytics.
"""
from unittest.mock import patch, MagicMock
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from analyzer.models import ResumeAnalysis, Resume, ScrapeResult, LLMResponse


def _ensure_free_plan():
    from accounts.models import Plan
    Plan.objects.get_or_create(
        slug='free',
        defaults={'name': 'Free', 'billing_cycle': 'free', 'price': 0, 'credits_per_month': 2},
    )


def _give_credits(user, amount=100):
    from accounts.models import Wallet
    wallet, _ = Wallet.objects.get_or_create(user=user)
    wallet.balance = amount
    wallet.save(update_fields=['balance'])


def _make_pdf(content=b'%PDF-1.4 fake content'):
    return SimpleUploadedFile('resume.pdf', content, content_type='application/pdf')


class ResumeModelTests(TestCase):
    """Tests for the Resume model and deduplication logic."""

    def setUp(self):
        self.user = User.objects.create_user(username='resumeuser', password='StrongPass123!')

    def test_compute_hash_deterministic(self):
        f1 = _make_pdf(b'%PDF-1.4 test content')
        f2 = _make_pdf(b'%PDF-1.4 test content')
        h1 = Resume.compute_hash(f1)
        h2 = Resume.compute_hash(f2)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # SHA-256 hex digest

    def test_compute_hash_different_files(self):
        f1 = _make_pdf(b'%PDF-1.4 file A')
        f2 = _make_pdf(b'%PDF-1.4 file B')
        self.assertNotEqual(Resume.compute_hash(f1), Resume.compute_hash(f2))

    def test_get_or_create_new(self):
        f = _make_pdf()
        resume, created = Resume.get_or_create_from_upload(self.user, f)
        self.assertTrue(created)
        self.assertEqual(resume.user, self.user)
        self.assertEqual(resume.original_filename, 'resume.pdf')
        self.assertGreater(resume.file_size_bytes, 0)

    def test_get_or_create_dedup_same_user(self):
        """Same file uploaded twice by same user → reuse existing Resume."""
        f1 = _make_pdf(b'%PDF-1.4 identical content')
        f2 = _make_pdf(b'%PDF-1.4 identical content')

        r1, created1 = Resume.get_or_create_from_upload(self.user, f1)
        r2, created2 = Resume.get_or_create_from_upload(self.user, f2)

        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(Resume.objects.filter(user=self.user).count(), 1)

    def test_get_or_create_different_users_no_dedup(self):
        """Same file uploaded by different users → separate Resume rows."""
        other = User.objects.create_user(username='other', password='StrongPass123!')
        content = b'%PDF-1.4 shared content'

        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(content))
        r2, _ = Resume.get_or_create_from_upload(other, _make_pdf(content))

        self.assertNotEqual(r1.pk, r2.pk)


class SoftDeleteTests(TestCase):
    """Tests for analysis soft-delete behavior."""

    def setUp(self):
        self.user = User.objects.create_user(username='softuser', password='StrongPass123!')

    def test_soft_delete_sets_deleted_at(self):
        analysis = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', jd_text='test',
            resume_text='long resume text here',
            resolved_jd='long jd text here',
        )
        analysis.soft_delete()
        analysis.refresh_from_db()

        self.assertIsNotNone(analysis.deleted_at)
        self.assertEqual(analysis.resume_text, '')
        self.assertEqual(analysis.resolved_jd, '')
        self.assertEqual(analysis.jd_text, '')

    def test_soft_deleted_hidden_from_default_manager(self):
        analysis = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', jd_text='test',
        )
        analysis.soft_delete()

        self.assertEqual(ResumeAnalysis.objects.filter(user=self.user).count(), 0)
        self.assertEqual(ResumeAnalysis.all_objects.filter(user=self.user).count(), 1)

    def test_soft_delete_keeps_lightweight_metadata(self):
        analysis = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', jd_text='test',
            ats_score=85, jd_role='Developer', jd_company='Acme',
            status='done',
        )
        analysis.soft_delete()
        analysis.refresh_from_db()

        self.assertEqual(analysis.ats_score, 85)
        self.assertEqual(analysis.jd_role, 'Developer')
        self.assertEqual(analysis.jd_company, 'Acme')
        self.assertEqual(analysis.status, 'done')

    def test_soft_delete_cleans_orphan_scrape_result(self):
        scrape = ScrapeResult.objects.create(
            user=self.user, source_url='https://example.com',
            status='done',
        )
        analysis = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='url',
            scrape_result=scrape,
        )
        scrape_id = scrape.pk

        analysis.soft_delete()

        self.assertFalse(ScrapeResult.objects.filter(pk=scrape_id).exists())

    def test_soft_delete_cleans_orphan_llm_response(self):
        llm = LLMResponse.objects.create(
            user=self.user, model_used='test', status='done',
        )
        analysis = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text',
            llm_response=llm,
        )
        llm_id = llm.pk

        analysis.soft_delete()

        self.assertFalse(LLMResponse.objects.filter(pk=llm_id).exists())

    def test_soft_delete_preserves_shared_scrape_result(self):
        """Scrape result used by another analysis should NOT be deleted."""
        scrape = ScrapeResult.objects.create(
            user=self.user, source_url='https://example.com', status='done',
        )
        analysis1 = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='url', scrape_result=scrape,
        )
        analysis2 = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='url', scrape_result=scrape,
        )

        analysis1.soft_delete()

        self.assertTrue(ScrapeResult.objects.filter(pk=scrape.pk).exists())


class AnalysisDeleteViewTests(TestCase):
    """Tests for the soft-delete API endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='deluser', password='StrongPass123!')
        token_resp = self.client.post(
            '/api/auth/login/',
            {'username': 'deluser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_resp.data["access"]}')

    def test_delete_returns_204(self):
        analysis = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', jd_text='test',
        )
        resp = self.client.delete(f'/api/analyses/{analysis.id}/delete/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_soft_deletes(self):
        analysis = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', jd_text='test',
        )
        self.client.delete(f'/api/analyses/{analysis.id}/delete/')

        # Not visible via default manager
        self.assertFalse(ResumeAnalysis.objects.filter(pk=analysis.pk).exists())
        # Still visible via all_objects
        self.assertTrue(ResumeAnalysis.all_objects.filter(pk=analysis.pk).exists())

    def test_delete_other_user_404(self):
        other = User.objects.create_user(username='other2', password='StrongPass123!')
        analysis = ResumeAnalysis.all_objects.create(
            user=other, jd_input_type='text',
        )
        resp = self.client.delete(f'/api/analyses/{analysis.id}/delete/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_deleted_analysis_excluded_from_list(self):
        """Soft-deleted analyses should not appear in the list endpoint."""
        a1 = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', jd_text='active',
        )
        a2 = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', jd_text='to_delete',
        )
        self.client.delete(f'/api/analyses/{a2.id}/delete/')

        resp = self.client.get('/api/analyses/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [r['id'] for r in resp.data['results']]
        self.assertIn(a1.id, ids)
        self.assertNotIn(a2.id, ids)


class ResumeAPITests(TestCase):
    """Tests for the resume list and delete endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='resapiuser', password='StrongPass123!')
        token_resp = self.client.post(
            '/api/auth/login/',
            {'username': 'resapiuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_resp.data["access"]}')

    def test_list_resumes_empty(self):
        resp = self.client.get('/api/resumes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['results'], [])

    def test_list_resumes_with_data(self):
        resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())
        resp = self.client.get('/api/resumes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['results'][0]['original_filename'], 'resume.pdf')

    def test_delete_resume_no_active_analyses(self):
        resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())
        resp = self.client.delete(f'/api/resumes/{resume.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Resume.objects.filter(pk=resume.pk).exists())

    def test_delete_resume_blocked_by_active_analysis(self):
        resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())
        ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', resume=resume,
        )
        resp = self.client.delete(f'/api/resumes/{resume.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Resume.objects.filter(pk=resume.pk).exists())

    def test_delete_resume_allowed_if_only_soft_deleted_analyses(self):
        """Resume can be deleted if all referencing analyses are soft-deleted."""
        resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())
        analysis = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', resume=resume,
        )
        analysis.soft_delete()

        resp = self.client.delete(f'/api/resumes/{resume.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_resume_other_user_404(self):
        other = User.objects.create_user(username='other3', password='StrongPass123!')
        resume, _ = Resume.get_or_create_from_upload(other, _make_pdf())
        resp = self.client.delete(f'/api/resumes/{resume.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class DashboardStatsTests(TestCase):
    """Tests for the dashboard analytics endpoint."""

    def setUp(self):
        from django.core.cache import cache
        self.client = APIClient()
        self.user = User.objects.create_user(username='dashuser', password='StrongPass123!')
        token_resp = self.client.post(
            '/api/auth/login/',
            {'username': 'dashuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_resp.data["access"]}')
        # Clear dashboard cache to avoid stale data between tests
        cache.delete(f'dashboard_stats:{self.user.id}')
    def test_stats_empty(self):
        resp = self.client.get('/api/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_analyses'], 0)
        self.assertEqual(resp.data['active_analyses'], 0)
        self.assertEqual(resp.data['deleted_analyses'], 0)
        self.assertIsNone(resp.data['average_ats_score'])

    def test_stats_with_data(self):
        # Create 3 analyses, soft-delete 1
        a1 = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', status='done',
            ats_score=80, jd_role='Developer',
        )
        a2 = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', status='done',
            ats_score=90, jd_role='Developer',
        )
        a3 = ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', status='done',
            ats_score=70, jd_role='Designer',
        )
        a3.soft_delete()

        resp = self.client.get('/api/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_analyses'], 3)
        self.assertEqual(resp.data['active_analyses'], 2)
        self.assertEqual(resp.data['deleted_analyses'], 1)
        self.assertEqual(resp.data['average_ats_score'], 80.0)  # (80+90+70)/3
        self.assertEqual(len(resp.data['score_trend']), 3)
        self.assertGreater(len(resp.data['top_roles']), 0)

    def test_stats_requires_auth(self):
        unauthed = APIClient()
        resp = unauthed.get('/api/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_stats_user_isolation(self):
        """One user's stats should not include another user's analyses."""
        other = User.objects.create_user(username='other4', password='StrongPass123!')
        ResumeAnalysis.all_objects.create(
            user=other, jd_input_type='text', status='done', ats_score=90,
        )
        ResumeAnalysis.all_objects.create(
            user=self.user, jd_input_type='text', status='done', ats_score=75,
        )

        resp = self.client.get('/api/dashboard/stats/')
        self.assertEqual(resp.data['total_analyses'], 1)
        self.assertEqual(resp.data['average_ats_score'], 75.0)


class AnalyzeResumeDeduplicationTests(TestCase):
    """Test that submitting an analysis creates a deduplicated Resume."""

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.user = User.objects.create_user(username='dedupuser', password='StrongPass123!')
        _give_credits(self.user)
        token_resp = self.client.post(
            '/api/auth/login/',
            {'username': 'dedupuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_resp.data["access"]}')

    @patch('analyzer.views.run_analysis_task')
    def test_analyze_creates_resume_row(self, mock_task):
        mock_task.delay.return_value = MagicMock(id='fake-task-id')

        resp = self.client.post(
            '/api/analyze/',
            {'resume_file': _make_pdf(), 'jd_input_type': 'text', 'jd_text': 'Python dev'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

        analysis = ResumeAnalysis.objects.get(id=resp.data['id'])
        self.assertIsNotNone(analysis.resume)
        self.assertEqual(analysis.resume.user, self.user)

        # Clean up idempotency lock
        cache.delete(f'analyze_lock:{self.user.id}')

    @patch('analyzer.views.run_analysis_task')
    def test_analyze_dedup_same_file(self, mock_task):
        """Two analyses with same resume file → same Resume row."""
        mock_task.delay.return_value = MagicMock(id='fake-task-id')
        content = b'%PDF-1.4 identical pdf bytes'

        resp1 = self.client.post(
            '/api/analyze/',
            {'resume_file': _make_pdf(content), 'jd_input_type': 'text', 'jd_text': 'Role A'},
            format='multipart',
        )
        cache.delete(f'analyze_lock:{self.user.id}')

        resp2 = self.client.post(
            '/api/analyze/',
            {'resume_file': _make_pdf(content), 'jd_input_type': 'text', 'jd_text': 'Role B'},
            format='multipart',
        )
        cache.delete(f'analyze_lock:{self.user.id}')

        a1 = ResumeAnalysis.objects.get(id=resp1.data['id'])
        a2 = ResumeAnalysis.objects.get(id=resp2.data['id'])

        self.assertEqual(a1.resume.pk, a2.resume.pk)
        self.assertEqual(Resume.objects.filter(user=self.user).count(), 1)
