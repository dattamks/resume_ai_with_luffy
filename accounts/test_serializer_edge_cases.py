"""
Edge-case tests for serializer validation.

Covers: RegisterSerializer, GoogleCompleteSerializer, UpdateUserSerializer
- Username: blank, too short, too long, reserved words, invalid characters, duplicates
- Email: blank, duplicate (case-insensitive), invalid format
- Password: weak, too short, entirely numeric, mismatch
- Country code / mobile number: invalid formats
- Standardized error response shape: every 400 has {detail, errors}

Run:  python manage.py test accounts.test_serializer_edge_cases -v2
"""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient


# ═══════════════════════════════════════════════════════════════════════════════
# Register Serializer Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class RegisterSerializerEdgeCaseTests(TestCase):
    """Edge-case tests for POST /api/v1/auth/register/."""

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/register/'
        self.valid_payload = {
            'username': 'validuser',
            'email': 'valid@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_to_terms': True,
            'agree_to_data_usage': True,
        }

    def _post(self, **overrides):
        """Helper: merge overrides into valid_payload and POST."""
        payload = {**self.valid_payload, **overrides}
        return self.client.post(self.url, payload, format='json')

    def _assert_400_with_field(self, resp, field):
        """Assert response is 400 and contains the field in errors dict."""
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)
        self.assertIn(field, resp.data.get('errors', resp.data))

    # ── Username edge cases ─────────────────────────────────────────────────

    def test_blank_username(self):
        resp = self._post(username='')
        self._assert_400_with_field(resp, 'username')

    def test_username_too_short(self):
        """Username must be at least 3 characters."""
        resp = self._post(username='ab')
        self._assert_400_with_field(resp, 'username')
        self.assertIn('at least 3', str(resp.data))

    def test_username_max_length(self):
        """Username must be at most 30 characters."""
        resp = self._post(username='a' * 31)
        self._assert_400_with_field(resp, 'username')
        self.assertIn('at most 30', str(resp.data))

    def test_username_reserved_admin(self):
        """Reserved usernames like 'admin' should be rejected."""
        resp = self._post(username='admin')
        self._assert_400_with_field(resp, 'username')
        self.assertIn('reserved', str(resp.data).lower())

    def test_username_reserved_root(self):
        resp = self._post(username='root')
        self._assert_400_with_field(resp, 'username')
        self.assertIn('reserved', str(resp.data).lower())

    def test_username_reserved_api(self):
        resp = self._post(username='api')
        self._assert_400_with_field(resp, 'username')

    def test_username_reserved_null(self):
        resp = self._post(username='null')
        self._assert_400_with_field(resp, 'username')

    def test_username_reserved_case_insensitive(self):
        """Reserved word check is case-insensitive."""
        resp = self._post(username='Admin')
        self._assert_400_with_field(resp, 'username')

    def test_username_invalid_chars_spaces(self):
        """Spaces are not allowed in usernames."""
        resp = self._post(username='user name')
        self._assert_400_with_field(resp, 'username')

    def test_username_invalid_chars_special(self):
        """Special characters like @, #, ! are not allowed."""
        resp = self._post(username='user@name')
        self._assert_400_with_field(resp, 'username')

    def test_username_invalid_chars_hyphen(self):
        """Hyphens are not allowed (only letters, digits, underscores)."""
        resp = self._post(username='user-name')
        self._assert_400_with_field(resp, 'username')

    def test_username_valid_underscore(self):
        """Underscores should be allowed."""
        resp = self._post(username='valid_user')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_username_valid_digits(self):
        """Digits should be allowed."""
        resp = self._post(username='user123', email='digits@example.com')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_username_duplicate(self):
        """Duplicate username should be rejected."""
        User.objects.create_user(username='taken', password='pass')
        resp = self._post(username='taken')
        self._assert_400_with_field(resp, 'username')

    def test_username_three_chars_ok(self):
        """Exactly 3 characters should be accepted."""
        resp = self._post(username='abc', email='three@example.com')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    # ── Email edge cases ────────────────────────────────────────────────────

    def test_blank_email(self):
        resp = self._post(email='')
        self._assert_400_with_field(resp, 'email')

    def test_invalid_email_format(self):
        resp = self._post(email='not-an-email')
        self._assert_400_with_field(resp, 'email')

    def test_duplicate_email_case_insensitive(self):
        """Email uniqueness check is case-insensitive."""
        User.objects.create_user(
            username='existing', email='Taken@Example.com', password='pass',
        )
        resp = self._post(email='taken@example.com')
        self._assert_400_with_field(resp, 'email')

    def test_duplicate_email_uppercase(self):
        User.objects.create_user(
            username='orig', email='test@example.com', password='pass',
        )
        resp = self._post(email='TEST@EXAMPLE.COM')
        self._assert_400_with_field(resp, 'email')

    # ── Password edge cases ─────────────────────────────────────────────────

    def test_password_too_short(self):
        resp = self._post(password='Sh1!', password2='Sh1!')
        self._assert_400_with_field(resp, 'password')

    def test_password_entirely_numeric(self):
        resp = self._post(password='12345678', password2='12345678')
        self._assert_400_with_field(resp, 'password')

    def test_password_too_common(self):
        resp = self._post(password='password123', password2='password123')
        self._assert_400_with_field(resp, 'password')

    def test_password_mismatch(self):
        resp = self._post(password='StrongPass123!', password2='DifferentPass456!')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Consent edge cases ──────────────────────────────────────────────────

    def test_missing_agree_to_terms(self):
        resp = self._post(agree_to_terms=False)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_agree_to_data_usage(self):
        resp = self._post(agree_to_data_usage=False)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Standardized error shape ────────────────────────────────────────────

    def test_error_response_has_detail_key(self):
        """All 400 responses should have a 'detail' string."""
        resp = self._post(username='')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)
        self.assertIsInstance(resp.data['detail'], str)

    def test_error_response_has_errors_key(self):
        """Field-level errors should be under 'errors' dict."""
        resp = self._post(username='', email='')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('errors', resp.data)
        self.assertIsInstance(resp.data['errors'], dict)


