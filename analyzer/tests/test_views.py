from unittest.mock import patch, MagicMock, PropertyMock
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from analyzer.models import ResumeAnalysis


def _make_pdf():
    return SimpleUploadedFile('resume.pdf', b'%PDF-1.4 fake content', content_type='application/pdf')


class AnalyzeResumeViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='apiuser', password='StrongPass123!')
        token_resp = self.client.post(
            '/api/auth/login/',
            {'username': 'apiuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_resp.data["access"]}')

    def test_analyze_requires_auth(self):
        unauthed = APIClient()
        resp = unauthed.post(
            '/api/analyze/',
            {'resume_file': _make_pdf(), 'jd_input_type': 'text', 'jd_text': 'Dev role'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('analyzer.views.run_analysis_task')
    def test_analyze_success(self, mock_task):
        mock_task.delay.return_value = MagicMock(id='fake-task-id')

        resp = self.client.post(
            '/api/analyze/',
            {'resume_file': _make_pdf(), 'jd_input_type': 'text', 'jd_text': 'We need a Python developer.'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn('id', resp.data)
        self.assertEqual(resp.data['status'], 'processing')
        mock_task.delay.assert_called_once()

    def test_analyze_missing_resume(self):
        resp = self.client.post(
            '/api/analyze/',
            {'jd_input_type': 'text', 'jd_text': 'We need a Python developer.'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_analyze_bad_pdf_magic_bytes(self):
        bad_file = SimpleUploadedFile('resume.pdf', b'PK\x03\x04zip content', content_type='application/pdf')
        resp = self.client.post(
            '/api/analyze/',
            {'resume_file': bad_file, 'jd_input_type': 'text', 'jd_text': 'Dev role'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('analyzer.views.run_analysis_task')
    def test_analyze_double_submit_blocked(self, mock_task):
        """Second submit within lock TTL should return 409 Conflict."""
        mock_task.delay.return_value = MagicMock(id='fake-task-id')

        resp1 = self.client.post(
            '/api/analyze/',
            {'resume_file': _make_pdf(), 'jd_input_type': 'text', 'jd_text': 'Python developer'},
            format='multipart',
        )
        self.assertEqual(resp1.status_code, status.HTTP_202_ACCEPTED)

        resp2 = self.client.post(
            '/api/analyze/',
            {'resume_file': _make_pdf(), 'jd_input_type': 'text', 'jd_text': 'Python developer'},
            format='multipart',
        )
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('already being submitted', resp2.data['detail'])

        # Only one task dispatched
        self.assertEqual(mock_task.delay.call_count, 1)

        # Clean up lock for other tests
        cache.delete(f'analyze_lock:{self.user.id}')


class AnalysisListViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='listuser', password='StrongPass123!')
        token_resp = self.client.post(
            '/api/auth/login/',
            {'username': 'listuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_resp.data["access"]}')

    def test_list_empty(self):
        resp = self.client.get('/api/analyses/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['results'], [])

    def test_list_requires_auth(self):
        unauthed = APIClient()
        resp = unauthed.get('/api/analyses/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_only_own_analyses(self):
        other_user = User.objects.create_user(username='other', password='StrongPass123!')
        ResumeAnalysis.objects.create(user=other_user, jd_input_type='text', jd_text='test')
        ResumeAnalysis.objects.create(user=self.user, jd_input_type='text', jd_text='mine')

        resp = self.client.get('/api/analyses/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 1)
