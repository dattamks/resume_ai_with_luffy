"""
Tests for the resume rename / display_name feature.

Covers:
- Happy path (Resume + GeneratedResume)
- Edge cases (max length, unicode, special chars, whitespace, XSS)
- Auth & permissions (unauthenticated, cross-user, nonexistent)
- HTTP method enforcement (PUT/DELETE/GET blocked)
- Payload validation (extra fields, readonly fields)
- Search integration (display_name searchable)
"""
import uuid

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from analyzer.models import Resume, GeneratedResume, ResumeAnalysis


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


def _login(client, username, password):
    resp = client.post(
        '/api/v1/auth/login/',
        {'username': username, 'password': password},
        format='json',
    )
    return resp.data['access']


class ResumeRenameTests(TestCase):
    """Tests for PATCH /api/v1/resumes/<uuid>/rename/"""

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.user = User.objects.create_user(username='renameuser', password='StrongPass123!')
        _give_credits(self.user)
        token = _login(self.client, 'renameuser', 'StrongPass123!')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        self.resume, _ = Resume.get_or_create_from_upload(self.user, _make_pdf())
        self.url = f'/api/v1/resumes/{self.resume.pk}/rename/'

    def tearDown(self):
        cache.clear()

    # ── Happy Path ────────────────────────────────────────────────────

    def test_rename_resume_success(self):
        resp = self.client.patch(self.url, {'display_name': 'My Best Resume'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], 'My Best Resume')
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.display_name, 'My Best Resume')

    def test_display_name_appears_in_list(self):
        self.resume.display_name = 'Listed Name'
        self.resume.save(update_fields=['display_name'])

        resp = self.client.get('/api/v1/resumes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [r['display_name'] for r in resp.data['results']]
        self.assertIn('Listed Name', names)

    def test_clear_display_name(self):
        self.resume.display_name = 'Temp Name'
        self.resume.save(update_fields=['display_name'])

        resp = self.client.patch(self.url, {'display_name': ''}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], '')

    def test_rename_preserves_other_fields(self):
        original_filename = self.resume.original_filename
        file_size = self.resume.file_size_bytes
        is_default = self.resume.is_default

        self.client.patch(self.url, {'display_name': 'New Name'}, format='json')
        self.resume.refresh_from_db()

        self.assertEqual(self.resume.original_filename, original_filename)
        self.assertEqual(self.resume.file_size_bytes, file_size)
        self.assertEqual(self.resume.is_default, is_default)

    def test_rename_does_not_affect_file(self):
        file_name_before = self.resume.file.name
        self.client.patch(self.url, {'display_name': 'Renamed'}, format='json')
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.file.name, file_name_before)

    # ── Edge Cases ────────────────────────────────────────────────────

    def test_display_name_max_length(self):
        name = 'A' * 255
        resp = self.client.patch(self.url, {'display_name': name}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], name)

    def test_display_name_exceeds_max_length(self):
        name = 'A' * 256
        resp = self.client.patch(self.url, {'display_name': name}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_display_name_with_unicode(self):
        resp = self.client.patch(self.url, {'display_name': '日本語の履歴書'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], '日本語の履歴書')

    def test_display_name_with_special_chars(self):
        name = 'Resume (v2) — Senior Dev @Google #1'
        resp = self.client.patch(self.url, {'display_name': name}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], name)

    def test_display_name_with_leading_trailing_spaces(self):
        resp = self.client.patch(self.url, {'display_name': '  My Resume  '}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], 'My Resume')

    def test_display_name_with_html_tags(self):
        """HTML tags stored as plain text — no XSS risk (CharField)."""
        name = "<script>alert('xss')</script>"
        resp = self.client.patch(self.url, {'display_name': name}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.display_name, name)

    def test_rename_same_name_twice(self):
        self.client.patch(self.url, {'display_name': 'First'}, format='json')
        resp = self.client.patch(self.url, {'display_name': 'Second'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], 'Second')

    def test_two_resumes_same_display_name(self):
        resume2, _ = Resume.get_or_create_from_upload(
            self.user, _make_pdf(b'%PDF-1.4 different content'),
        )
        url2 = f'/api/v1/resumes/{resume2.pk}/rename/'

        r1 = self.client.patch(self.url, {'display_name': 'Same Name'}, format='json')
        r2 = self.client.patch(url2, {'display_name': 'Same Name'}, format='json')
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)

    def test_default_display_name_is_blank(self):
        fresh = Resume.get_or_create_from_upload(
            self.user, _make_pdf(b'%PDF-1.4 brand new'),
        )[0]
        self.assertEqual(fresh.display_name, '')

    # ── Auth & Permissions ────────────────────────────────────────────

    def test_rename_unauthenticated(self):
        client = APIClient()
        resp = client.patch(self.url, {'display_name': 'Hacked'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rename_other_users_resume(self):
        other = User.objects.create_user(username='otheruser', password='StrongPass123!')
        _give_credits(other)
        client2 = APIClient()
        token2 = _login(client2, 'otheruser', 'StrongPass123!')
        client2.credentials(HTTP_AUTHORIZATION=f'Bearer {token2}')

        resp = client2.patch(self.url, {'display_name': 'Stolen'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_rename_nonexistent_resume(self):
        url = f'/api/v1/resumes/{uuid.uuid4()}/rename/'
        resp = self.client.patch(url, {'display_name': 'Ghost'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    # ── HTTP Method Enforcement ───────────────────────────────────────

    def test_put_not_allowed(self):
        resp = self.client.put(self.url, {'display_name': 'X'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed_on_rename_endpoint(self):
        resp = self.client.delete(self.url)
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_get_not_allowed_on_rename_endpoint(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # ── Payload Validation ────────────────────────────────────────────

    def test_patch_with_no_body(self):
        resp = self.client.patch(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_patch_with_extra_fields_ignored(self):
        resp = self.client.patch(
            self.url,
            {'display_name': 'Valid', 'original_filename': 'hacked.pdf'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.display_name, 'Valid')
        self.assertNotEqual(self.resume.original_filename, 'hacked.pdf')

    def test_patch_original_filename_readonly(self):
        original = self.resume.original_filename
        self.client.patch(
            self.url, {'original_filename': 'evil.pdf'}, format='json',
        )
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.original_filename, original)

    def test_patch_file_hash_readonly(self):
        original_hash = self.resume.file_hash
        self.client.patch(
            self.url, {'file_hash': 'deadbeef' * 8}, format='json',
        )
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.file_hash, original_hash)

    def test_patch_is_default_readonly(self):
        original_default = self.resume.is_default
        self.client.patch(
            self.url, {'is_default': not original_default}, format='json',
        )
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.is_default, original_default)

    # ── Search Integration ────────────────────────────────────────────

    def test_search_by_display_name(self):
        self.resume.display_name = 'Google SWE Application'
        self.resume.save(update_fields=['display_name'])

        resp = self.client.get('/api/v1/resumes/?search=Google')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['display_name'], 'Google SWE Application')


class GeneratedResumeRenameTests(TestCase):
    """Tests for PATCH /api/v1/generated-resumes/<uuid>/rename/"""

    def setUp(self):
        _ensure_free_plan()
        self.client = APIClient()
        self.user = User.objects.create_user(username='genrenamer', password='StrongPass123!')
        _give_credits(self.user)
        token = _login(self.client, 'genrenamer', 'StrongPass123!')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        self.gen = GeneratedResume.objects.create(
            user=self.user,
            template='ats_classic',
            format='pdf',
            status='done',
        )
        self.url = f'/api/v1/generated-resumes/{self.gen.pk}/rename/'

    def tearDown(self):
        cache.clear()

    # ── Happy Path ────────────────────────────────────────────────────

    def test_rename_generated_resume_success(self):
        resp = self.client.patch(self.url, {'display_name': 'Google SWE v2'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], 'Google SWE v2')
        self.gen.refresh_from_db()
        self.assertEqual(self.gen.display_name, 'Google SWE v2')

    def test_display_name_appears_in_generated_list(self):
        self.gen.display_name = 'My Generated'
        self.gen.save(update_fields=['display_name'])

        resp = self.client.get('/api/v1/generated-resumes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [r['display_name'] for r in resp.data['results']]
        self.assertIn('My Generated', names)

    def test_clear_generated_display_name(self):
        self.gen.display_name = 'Temp'
        self.gen.save(update_fields=['display_name'])

        resp = self.client.patch(self.url, {'display_name': ''}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], '')

    # ── Edge Cases ────────────────────────────────────────────────────

    def test_generated_display_name_max_length(self):
        name = 'B' * 255
        resp = self.client.patch(self.url, {'display_name': name}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_generated_display_name_exceeds_max_length(self):
        name = 'B' * 256
        resp = self.client.patch(self.url, {'display_name': name}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generated_display_name_unicode(self):
        resp = self.client.patch(self.url, {'display_name': '이력서 v3'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], '이력서 v3')

    def test_generated_leading_trailing_spaces_stripped(self):
        resp = self.client.patch(self.url, {'display_name': '  Padded  '}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['display_name'], 'Padded')

    def test_generated_default_display_name_is_blank(self):
        fresh = GeneratedResume.objects.create(
            user=self.user, template='ats_classic', format='pdf', status='done',
        )
        self.assertEqual(fresh.display_name, '')

    # ── Auth & Permissions ────────────────────────────────────────────

    def test_rename_generated_unauthenticated(self):
        client = APIClient()
        resp = client.patch(self.url, {'display_name': 'Hacked'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rename_other_users_generated_resume(self):
        other = User.objects.create_user(username='otherguser', password='StrongPass123!')
        _give_credits(other)
        client2 = APIClient()
        token2 = _login(client2, 'otherguser', 'StrongPass123!')
        client2.credentials(HTTP_AUTHORIZATION=f'Bearer {token2}')

        resp = client2.patch(self.url, {'display_name': 'Stolen'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_rename_nonexistent_generated_resume(self):
        url = f'/api/v1/generated-resumes/{uuid.uuid4()}/rename/'
        resp = self.client.patch(url, {'display_name': 'Ghost'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    # ── HTTP Method Enforcement ───────────────────────────────────────

    def test_put_not_allowed_generated(self):
        resp = self.client.put(self.url, {'display_name': 'X'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed_on_generated_rename(self):
        resp = self.client.delete(self.url)
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_get_not_allowed_on_generated_rename(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # ── Payload Validation ────────────────────────────────────────────

    def test_patch_generated_with_no_body(self):
        resp = self.client.patch(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_patch_generated_extra_fields_ignored(self):
        resp = self.client.patch(
            self.url,
            {'display_name': 'Valid', 'template': 'hacked_template'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.gen.refresh_from_db()
        self.assertEqual(self.gen.display_name, 'Valid')
        self.assertEqual(self.gen.template, 'ats_classic')