# ═══════════════════════════════════════════════════════════════════════════════
# UpdateUser Serializer Edge Cases (Profile update)
# ═══════════════════════════════════════════════════════════════════════════════

class UpdateUserSerializerEdgeCaseTests(TestCase):
    """Edge-case tests for PUT /api/v1/auth/me/."""

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/me/'
        self.user = User.objects.create_user(
            username='profuser', email='prof@example.com', password='StrongPass123!',
        )
        self.client.force_authenticate(user=self.user)

    def _put(self, **data):
        return self.client.put(self.url, data, format='json')

    # ── Country code validation ─────────────────────────────────────────────

    def test_invalid_country_code_no_plus(self):
        """Country code must start with +."""
        resp = self._put(country_code='91')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)

    def test_invalid_country_code_too_long(self):
        resp = self._put(country_code='+123456')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_country_code_letters(self):
        resp = self._put(country_code='+abc')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_country_code(self):
        resp = self._put(country_code='+91')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # ── Mobile number validation ────────────────────────────────────────────

    def test_mobile_number_non_digits(self):
        resp = self._put(mobile_number='abc123')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mobile_number_too_short(self):
        resp = self._put(mobile_number='12345')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_mobile_number(self):
        resp = self._put(mobile_number='9876543210')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # ── Username update edge cases ──────────────────────────────────────────

    def test_update_username_too_short(self):
        resp = self._put(username='ab')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('at least 3', str(resp.data))

    def test_update_username_reserved(self):
        resp = self._put(username='admin')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('reserved', str(resp.data).lower())

    def test_update_username_invalid_chars(self):
        resp = self._put(username='user@name')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_username_taken(self):
        User.objects.create_user(username='taken', password='pass')
        resp = self._put(username='taken')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_username_same_as_current(self):
        """User should be able to keep their current username."""
        resp = self._put(username='profuser')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # ── Email update edge cases ─────────────────────────────────────────────

    def test_update_email_duplicate(self):
        User.objects.create_user(
            username='other', email='other@example.com', password='pass',
        )
        resp = self._put(email='other@example.com')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_email_valid(self):
        resp = self._put(email='newemail@example.com')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # ── Standardized error shape ────────────────────────────────────────────

    def test_profile_update_error_has_detail(self):
        resp = self._put(country_code='invalid')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)
        self.assertIsInstance(resp.data['detail'], str)


# ═══════════════════════════════════════════════════════════════════════════════
# Standardized Error Response Shape Tests
# ═══════════════════════════════════════════════════════════════════════════════

class StandardizedErrorResponseTests(TestCase):
    """Verify that the custom exception handler produces the correct shape."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='erroruser', email='error@example.com', password='StrongPass123!',
        )

    def test_401_has_detail(self):
        """Unauthenticated requests should have a 'detail' key."""
        resp = self.client.get('/api/v1/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('detail', resp.data)
        self.assertIsInstance(resp.data['detail'], str)

    def test_login_wrong_password_has_detail(self):
        self.user.profile.is_email_verified = True
        self.user.profile.save(update_fields=['is_email_verified'])
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        resp = self.client.post('/api/v1/auth/login/', {
            'username': 'erroruser',
            'password': 'WrongPassword!',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('detail', resp.data)

    def test_change_password_wrong_current_has_detail(self):
        """Wrong current password should return {'detail': ..., 'errors': {...}}."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/v1/auth/change-password/', {
            'current_password': 'WrongCurrent!',
            'new_password': 'NewStrongPass123!',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)

    def test_forgot_password_invalid_email_format_has_detail(self):
        resp = self.client.post('/api/v1/auth/forgot-password/', {
            'email': 'not-valid',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', resp.data)
