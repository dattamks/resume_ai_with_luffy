from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status


class RegisterViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/register/'

    def test_register_success(self):
        payload = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
            'marketing_opt_in': False,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)
        self.assertEqual(resp.data['user']['username'], 'testuser')

    def test_register_password_mismatch(self):
        payload = {
            'username': 'testuser2',
            'email': 'test2@example.com',
            'password': 'StrongPass123!',
            'password2': 'Different456!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_username(self):
        User.objects.create_user(username='existing', password='pass')
        payload = {
            'username': 'existing',
            'email': 'new@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_weak_password(self):
        payload = {
            'username': 'weakuser',
            'email': 'weak@example.com',
            'password': '123',
            'password2': '123',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_terms_consent(self):
        """Registration fails when agree_to_terms is not True."""
        payload = {
            'username': 'noterms',
            'email': 'noterms@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_to_terms': False,
            'agree_to_data_usage': True,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('agree_to_terms', resp.data)

    def test_register_missing_data_usage_consent(self):
        """Registration fails when agree_to_data_usage is not True."""
        payload = {
            'username': 'nodatausage',
            'email': 'nodatausage@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': False,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('agree_to_data_usage', resp.data)

    def test_register_consent_logged(self):
        """ConsentLog entries are created on successful registration."""
        from accounts.models import ConsentLog
        payload = {
            'username': 'consentuser',
            'email': 'consent@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
            'marketing_opt_in': True,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='consentuser')
        logs = ConsentLog.objects.filter(user=user)
        self.assertEqual(logs.count(), 3)
        self.assertTrue(logs.filter(consent_type='terms_privacy', agreed=True).exists())
        self.assertTrue(logs.filter(consent_type='data_usage_ai', agreed=True).exists())
        self.assertTrue(logs.filter(consent_type='marketing_newsletter', agreed=True).exists())

    def test_register_marketing_opt_in_syncs_newsletter_pref(self):
        """marketing_opt_in=True syncs to NotificationPreference.newsletters_email."""
        payload = {
            'username': 'marketuser',
            'email': 'market@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
            'marketing_opt_in': True,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='marketuser')
        self.assertTrue(user.profile.marketing_opt_in)
        self.assertTrue(user.notification_preferences.newsletters_email)

    def test_register_consent_fields_in_response(self):
        """Registration response includes consent flags."""
        payload = {
            'username': 'respuser',
            'email': 'resp@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
            'marketing_opt_in': False,
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['user']['agreed_to_terms'])
        self.assertTrue(resp.data['user']['agreed_to_data_usage'])
        self.assertFalse(resp.data['user']['marketing_opt_in'])


class LoginViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/login/'
        self.user = User.objects.create_user(username='loginuser', password='StrongPass123!')

    def test_login_success(self):
        resp = self.client.post(self.url, {'username': 'loginuser', 'password': 'StrongPass123!'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

    def test_login_wrong_password(self):
        resp = self.client.post(self.url, {'username': 'loginuser', 'password': 'wrong'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_unknown_user(self):
        resp = self.client.post(self.url, {'username': 'nobody', 'password': 'pass'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class LogoutViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='logoutuser', password='StrongPass123!')

    def _get_tokens(self):
        resp = self.client.post('/api/v1/auth/login/', {'username': 'logoutuser', 'password': 'StrongPass123!'}, format='json')
        return resp.data['access'], resp.data['refresh']

    def test_logout_success(self):
        access, refresh = self._get_tokens()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        resp = self.client.post('/api/v1/auth/logout/', {'refresh': refresh}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_logout_requires_auth(self):
        resp = self.client.post('/api/v1/auth/logout/', {'refresh': 'dummy'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class MeViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='meuser', email='me@example.com', password='StrongPass123!')

    def test_me_authenticated(self):
        resp = self.client.post('/api/v1/auth/login/', {'username': 'meuser', 'password': 'StrongPass123!'}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
        me_resp = self.client.get('/api/v1/auth/me/')
        self.assertEqual(me_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(me_resp.data['username'], 'meuser')

    def test_me_unauthenticated(self):
        resp = self.client.get('/api/v1/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Google OAuth Tests ──────────────────────────────────────────────────────

class GoogleLoginViewTests(TestCase):
    """Tests for POST /api/auth/google/"""

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/google/'

    @patch('accounts.views.settings')
    def test_returns_503_when_not_configured(self, mock_settings):
        """Returns 503 when GOOGLE_OAUTH2_CLIENT_ID is empty."""
        mock_settings.GOOGLE_OAUTH2_CLIENT_ID = ''
        mock_settings.SECRET_KEY = 'test-secret'
        resp = self.client.post(self.url, {'token': 'fake'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @override_settings(GOOGLE_OAUTH2_CLIENT_ID='test-client-id')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_existing_user_returns_jwt(self, mock_verify):
        """Existing user gets JWT tokens immediately."""
        User.objects.create_user(
            username='existinggoogle', email='existing@gmail.com', password='Pass123!',
        )
        mock_verify.return_value = {
            'email': 'existing@gmail.com',
            'email_verified': True,
            'sub': 'google-sub-123',
            'name': 'Existing User',
            'picture': 'https://example.com/pic.jpg',
        }
        resp = self.client.post(self.url, {'token': 'valid-google-token'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)
        self.assertEqual(resp.data['user']['email'], 'existing@gmail.com')
        self.assertNotIn('needs_registration', resp.data)

    @override_settings(GOOGLE_OAUTH2_CLIENT_ID='test-client-id')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_new_user_returns_needs_registration(self, mock_verify):
        """New user gets needs_registration flag, temp_token, and profile details."""
        mock_verify.return_value = {
            'email': 'newuser@gmail.com',
            'email_verified': True,
            'sub': 'google-sub-456',
            'name': 'New User',
            'given_name': 'New',
            'family_name': 'User',
            'picture': 'https://example.com/pic2.jpg',
        }
        resp = self.client.post(self.url, {'token': 'valid-google-token'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['needs_registration'])
        self.assertIn('temp_token', resp.data)
        self.assertEqual(resp.data['email'], 'newuser@gmail.com')
        self.assertEqual(resp.data['name'], 'New User')
        self.assertEqual(resp.data['given_name'], 'New')
        self.assertEqual(resp.data['family_name'], 'User')
        self.assertEqual(resp.data['picture'], 'https://example.com/pic2.jpg')
        self.assertNotIn('access', resp.data)

    @override_settings(GOOGLE_OAUTH2_CLIENT_ID='test-client-id')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_invalid_token_returns_401(self, mock_verify):
        """Invalid Google token returns 401."""
        mock_verify.side_effect = ValueError('Token expired')
        resp = self.client.post(self.url, {'token': 'expired-token'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(GOOGLE_OAUTH2_CLIENT_ID='test-client-id')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_unverified_email_returns_400(self, mock_verify):
        """Unverified Google email returns 400."""
        mock_verify.return_value = {
            'email': 'unverified@gmail.com',
            'email_verified': False,
            'sub': 'google-sub-789',
        }
        resp = self.client.post(self.url, {'token': 'valid-token'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not verified', resp.data['detail'])

    def test_missing_token_returns_400(self):
        """Missing token field returns 400."""
        resp = self.client.post(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(GOOGLE_OAUTH2_CLIENT_ID='test-client-id')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_case_insensitive_email_match(self, mock_verify):
        """Email matching is case-insensitive."""
        User.objects.create_user(
            username='caseuser', email='CaseUser@Gmail.COM', password='Pass123!',
        )
        mock_verify.return_value = {
            'email': 'caseuser@gmail.com',
            'email_verified': True,
            'sub': 'google-sub-case',
            'name': 'Case User',
        }
        resp = self.client.post(self.url, {'token': 'valid'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)

    @override_settings(GOOGLE_OAUTH2_CLIENT_ID='test-client-id')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_existing_user_syncs_blank_fields(self, mock_verify):
        """Returning Google user: blank name/avatar get filled from Google."""
        user = User.objects.create_user(
            username='syncuser', email='sync@gmail.com', password='Pass123!',
            first_name='', last_name='',
        )
        # Profile has no avatar and default auth_provider='email'
        mock_verify.return_value = {
            'email': 'sync@gmail.com',
            'email_verified': True,
            'sub': 'google-sub-sync',
            'name': 'Sync User',
            'given_name': 'Sync',
            'family_name': 'User',
            'picture': 'https://example.com/avatar.jpg',
        }
        resp = self.client.post(self.url, {'token': 'valid'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertEqual(user.first_name, 'Sync')
        self.assertEqual(user.last_name, 'User')
        self.assertEqual(user.profile.avatar_url, 'https://example.com/avatar.jpg')
        self.assertEqual(user.profile.google_sub, 'google-sub-sync')
        self.assertEqual(user.profile.auth_provider, 'google')

    @override_settings(GOOGLE_OAUTH2_CLIENT_ID='test-client-id')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_existing_user_does_not_overwrite_manual_edits(self, mock_verify):
        """Returning Google user: manually set name/avatar NOT overwritten."""
        user = User.objects.create_user(
            username='manualuser', email='manual@gmail.com', password='Pass123!',
            first_name='Custom', last_name='Name',
        )
        profile = user.profile
        profile.avatar_url = 'https://my-custom-avatar.com/pic.png'
        profile.auth_provider = 'google'
        profile.google_sub = 'original-sub'
        profile.save(update_fields=['avatar_url', 'auth_provider', 'google_sub'])

        mock_verify.return_value = {
            'email': 'manual@gmail.com',
            'email_verified': True,
            'sub': 'google-sub-updated',
            'name': 'Google Name',
            'given_name': 'Google',
            'family_name': 'Name',
            'picture': 'https://google.com/new-avatar.jpg',
        }
        resp = self.client.post(self.url, {'token': 'valid'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        user.refresh_from_db()
        user.profile.refresh_from_db()
        # Name and avatar should NOT be overwritten
        self.assertEqual(user.first_name, 'Custom')
        self.assertEqual(user.last_name, 'Name')
        self.assertEqual(user.profile.avatar_url, 'https://my-custom-avatar.com/pic.png')
        # google_sub should always update
        self.assertEqual(user.profile.google_sub, 'google-sub-updated')


class GoogleCompleteViewTests(TestCase):
    """Tests for POST /api/auth/google/complete/"""

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/google/complete/'

    def _make_temp_token(self, email='new@gmail.com', ttl=600, **extra):
        from accounts.views import _sign_temp_token
        import time
        payload = {
            'email': email,
            'google_sub': 'google-sub-test',
            'name': 'Test User',
            'given_name': 'Test',
            'family_name': 'User',
            'picture': 'https://example.com/avatar.jpg',
            'exp': int(time.time()) + ttl,
            **extra,
        }
        return _sign_temp_token(payload)

    def test_complete_creates_user_with_consent(self):
        """Successful completion creates user with Google profile, logs consent, returns JWT."""
        token = self._make_temp_token()
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'googlenewuser',
            'password': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
            'marketing_opt_in': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)
        self.assertEqual(resp.data['user']['username'], 'googlenewuser')
        self.assertEqual(resp.data['user']['email'], 'new@gmail.com')

        # Verify user created with Google profile details
        user = User.objects.get(username='googlenewuser')
        self.assertEqual(user.email, 'new@gmail.com')
        self.assertEqual(user.first_name, 'Test')
        self.assertEqual(user.last_name, 'User')
        self.assertTrue(user.profile.agreed_to_terms)
        self.assertTrue(user.profile.agreed_to_data_usage)
        self.assertTrue(user.profile.marketing_opt_in)
        self.assertEqual(user.profile.auth_provider, 'google')
        self.assertEqual(user.profile.avatar_url, 'https://example.com/avatar.jpg')
        self.assertEqual(user.profile.google_sub, 'google-sub-test')

        # Verify consent log
        from accounts.models import ConsentLog
        logs = ConsentLog.objects.filter(user=user)
        self.assertEqual(logs.count(), 3)

        # Verify newsletter sync
        self.assertTrue(user.notification_preferences.newsletters_email)

    def test_complete_without_marketing_defaults_false(self):
        """marketing_opt_in defaults to False when omitted."""
        token = self._make_temp_token()
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'nomarketing',
            'password': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='nomarketing')
        self.assertFalse(user.profile.marketing_opt_in)

    def test_complete_rejects_expired_token(self):
        """Expired temp token returns 400."""
        token = self._make_temp_token(ttl=-10)  # already expired
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'expireduser',
            'password': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('expired', resp.data['detail'].lower())

    def test_complete_rejects_tampered_token(self):
        """Tampered token returns 400."""
        resp = self.client.post(self.url, {
            'temp_token': 'totally.invalid.token',
            'username': 'tamperuser',
            'password': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_rejects_missing_terms(self):
        """Missing terms consent returns 400."""
        token = self._make_temp_token()
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'noterms',
            'password': 'StrongPass123!',
            'agree_to_terms': False,
            'agree_to_data_usage': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('agree_to_terms', str(resp.data))

    def test_complete_rejects_missing_data_usage(self):
        """Missing data usage consent returns 400."""
        token = self._make_temp_token()
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'nodatausage',
            'password': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': False,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('agree_to_data_usage', str(resp.data))

    def test_complete_rejects_duplicate_username(self):
        """Duplicate username returns 400."""
        User.objects.create_user(username='taken', password='Pass123!')
        token = self._make_temp_token()
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'taken',
            'password': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', str(resp.data))

    def test_complete_rejects_weak_password(self):
        """Weak password returns 400."""
        token = self._make_temp_token()
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'weakpwuser',
            'password': '123',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_409_if_email_already_taken(self):
        """Returns 409 if email was registered between step 1 and step 2."""
        User.objects.create_user(
            username='raceuser', email='new@gmail.com', password='Pass123!',
        )
        token = self._make_temp_token(email='new@gmail.com')
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'raceuser2',
            'password': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_complete_consent_fields_in_response(self):
        """Response includes consent flags, profile fields, and auth_provider in user object."""
        token = self._make_temp_token()
        resp = self.client.post(self.url, {
            'temp_token': token,
            'username': 'consentresp',
            'password': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
            'marketing_opt_in': False,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['user']['agreed_to_terms'])
        self.assertTrue(resp.data['user']['agreed_to_data_usage'])
        self.assertFalse(resp.data['user']['marketing_opt_in'])
        self.assertEqual(resp.data['user']['auth_provider'], 'google')
        self.assertEqual(resp.data['user']['avatar_url'], 'https://example.com/avatar.jpg')
        self.assertEqual(resp.data['user']['first_name'], 'Test')
        self.assertEqual(resp.data['user']['last_name'], 'User')
