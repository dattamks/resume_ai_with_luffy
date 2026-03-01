"""
Tests for the default resume feature.

A user has exactly one "default" resume at a time. All personalised surfaces
(dashboard analytics, feed, skill-gap, recommendations) are scoped to the
default resume.

Behaviour:
- First resume uploaded is automatically marked as default.
- User can change the default via POST /api/v1/resumes/<uuid>/set-default/.
- Deleting the default resume promotes the next most-recent resume.
- Only one resume can be default per user (DB-enforced partial unique).
- GET /api/v1/resumes/ includes ``is_default`` in each entry.
- GET /api/v1/dashboard/stats/ includes ``default_resume_id``.
"""
import uuid

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status as http_status

from analyzer.models import Resume


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


class DefaultResumeModelTests(TestCase):
    """Unit tests for Resume.is_default, set_as_default, get_default_for_user."""

    def setUp(self):
        self.user = User.objects.create_user(username='defuser', password='StrongPass123!')

    # ── Auto-set on first upload ──────────────────────────────────────

    def test_first_resume_is_auto_default(self):
        resume, created = Resume.get_or_create_from_upload(self.user, _make_pdf())
        self.assertTrue(created)
        resume.refresh_from_db()
        self.assertTrue(resume.is_default)

    def test_second_resume_is_not_default(self):
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 first'))
        r2, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 second'))
        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertTrue(r1.is_default)
        self.assertFalse(r2.is_default)

    # ── set_as_default ────────────────────────────────────────────────

    def test_set_as_default_swaps(self):
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 aaa'))
        r2, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 bbb'))
        self.assertTrue(r1.is_default)

        r2.set_as_default()

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertFalse(r1.is_default)
        self.assertTrue(r2.is_default)

    def test_set_as_default_idempotent(self):
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())
        r1.set_as_default()  # already default — should not error
        r1.refresh_from_db()
        self.assertTrue(r1.is_default)

    # ── get_default_for_user ──────────────────────────────────────────

    def test_get_default_none_when_no_resumes(self):
        self.assertIsNone(Resume.get_default_for_user(self.user))

    def test_get_default_returns_correct_resume(self):
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 ccc'))
        r2, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 ddd'))
        r2.set_as_default()
        self.assertEqual(Resume.get_default_for_user(self.user), r2)

    # ── Uniqueness constraint ─────────────────────────────────────────

    def test_only_one_default_per_user(self):
        """DB constraint prevents two defaults via direct ORM manipulation."""
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 111'))
        r2, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 222'))
        # r1 is default already — force both True should violate constraint
        from django.db import IntegrityError
        r2.is_default = True
        with self.assertRaises(IntegrityError):
            r2.save(update_fields=['is_default'])


class SetDefaultResumeAPITests(TestCase):
    """Integration tests for POST /api/v1/resumes/<uuid>/set-default/."""

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.user = User.objects.create_user(username='apidefuser', password='StrongPass123!')
        _give_credits(self.user)
        token_resp = self.client.post(
            '/api/v1/auth/login/',
            {'username': 'apidefuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.token = token_resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

        self.r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 apione'))
        self.r2, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 apitwo'))

    def tearDown(self):
        cache.clear()

    def test_set_default_success(self):
        url = f'/api/v1/resumes/{self.r2.id}/set-default/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertEqual(resp.data['resume_id'], str(self.r2.id))

        self.r1.refresh_from_db()
        self.r2.refresh_from_db()
        self.assertFalse(self.r1.is_default)
        self.assertTrue(self.r2.is_default)

    def test_set_default_not_found(self):
        fake_id = uuid.uuid4()
        resp = self.client.post(f'/api/v1/resumes/{fake_id}/set-default/')
        self.assertEqual(resp.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_set_default_other_users_resume(self):
        other = User.objects.create_user(username='otheruser', password='StrongPass123!')
        other_resume, _ = Resume.get_or_create_from_upload(other, _make_pdf(b'%PDF-1.4 other'))
        resp = self.client.post(f'/api/v1/resumes/{other_resume.id}/set-default/')
        self.assertEqual(resp.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_set_default_unauthenticated(self):
        client = APIClient()
        resp = client.post(f'/api/v1/resumes/{self.r1.id}/set-default/')
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)


class ResumeListDefaultFlagTests(TestCase):
    """GET /api/v1/resumes/ returns is_default flag."""

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.user = User.objects.create_user(username='listdefuser', password='StrongPass123!')
        _give_credits(self.user)
        token_resp = self.client.post(
            '/api/v1/auth/login/',
            {'username': 'listdefuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.token = token_resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def tearDown(self):
        cache.clear()

    def test_is_default_in_response(self):
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 list1'))
        r2, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 list2'))

        resp = self.client.get('/api/v1/resumes/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)

        results = resp.data['results'] if 'results' in resp.data else resp.data
        for item in results:
            self.assertIn('is_default', item)

        # r1 should be default (uploaded first)
        default_items = [r for r in results if r['is_default']]
        self.assertEqual(len(default_items), 1)
        self.assertEqual(default_items[0]['id'], str(r1.id))


class DeleteDefaultResumeTests(TestCase):
    """Deleting the default resume should auto-promote the next most-recent."""

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.user = User.objects.create_user(username='deldefuser', password='StrongPass123!')
        _give_credits(self.user)
        token_resp = self.client.post(
            '/api/v1/auth/login/',
            {'username': 'deldefuser', 'password': 'StrongPass123!'},
            format='json',
        )
        self.token = token_resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def tearDown(self):
        cache.clear()

    def test_delete_default_promotes_next(self):
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 del1'))
        r2, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 del2'))
        self.assertTrue(r1.is_default)

        # Delete r1 (the default)
        resp = self.client.delete(f'/api/v1/resumes/{r1.id}/')
        self.assertEqual(resp.status_code, http_status.HTTP_204_NO_CONTENT)

        r2.refresh_from_db()
        self.assertTrue(r2.is_default)

    def test_delete_last_resume_leaves_no_default(self):
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 only'))

        resp = self.client.delete(f'/api/v1/resumes/{r1.id}/')
        self.assertEqual(resp.status_code, http_status.HTTP_204_NO_CONTENT)

        self.assertIsNone(Resume.get_default_for_user(self.user))

    def test_delete_non_default_keeps_original_default(self):
        r1, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 keep1'))
        r2, _ = Resume.get_or_create_from_upload(self.user, _make_pdf(b'%PDF-1.4 keep2'))
        self.assertTrue(r1.is_default)

        resp = self.client.delete(f'/api/v1/resumes/{r2.id}/')
        self.assertEqual(resp.status_code, http_status.HTTP_204_NO_CONTENT)

        r1.refresh_from_db()
        self.assertTrue(r1.is_default)
