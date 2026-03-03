"""
Tests for profile management endpoints:
  PUT    /api/auth/me/              — Update username/email
  DELETE /api/auth/me/              — Delete account permanently
  POST   /api/auth/change-password/ — Change password
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status


def _auth(client, username='profuser', password='StrongPass123!'):
    """Create user, login, set credentials. Returns (client, user)."""
    user = User.objects.create_user(username=username, password=password, email=f'{username}@test.com')
    resp = client.post('/api/v1/auth/login/', {'username': username, 'password': password}, format='json')
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client, user, resp.data.get('refresh')


class UpdateProfileTests(TestCase):
    """PUT /api/auth/me/"""

    def setUp(self):
        self.client = APIClient()
        self.client, self.user, _ = _auth(self.client)

    def test_update_username(self):
        resp = self.client.put('/api/v1/auth/me/', {'username': 'newname'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['username'], 'newname')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'newname')

    def test_update_email(self):
        resp = self.client.put('/api/v1/auth/me/', {'email': 'new@example.com'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['email'], 'new@example.com')

    def test_update_both(self):
        resp = self.client.put(
            '/api/v1/auth/me/',
            {'username': 'both', 'email': 'both@example.com'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['username'], 'both')
        self.assertEqual(resp.data['email'], 'both@example.com')

    def test_partial_update(self):
        """PUT with partial=True — only email, username unchanged."""
        resp = self.client.put('/api/v1/auth/me/', {'email': 'partial@example.com'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['username'], 'profuser')  # unchanged

    def test_duplicate_username_rejected(self):
        User.objects.create_user(username='taken', password='StrongPass123!')
        resp = self.client.put('/api/v1/auth/me/', {'username': 'taken'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)
        self.assertIn('username', resp.data.get('errors', {}))

    def test_duplicate_email_rejected(self):
        User.objects.create_user(username='other', password='StrongPass123!', email='used@test.com')
        resp = self.client.put('/api/v1/auth/me/', {'email': 'used@test.com'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)
        self.assertIn('email', resp.data.get('errors', {}))

    def test_requires_auth(self):
        resp = APIClient().put('/api/v1/auth/me/', {'username': 'x'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class ChangePasswordTests(TestCase):
    """POST /api/auth/change-password/"""

    def setUp(self):
        self.client = APIClient()
        self.client, self.user, _ = _auth(self.client, username='pwuser')

    def test_change_password_success(self):
        resp = self.client.post(
            '/api/v1/auth/change-password/',
            {'current_password': 'StrongPass123!', 'new_password': 'NewStrong456!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrong456!'))

    def test_wrong_current_password(self):
        resp = self.client.post(
            '/api/v1/auth/change-password/',
            {'current_password': 'WrongPass', 'new_password': 'NewStrong456!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)
        self.assertIn('current_password', resp.data.get('errors', {}))

    def test_weak_new_password(self):
        resp = self.client.post(
            '/api/v1/auth/change-password/',
            {'current_password': 'StrongPass123!', 'new_password': '123'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)
        self.assertIn('new_password', resp.data.get('errors', {}))

    def test_requires_auth(self):
        resp = APIClient().post(
            '/api/v1/auth/change-password/',
            {'current_password': 'x', 'new_password': 'y'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class DeleteAccountTests(TestCase):
    """DELETE /api/auth/me/"""

    def setUp(self):
        self.client = APIClient()
        self.client, self.user, self.refresh = _auth(self.client, username='deluser')

    def test_delete_account(self):
        user_id = self.user.id
        resp = self.client.delete('/api/v1/auth/me/', {'password': 'StrongPass123!'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(id=user_id).exists())

    def test_delete_cascades_analyses(self):
        """Analyses are soft-deleted, then user cascade-deletes everything."""
        from analyzer.models import ResumeAnalysis, Resume
        resume, _ = Resume.get_or_create_from_upload(
            self.user,
            SimpleUploadedFile('r.pdf', b'%PDF-1.4 fake', content_type='application/pdf'),
        )
        ResumeAnalysis.all_objects.create(
            user=self.user,
            resume_file=resume.file.name,
            resume=resume,
            jd_input_type='text',
            jd_text='dev',
        )
        resp = self.client.delete('/api/v1/auth/me/', {'password': 'StrongPass123!'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        # User + all owned objects are gone
        self.assertEqual(Resume.objects.filter(user=self.user).count(), 0)

    def test_requires_auth(self):
        resp = APIClient().delete('/api/v1/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
