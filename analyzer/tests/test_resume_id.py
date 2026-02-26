"""
Tests for the resume_id feature: reuse an existing Resume for a new analysis
instead of re-uploading the PDF file.
"""
import uuid
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from analyzer.models import Resume, ResumeAnalysis


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


class ResumeIdAnalyzeTests(TestCase):
    """POST /api/analyze/ with resume_id instead of resume_file."""

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.user = User.objects.create_user(username='riduser', password='StrongPass123!')
        _give_credits(self.user)
        token_resp = self.client.post(
            '/api/auth/login/',
            {'username': 'riduser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.token = token_resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

        # Create a Resume object that we can reference by ID
        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())

    def tearDown(self):
        cache.clear()

    # ── Success cases ──────────────────────────────────────────────────

    @patch('analyzer.views.run_analysis_task')
    def test_analyze_with_resume_id_success(self, mock_task):
        """Sending resume_id (JSON) should create an analysis linked to the Resume."""
        mock_task.delay.return_value = MagicMock(id='fake-task-id')

        resp = self.client.post(
            '/api/analyze/',
            {
                'resume_id': str(self.resume.id),
                'jd_input_type': 'text',
                'jd_text': 'We need a Python developer.',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn('id', resp.data)
        self.assertEqual(resp.data['status'], 'processing')

        # Verify the analysis is linked to the Resume and has its file
        analysis = ResumeAnalysis.objects.get(id=resp.data['id'])
        self.assertEqual(analysis.resume, self.resume)
        self.assertEqual(analysis.resume_file.name, self.resume.file.name)
        mock_task.delay.assert_called_once()

    @patch('analyzer.views.run_analysis_task')
    def test_analyze_with_resume_id_form_jd(self, mock_task):
        """resume_id works with form JD type as well."""
        mock_task.delay.return_value = MagicMock(id='fake-task-id')

        resp = self.client.post(
            '/api/analyze/',
            {
                'resume_id': str(self.resume.id),
                'jd_input_type': 'form',
                'jd_role': 'Data Scientist',
                'jd_skills': 'Python, ML',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

    @patch('analyzer.views.run_analysis_task')
    def test_analyze_with_resume_id_as_form_field(self, mock_task):
        """resume_id can also be sent via multipart/form-data."""
        mock_task.delay.return_value = MagicMock(id='fake-task-id')

        resp = self.client.post(
            '/api/analyze/',
            {
                'resume_id': str(self.resume.id),
                'jd_input_type': 'text',
                'jd_text': 'Python developer needed.',
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

    # ── Validation / error cases ───────────────────────────────────────

    def test_neither_file_nor_id_returns_400(self):
        """Sending neither resume_file nor resume_id should fail."""
        resp = self.client.post(
            '/api/analyze/',
            {
                'jd_input_type': 'text',
                'jd_text': 'Developer role',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_both_file_and_id_returns_400(self):
        """Sending both resume_file and resume_id should fail."""
        resp = self.client.post(
            '/api/analyze/',
            {
                'resume_file': _make_pdf(),
                'resume_id': str(self.resume.id),
                'jd_input_type': 'text',
                'jd_text': 'Dev role',
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_resume_id_returns_400(self):
        """A malformed UUID should fail validation."""
        resp = self.client.post(
            '/api/analyze/',
            {
                'resume_id': 'not-a-uuid',
                'jd_input_type': 'text',
                'jd_text': 'Developer role',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nonexistent_resume_id_returns_400(self):
        """A valid UUID that doesn't match any Resume should fail."""
        fake_id = str(uuid.uuid4())
        resp = self.client.post(
            '/api/analyze/',
            {
                'resume_id': fake_id,
                'jd_input_type': 'text',
                'jd_text': 'Developer role',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_other_users_resume_id_returns_400(self):
        """Users cannot reference another user's Resume."""
        other_user = User.objects.create_user(username='otheruser', password='StrongPass123!')
        other_resume, _ = Resume.get_or_create_from_upload(
            other_user,
            _make_pdf(b'%PDF-1.4 other user content'),
        )

        resp = self.client.post(
            '/api/analyze/',
            {
                'resume_id': str(other_resume.id),
                'jd_input_type': 'text',
                'jd_text': 'Developer role',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Multiple analyses from same Resume ─────────────────────────────

    @patch('analyzer.views.run_analysis_task')
    def test_multiple_analyses_same_resume(self, mock_task):
        """Multiple analyses can reference the same Resume."""
        mock_task.delay.return_value = MagicMock(id='fake-task-id')

        ids = []
        for jd in ['Python role', 'Java role', 'Go role']:
            cache.clear()  # reset idempotency lock
            resp = self.client.post(
                '/api/analyze/',
                {
                    'resume_id': str(self.resume.id),
                    'jd_input_type': 'text',
                    'jd_text': jd,
                },
                format='json',
            )
            self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
            ids.append(resp.data['id'])

        # Three unique analyses, all linked to the same Resume
        self.assertEqual(len(set(ids)), 3)
        for analysis_id in ids:
            analysis = ResumeAnalysis.objects.get(id=analysis_id)
            self.assertEqual(analysis.resume_id, self.resume.id)

    # ── File upload still works ────────────────────────────────────────

    @patch('analyzer.views.run_analysis_task')
    def test_file_upload_still_works(self, mock_task):
        """Original file upload path should continue to work as before."""
        mock_task.delay.return_value = MagicMock(id='fake-task-id')

        resp = self.client.post(
            '/api/analyze/',
            {
                'resume_file': _make_pdf(),
                'jd_input_type': 'text',
                'jd_text': 'Python developer needed.',
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn('id', resp.data)

        analysis = ResumeAnalysis.objects.get(id=resp.data['id'])
        self.assertIsNotNone(analysis.resume)
        self.assertTrue(analysis.resume_file.name.startswith('resumes/'))
