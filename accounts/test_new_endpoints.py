"""
Tests for new account endpoints added in the backend backlog sweep.

Covers:
- POST /api/auth/forgot-password/
- POST /api/auth/reset-password/
- GET/PUT /api/auth/notifications/
- GET /api/auth/wallet/
- GET /api/auth/wallet/transactions/
- POST /api/auth/wallet/topup/
- GET /api/auth/plans/
- POST /api/auth/plans/subscribe/
- POST /api/auth/logout-all/
"""

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework import status


def _auth(client, username='testuser', email='test@example.com', password='StrongPass123!'):
    """Create a user, log in, and set Bearer credentials on the client."""
    user = User.objects.create_user(username=username, email=email, password=password)
    resp = client.post(
        '/api/v1/auth/login/',
        {'username': username, 'password': password},
        format='json',
    )
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client, user, resp.data.get('refresh')


def _ensure_free_plan():
    from accounts.models import Plan
    plan, _ = Plan.objects.get_or_create(
        slug='free',
        defaults={
            'name': 'Free', 'billing_cycle': 'free', 'price': 0,
            'credits_per_month': 2,
        },
    )
    return plan


# ── Forgot / Reset Password ─────────────────────────────────────────────────


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ForgotPasswordTests(TestCase):
    """POST /api/auth/forgot-password/"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='forgot', email='forgot@test.com', password='StrongPass123!',
        )

    @override_settings(
        FRONTEND_URL='http://localhost:5173',
    )
    def test_forgot_password_existing_email(self):
        # Create the email template so send_templated_email doesn't error
        from accounts.models import EmailTemplate
        EmailTemplate.objects.get_or_create(
            slug='password-reset',
            defaults={
                'name': 'Password Reset',
                'subject': 'Reset your password',
                'html_body': '<p>Reset: {{ reset_link }}</p>',
                'plain_text_body': 'Reset: {{ reset_link }}',
                'category': 'auth',
            },
        )
        resp = self.client.post(
            '/api/v1/auth/forgot-password/',
            {'email': 'forgot@test.com'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('reset link', resp.data['detail'])

    def test_forgot_password_nonexistent_email(self):
        """Should return 200 anyway (don't reveal whether email exists)."""
        resp = self.client.post(
            '/api/v1/auth/forgot-password/',
            {'email': 'nobody@test.com'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('reset link', resp.data['detail'])

    def test_forgot_password_missing_email(self):
        resp = self.client.post(
            '/api/v1/auth/forgot-password/',
            {},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_forgot_password_invalid_email_format(self):
        resp = self.client.post(
            '/api/v1/auth/forgot-password/',
            {'email': 'not-an-email'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ResetPasswordTests(TestCase):
    """POST /api/auth/reset-password/"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='reset', email='reset@test.com', password='StrongPass123!',
        )
        # Generate valid uid/token
        self.uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.token = default_token_generator.make_token(self.user)

    def test_reset_password_success(self):
        resp = self.client.post(
            '/api/v1/auth/reset-password/',
            {
                'uid': self.uid,
                'token': self.token,
                'new_password': 'NewStrong789!',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrong789!'))

    def test_reset_password_invalid_token(self):
        resp = self.client.post(
            '/api/v1/auth/reset-password/',
            {
                'uid': self.uid,
                'token': 'bad-token-value',
                'new_password': 'NewStrong789!',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_password_invalid_uid(self):
        resp = self.client.post(
            '/api/v1/auth/reset-password/',
            {
                'uid': 'XXXX',
                'token': self.token,
                'new_password': 'NewStrong789!',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_password_missing_fields(self):
        resp = self.client.post(
            '/api/v1/auth/reset-password/',
            {'uid': self.uid},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── Notification Preferences ────────────────────────────────────────────────


class NotificationPreferenceTests(TestCase):
    """GET / PUT /api/auth/notifications/"""

    def setUp(self):
        self.client = APIClient()
        self.client, self.user, _ = _auth(self.client, username='notifuser', email='notif@test.com')

    def test_get_notification_prefs(self):
        resp = self.client.get('/api/v1/auth/notifications/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Default values — all email channels on
        self.assertTrue(resp.data['job_alerts_email'])
        self.assertTrue(resp.data['feature_updates_email'])
        self.assertTrue(resp.data['newsletters_email'])

    def test_update_notification_prefs(self):
        resp = self.client.put(
            '/api/v1/auth/notifications/',
            {'newsletters_email': False, 'job_alerts_mobile': True},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['newsletters_email'])
        self.assertTrue(resp.data['job_alerts_mobile'])

    def test_partial_update(self):
        """Only send one field — others stay at defaults."""
        resp = self.client.put(
            '/api/v1/auth/notifications/',
            {'feature_updates_email': False},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['feature_updates_email'])
        self.assertTrue(resp.data['newsletters_email'])  # unchanged

    def test_requires_auth(self):
        resp = APIClient().get('/api/v1/auth/notifications/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Wallet ──────────────────────────────────────────────────────────────────


class WalletViewTests(TestCase):
    """GET /api/auth/wallet/"""

    def setUp(self):
        self.client = APIClient()
        _ensure_free_plan()
        self.client, self.user, _ = _auth(self.client, username='walletuser', email='wallet@test.com')

    def test_get_wallet(self):
        resp = self.client.get('/api/v1/auth/wallet/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('balance', resp.data)
        self.assertIn('plan_name', resp.data)

    def test_wallet_auto_creates(self):
        """Wallet should be auto-created on first access."""
        from accounts.models import Wallet
        Wallet.objects.filter(user=self.user).delete()
        resp = self.client.get('/api/v1/auth/wallet/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(Wallet.objects.filter(user=self.user).exists())

    def test_requires_auth(self):
        resp = APIClient().get('/api/v1/auth/wallet/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class WalletTransactionListTests(TestCase):
    """GET /api/auth/wallet/transactions/"""

    def setUp(self):
        self.client = APIClient()
        _ensure_free_plan()
        self.client, self.user, _ = _auth(self.client, username='txnuser', email='txn@test.com')

    def test_get_transactions_paginated(self):
        """Wallet creation itself may create a transaction; verify pagination works."""
        resp = self.client.get('/api/v1/auth/wallet/transactions/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('count', resp.data)
        self.assertIn('results', resp.data)

    def test_get_transactions_with_data(self):
        from accounts.models import Wallet, WalletTransaction
        wallet, _ = Wallet.objects.get_or_create(user=self.user)
        initial_count = WalletTransaction.objects.filter(wallet=wallet).count()
        WalletTransaction.objects.create(
            wallet=wallet, amount=10, balance_after=10,
            transaction_type='credit', description='Test credit',
        )
        resp = self.client.get('/api/v1/auth/wallet/transactions/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], initial_count + 1)

    def test_requires_auth(self):
        resp = APIClient().get('/api/v1/auth/wallet/transactions/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class WalletTopUpTests(TestCase):
    """POST /api/auth/wallet/topup/ (deprecated — redirects to Razorpay)"""

    def setUp(self):
        self.client = APIClient()
        self.client, self.user, _ = _auth(self.client, username='topupuser', email='topup@test.com')

    def test_topup_returns_payment_required(self):
        resp = self.client.post(
            '/api/v1/auth/wallet/topup/',
            {'quantity': 1},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn('payment_url', resp.data)


# ── Plans ────────────────────────────────────────────────────────────────────


class PlanListTests(TestCase):
    """GET /api/auth/plans/"""

    def setUp(self):
        self.client = APIClient()
        _ensure_free_plan()

    def test_list_plans_unauthenticated(self):
        """Plans are public — no auth required."""
        resp = self.client.get('/api/v1/auth/plans/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(len(resp.data) >= 1)

    def test_list_plans_shows_active_only(self):
        from accounts.models import Plan
        Plan.objects.create(
            name='Hidden', slug='hidden', billing_cycle='monthly',
            price=999, is_active=False,
        )
        resp = self.client.get('/api/v1/auth/plans/')
        slugs = [p['slug'] for p in resp.data]
        self.assertNotIn('hidden', slugs)


class PlanSubscribeTests(TestCase):
    """POST /api/auth/plans/subscribe/"""

    def setUp(self):
        self.client = APIClient()
        self.free_plan = _ensure_free_plan()
        self.client, self.user, _ = _auth(self.client, username='planuser', email='plan@test.com')

    def test_subscribe_free_plan(self):
        resp = self.client.post(
            '/api/v1/auth/plans/subscribe/',
            {'plan_slug': 'free'},
            format='json',
        )
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_subscribe_paid_plan_blocked(self):
        """Paid plans require Razorpay flow — direct subscribe returns 402."""
        from accounts.models import Plan
        Plan.objects.create(
            name='Pro', slug='pro', billing_cycle='monthly',
            price=499, is_active=True, credits_per_month=20,
        )
        resp = self.client.post(
            '/api/v1/auth/plans/subscribe/',
            {'plan_slug': 'pro'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn('payment_url', resp.data)

    def test_subscribe_missing_slug(self):
        resp = self.client.post(
            '/api/v1/auth/plans/subscribe/',
            {},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_subscribe_nonexistent_plan(self):
        resp = self.client.post(
            '/api/v1/auth/plans/subscribe/',
            {'plan_slug': 'nonexistent'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── Logout All Devices ──────────────────────────────────────────────────────


class LogoutAllDevicesTests(TestCase):
    """POST /api/auth/logout-all/"""

    def setUp(self):
        self.client = APIClient()
        self.client, self.user, self.refresh = _auth(
            self.client, username='logoutall', email='logoutall@test.com',
        )

    def test_logout_all_success(self):
        resp = self.client.post('/api/v1/auth/logout-all/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('invalidated', resp.data)
        self.assertGreaterEqual(resp.data['invalidated'], 1)

    def test_logout_all_blacklists_refresh(self):
        """After logout-all, the refresh token should be blacklisted."""
        self.client.post('/api/v1/auth/logout-all/')
        resp = self.client.post(
            '/api/v1/auth/token/refresh/',
            {'refresh': self.refresh},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_requires_auth(self):
        resp = APIClient().post('/api/v1/auth/logout-all/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
