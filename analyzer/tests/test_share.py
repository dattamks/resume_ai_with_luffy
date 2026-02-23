"""
Tests for the shareable results link feature.

Covers:
- POST /api/analyses/<id>/share/ — generate share token
- DELETE /api/analyses/<id>/share/ — revoke share token
- GET /api/shared/<token>/ — public read-only view
- Serializer field exposure (share_token, share_url)
- Edge cases: soft-deleted, incomplete, wrong user, revoked
"""
import uuid

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from analyzer.models import ResumeAnalysis


@override_settings(
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    MEDIA_ROOT='/tmp/test_media_share',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ShareTokenTests(TestCase):
    """Tests for generating and revoking share tokens."""

    def setUp(self):
        self.user = User.objects.create_user('alice', 'alice@test.com', 'pass1234')
        self.other_user = User.objects.create_user('bob', 'bob@test.com', 'pass1234')

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create a completed analysis
        self.analysis = ResumeAnalysis.all_objects.create(
            user=self.user,
            jd_input_type='text',
            jd_text='Test JD',
            jd_role='Backend Engineer',
            jd_company='Acme Corp',
            status=ResumeAnalysis.STATUS_DONE,
            pipeline_step=ResumeAnalysis.STEP_DONE,
            overall_grade='B',
            ats_score=82,
            scores={'generic_ats': 82, 'workday_ats': 70, 'greenhouse_ats': 75, 'keyword_match_percent': 60},
            ats_disclaimers={'workday': 'Simulated.', 'greenhouse': 'Simulated.'},
            keyword_analysis={
                'matched_keywords': ['Python'],
                'missing_keywords': ['Kubernetes', 'Docker'],
                'recommended_to_add': ['Add Docker to skills'],
            },
            section_feedback=[{
                'section_name': 'Work Experience',
                'score': 65,
                'feedback': ['Add metrics'],
                'ats_flags': [],
            }],
            sentence_suggestions=[{
                'original': 'Worked on backend',
                'suggested': 'Built 5 microservices',
                'reason': 'Added specifics',
            }],
            formatting_flags=[],
            quick_wins=[
                {'priority': 1, 'action': 'Add Docker'},
                {'priority': 2, 'action': 'Quantify bullets'},
                {'priority': 3, 'action': 'Fix formatting'},
            ],
            summary='Strong backend profile.',
            ai_provider_used='OpenRouterProvider',
        )

    # ── POST /api/analyses/<id>/share/ ────────────────────────────────────

    def test_create_share_token(self):
        resp = self.client.post(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp.status_code, 201)
        self.assertIn('share_token', resp.data)
        self.assertIn('share_url', resp.data)

        # Token is a valid UUID
        token = resp.data['share_token']
        uuid.UUID(token)

        # Verify persisted
        self.analysis.refresh_from_db()
        self.assertEqual(str(self.analysis.share_token), token)

    def test_create_share_token_idempotent(self):
        """Calling POST share twice returns the same token (200, not 201)."""
        resp1 = self.client.post(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp1.status_code, 201)

        resp2 = self.client.post(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.data['share_token'], resp2.data['share_token'])

    def test_create_share_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp.status_code, 401)

    def test_create_share_wrong_user(self):
        self.client.force_authenticate(user=self.other_user)
        resp = self.client.post(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp.status_code, 404)

    def test_create_share_incomplete_analysis(self):
        """Cannot share an analysis that hasn't completed yet."""
        pending = ResumeAnalysis.all_objects.create(
            user=self.user,
            jd_input_type='text',
            jd_text='Test',
            status=ResumeAnalysis.STATUS_PROCESSING,
            pipeline_step=ResumeAnalysis.STEP_LLM_CALL,
        )
        resp = self.client.post(f'/api/analyses/{pending.id}/share/')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('completed', resp.data['detail'])

    def test_create_share_soft_deleted_analysis(self):
        """Cannot share a soft-deleted analysis (404 from ActiveAnalysisManager)."""
        self.analysis.soft_delete()
        resp = self.client.post(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp.status_code, 404)

    # ── DELETE /api/analyses/<id>/share/ ──────────────────────────────────

    def test_revoke_share_token(self):
        self.analysis.share_token = uuid.uuid4()
        self.analysis.save(update_fields=['share_token'])

        resp = self.client.delete(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp.status_code, 204)

        self.analysis.refresh_from_db()
        self.assertIsNone(self.analysis.share_token)

    def test_revoke_share_not_shared(self):
        """Revoking when not shared returns 400."""
        resp = self.client.delete(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not currently shared', resp.data['detail'])

    def test_revoke_share_wrong_user(self):
        self.analysis.share_token = uuid.uuid4()
        self.analysis.save(update_fields=['share_token'])

        self.client.force_authenticate(user=self.other_user)
        resp = self.client.delete(f'/api/analyses/{self.analysis.id}/share/')
        self.assertEqual(resp.status_code, 404)


@override_settings(
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    MEDIA_ROOT='/tmp/test_media_share',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class SharedAnalysisViewTests(TestCase):
    """Tests for GET /api/shared/<token>/ — public read-only endpoint."""

    def setUp(self):
        self.user = User.objects.create_user('alice', 'alice@test.com', 'pass1234')
        self.client = APIClient()  # No auth

        self.analysis = ResumeAnalysis.all_objects.create(
            user=self.user,
            jd_input_type='text',
            jd_text='Test JD',
            jd_role='Backend Engineer',
            jd_company='Acme Corp',
            status=ResumeAnalysis.STATUS_DONE,
            pipeline_step=ResumeAnalysis.STEP_DONE,
            overall_grade='B',
            ats_score=82,
            scores={'generic_ats': 82, 'workday_ats': 70, 'greenhouse_ats': 75, 'keyword_match_percent': 60},
            ats_disclaimers={'workday': 'Simulated.', 'greenhouse': 'Simulated.'},
            keyword_analysis={
                'matched_keywords': ['Python'],
                'missing_keywords': ['Kubernetes'],
                'recommended_to_add': [],
            },
            section_feedback=[],
            sentence_suggestions=[],
            formatting_flags=[],
            quick_wins=[],
            summary='Strong.',
            ai_provider_used='OpenRouterProvider',
            share_token=uuid.uuid4(),
        )

    def test_public_access_no_auth(self):
        """Shared link works without authentication."""
        resp = self.client.get(f'/api/shared/{self.analysis.share_token}/')
        self.assertEqual(resp.status_code, 200)

    def test_shared_response_fields(self):
        resp = self.client.get(f'/api/shared/{self.analysis.share_token}/')
        self.assertEqual(resp.status_code, 200)

        data = resp.data
        self.assertEqual(data['jd_role'], 'Backend Engineer')
        self.assertEqual(data['jd_company'], 'Acme Corp')
        self.assertEqual(data['ats_score'], 82)
        self.assertIn('keyword_analysis', data)
        self.assertIn('section_feedback', data)
        self.assertIn('sentence_suggestions', data)
        self.assertIn('summary', data)

    def test_shared_excludes_sensitive_fields(self):
        """Shared view must NOT expose resume file, user data, or celery IDs."""
        resp = self.client.get(f'/api/shared/{self.analysis.share_token}/')
        data = resp.data

        sensitive = ['id', 'resume_file', 'resume_file_url', 'resume_text',
                     'resolved_jd', 'celery_task_id', 'jd_text', 'jd_url',
                     'user', 'share_token']
        for field in sensitive:
            self.assertNotIn(field, data, f'Sensitive field "{field}" should not be in shared view')

    def test_invalid_token_404(self):
        fake_token = uuid.uuid4()
        resp = self.client.get(f'/api/shared/{fake_token}/')
        self.assertEqual(resp.status_code, 404)

    def test_revoked_token_404(self):
        """After revoking, the shared link should return 404."""
        token = self.analysis.share_token
        self.analysis.share_token = None
        self.analysis.save(update_fields=['share_token'])

        resp = self.client.get(f'/api/shared/{token}/')
        self.assertEqual(resp.status_code, 404)

    def test_soft_deleted_shared_analysis_404(self):
        """Soft-deleted analyses should not be accessible via share link."""
        token = self.analysis.share_token
        self.analysis.soft_delete()

        resp = self.client.get(f'/api/shared/{token}/')
        self.assertEqual(resp.status_code, 404)


@override_settings(
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    MEDIA_ROOT='/tmp/test_media_share',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ShareFieldExposureTests(TestCase):
    """Tests that share_token and share_url are exposed in list/detail serializers."""

    def setUp(self):
        self.user = User.objects.create_user('alice', 'alice@test.com', 'pass1234')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.analysis = ResumeAnalysis.all_objects.create(
            user=self.user,
            jd_input_type='text',
            jd_text='Test JD',
            jd_role='Backend Engineer',
            status=ResumeAnalysis.STATUS_DONE,
            pipeline_step=ResumeAnalysis.STEP_DONE,
            ats_score=82,
            share_token=uuid.uuid4(),
        )

    def test_detail_includes_share_token(self):
        resp = self.client.get(f'/api/analyses/{self.analysis.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('share_token', resp.data)
        self.assertIn('share_url', resp.data)
        self.assertEqual(resp.data['share_token'], str(self.analysis.share_token))
        self.assertEqual(resp.data['share_url'], f'/api/shared/{self.analysis.share_token}/')

    def test_list_includes_share_fields(self):
        resp = self.client.get('/api/analyses/')
        self.assertEqual(resp.status_code, 200)
        item = resp.data['results'][0]
        self.assertIn('share_token', item)
        self.assertIn('share_url', item)

    def test_detail_no_share_url_when_not_shared(self):
        self.analysis.share_token = None
        self.analysis.save(update_fields=['share_token'])

        resp = self.client.get(f'/api/analyses/{self.analysis.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['share_token'])
        self.assertIsNone(resp.data['share_url'])
