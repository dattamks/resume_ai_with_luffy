"""
Tests for Razorpay payment integration.

Tests cover:
- Payment model creation & constraints
- Subscription flow (create, verify, cancel, status)
- Top-up flow (create order, verify)
- Webhook handling (signature verification, event processing)
- Idempotency (duplicate payment handling)
- Edge cases (free plan topup, no active subscription cancel, etc.)
"""
import hashlib
import hmac
import json
from unittest.mock import patch, MagicMock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import (
    Plan, Wallet, WalletTransaction, UserProfile,
    RazorpayPayment, RazorpaySubscription,
)


class PaymentTestMixin:
    """Shared setup for payment tests."""

    def setUp(self):
        self.client = APIClient()

        # Create plans
        self.free_plan = Plan.objects.create(
            name='Free', slug='free', billing_cycle='free', price=0,
            credits_per_month=2, max_credits_balance=10,
            topup_credits_per_pack=0, topup_price=0,
            is_active=True, display_order=0,
        )
        self.pro_plan = Plan.objects.create(
            name='Pro', slug='pro', billing_cycle='monthly', price=499,
            credits_per_month=25, max_credits_balance=100,
            topup_credits_per_pack=5, topup_price=49,
            job_notifications=True, max_job_alerts=3,
            is_active=True, display_order=10,
        )

        # Create user (auto-creates profile, wallet via signal)
        self.user = User.objects.create_user(
            username='paytest', email='pay@test.com', password='StrongPass123!'
        )
        self._login()

    def _login(self):
        resp = self.client.post('/api/v1/auth/login/', {
            'username': 'paytest', 'password': 'StrongPass123!'
        }, format='json')
        self.access = resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access}')

    def _make_signature(self, data_str, secret=None):
        """Generate HMAC-SHA256 signature for testing."""
        if secret is None:
            secret = settings.RAZORPAY_KEY_SECRET
        return hmac.new(
            secret.encode(), data_str.encode(), hashlib.sha256,
        ).hexdigest()

    def _make_webhook_signature(self, body_bytes, secret=None):
        """Generate webhook signature."""
        if secret is None:
            secret = settings.RAZORPAY_WEBHOOK_SECRET
        return hmac.new(
            secret.encode(), body_bytes, hashlib.sha256,
        ).hexdigest()


class RazorpayPaymentModelTests(PaymentTestMixin, TestCase):
    """Tests for RazorpayPayment and RazorpaySubscription models."""

    def test_create_payment_record(self):
        payment = RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id='order_test123',
            amount=4900,
            currency='INR',
            status=RazorpayPayment.STATUS_CREATED,
        )
        self.assertEqual(payment.amount, 4900)
        self.assertEqual(payment.status, 'created')
        self.assertFalse(payment.credits_granted)
        self.assertFalse(payment.webhook_verified)

    def test_create_subscription_record(self):
        subscription = RazorpaySubscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            razorpay_subscription_id='sub_test123',
            razorpay_plan_id='plan_pro_monthly',
            status=RazorpaySubscription.STATUS_CREATED,
        )
        self.assertEqual(subscription.status, 'created')
        self.assertFalse(subscription.is_active)

    def test_subscription_is_active_property(self):
        subscription = RazorpaySubscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            razorpay_subscription_id='sub_active',
            razorpay_plan_id='plan_pro_monthly',
            status=RazorpaySubscription.STATUS_ACTIVE,
        )
        self.assertTrue(subscription.is_active)

        subscription.status = RazorpaySubscription.STATUS_CANCELLED
        self.assertFalse(subscription.is_active)

    def test_payment_unique_payment_id(self):
        """razorpay_payment_id must be unique (when not null)."""
        RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id='order_1',
            razorpay_payment_id='pay_unique123',
            amount=4900,
        )
        with self.assertRaises(Exception):
            RazorpayPayment.objects.create(
                user=self.user,
                payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
                razorpay_order_id='order_2',
                razorpay_payment_id='pay_unique123',
                amount=4900,
            )


class CreateSubscriptionViewTests(PaymentTestMixin, TestCase):
    """Tests for POST /api/auth/payments/subscribe/"""

    @patch('accounts.razorpay_service._get_client')
    def test_create_subscription_success(self, mock_client):
        mock_rz = MagicMock()
        mock_rz.subscription.create.return_value = {
            'id': 'sub_test_new',
            'short_url': 'https://rzp.io/test',
            'status': 'created',
        }
        mock_client.return_value = mock_rz

        resp = self.client.post('/api/v1/auth/payments/subscribe/', {
            'plan_slug': 'pro',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['subscription_id'], 'sub_test_new')
        self.assertIn('key_id', resp.data)
        self.assertEqual(resp.data['amount'], 49900)

        # Check local records created
        self.assertTrue(RazorpaySubscription.objects.filter(
            user=self.user, razorpay_subscription_id='sub_test_new',
        ).exists())
        self.assertTrue(RazorpayPayment.objects.filter(
            user=self.user, razorpay_subscription_id='sub_test_new',
        ).exists())

    def test_create_subscription_free_plan_rejected(self):
        resp = self.client.post('/api/v1/auth/payments/subscribe/', {
            'plan_slug': 'free',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('free plan', resp.data['detail'].lower())

    def test_create_subscription_invalid_plan(self):
        resp = self.client.post('/api/v1/auth/payments/subscribe/', {
            'plan_slug': 'nonexistent',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_subscription_no_plan_slug(self):
        resp = self.client.post('/api/v1/auth/payments/subscribe/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('accounts.razorpay_service._get_client')
    def test_create_subscription_duplicate_rejected(self, mock_client):
        """Cannot create a second subscription while one is active."""
        RazorpaySubscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            razorpay_subscription_id='sub_existing',
            razorpay_plan_id='plan_pro_monthly',
            status=RazorpaySubscription.STATUS_ACTIVE,
        )

        resp = self.client.post('/api/v1/auth/payments/subscribe/', {
            'plan_slug': 'pro',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already have', resp.data['detail'].lower())

    def test_create_subscription_unauthenticated(self):
        self.client.credentials()  # Remove auth
        resp = self.client.post('/api/v1/auth/payments/subscribe/', {
            'plan_slug': 'pro',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class VerifySubscriptionViewTests(PaymentTestMixin, TestCase):
    """Tests for POST /api/auth/payments/subscribe/verify/"""

    def setUp(self):
        super().setUp()
        # Pre-create subscription and payment records
        self.subscription = RazorpaySubscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            razorpay_subscription_id='sub_verify_test',
            razorpay_plan_id='plan_pro_monthly',
            status=RazorpaySubscription.STATUS_CREATED,
        )
        self.payment = RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_SUBSCRIPTION,
            razorpay_subscription_id='sub_verify_test',
            amount=49900,
            status=RazorpayPayment.STATUS_CREATED,
        )

    def test_verify_subscription_success(self):
        payment_id = 'pay_sub_test123'
        sub_id = 'sub_verify_test'
        sig = self._make_signature(f'{payment_id}|{sub_id}')

        resp = self.client.post('/api/v1/auth/payments/subscribe/verify/', {
            'razorpay_subscription_id': sub_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'activated')

        # Check subscription is now active
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, 'active')

        # Check user plan was upgraded
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.plan.slug, 'pro')

    def test_verify_subscription_invalid_signature(self):
        resp = self.client.post('/api/v1/auth/payments/subscribe/verify/', {
            'razorpay_subscription_id': 'sub_verify_test',
            'razorpay_payment_id': 'pay_fake',
            'razorpay_signature': 'invalid_signature',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('signature', resp.data['detail'].lower())

    def test_verify_subscription_missing_fields(self):
        resp = self.client.post('/api/v1/auth/payments/subscribe/verify/', {
            'razorpay_subscription_id': 'sub_verify_test',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_subscription_idempotent(self):
        """Verifying the same payment twice should not double-provision."""
        payment_id = 'pay_idempotent_sub'
        sub_id = 'sub_verify_test'
        sig = self._make_signature(f'{payment_id}|{sub_id}')

        # First verify
        resp1 = self.client.post('/api/v1/auth/payments/subscribe/verify/', {
            'razorpay_subscription_id': sub_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig,
        }, format='json')
        self.assertEqual(resp1.data['status'], 'activated')

        # Second verify — should be idempotent
        resp2 = self.client.post('/api/v1/auth/payments/subscribe/verify/', {
            'razorpay_subscription_id': sub_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig,
        }, format='json')
        self.assertEqual(resp2.data['status'], 'already_processed')


class CancelSubscriptionViewTests(PaymentTestMixin, TestCase):
    """Tests for POST /api/auth/payments/subscribe/cancel/"""

    @patch('accounts.razorpay_service._get_client')
    def test_cancel_subscription_success(self, mock_client):
        mock_rz = MagicMock()
        mock_rz.subscription.cancel.return_value = {'status': 'cancelled'}
        mock_client.return_value = mock_rz

        from django.utils import timezone
        RazorpaySubscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            razorpay_subscription_id='sub_cancel_test',
            razorpay_plan_id='plan_pro_monthly',
            status=RazorpaySubscription.STATUS_ACTIVE,
            current_end=timezone.now() + timezone.timedelta(days=15),
        )

        # Upgrade user to pro first
        self.user.profile.plan = self.pro_plan
        self.user.profile.plan_valid_until = timezone.now() + timezone.timedelta(days=15)
        self.user.profile.save()

        resp = self.client.post('/api/v1/auth/payments/subscribe/cancel/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'cancelled')

    def test_cancel_subscription_no_active(self):
        resp = self.client.post('/api/v1/auth/payments/subscribe/cancel/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('no active', resp.data['detail'].lower())


class SubscriptionStatusViewTests(PaymentTestMixin, TestCase):
    """Tests for GET /api/auth/payments/subscribe/status/"""

    def test_status_no_subscription(self):
        resp = self.client.get('/api/v1/auth/payments/subscribe/status/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['has_subscription'])
        self.assertFalse(resp.data['is_active'])

    def test_status_with_subscription(self):
        RazorpaySubscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            razorpay_subscription_id='sub_status_test',
            razorpay_plan_id='plan_pro_monthly',
            status=RazorpaySubscription.STATUS_ACTIVE,
        )
        resp = self.client.get('/api/v1/auth/payments/subscribe/status/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['has_subscription'])
        self.assertTrue(resp.data['is_active'])
        self.assertEqual(resp.data['plan'], 'pro')


class CreateTopUpOrderViewTests(PaymentTestMixin, TestCase):
    """Tests for POST /api/auth/payments/topup/"""

    @patch('accounts.razorpay_service._get_client')
    def test_create_topup_order_success(self, mock_client):
        mock_rz = MagicMock()
        mock_rz.order.create.return_value = {
            'id': 'order_topup_test',
            'amount': 9800,
            'currency': 'INR',
        }
        mock_client.return_value = mock_rz

        # Upgrade user to Pro first (only Pro can topup)
        self.user.profile.plan = self.pro_plan
        self.user.profile.save()

        resp = self.client.post('/api/v1/auth/payments/topup/', {
            'quantity': 2,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['order_id'], 'order_topup_test')
        self.assertEqual(resp.data['quantity'], 2)
        self.assertEqual(resp.data['credits'], 10)  # 2 × 5
        self.assertEqual(resp.data['total_price'], 98.0)  # 2 × 49

    def test_topup_free_plan_rejected(self):
        """Free plan users cannot top up."""
        resp = self.client.post('/api/v1/auth/payments/topup/', {
            'quantity': 1,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('top-up', resp.data['detail'].lower())

    def test_topup_invalid_quantity(self):
        self.user.profile.plan = self.pro_plan
        self.user.profile.save()

        resp = self.client.post('/api/v1/auth/payments/topup/', {
            'quantity': 0,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_topup_default_quantity(self):
        """Default quantity should be 1."""
        self.user.profile.plan = self.pro_plan
        self.user.profile.save()

        with patch('accounts.razorpay_service._get_client') as mock_client:
            mock_rz = MagicMock()
            mock_rz.order.create.return_value = {
                'id': 'order_default',
                'amount': 4900,
                'currency': 'INR',
            }
            mock_client.return_value = mock_rz

            resp = self.client.post('/api/v1/auth/payments/topup/', {}, format='json')
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            self.assertEqual(resp.data['quantity'], 1)
            self.assertEqual(resp.data['credits'], 5)


class VerifyTopUpViewTests(PaymentTestMixin, TestCase):
    """Tests for POST /api/auth/payments/topup/verify/"""

    def setUp(self):
        super().setUp()
        # Upgrade user to Pro
        self.user.profile.plan = self.pro_plan
        self.user.profile.save()

        # Pre-create payment record
        self.payment = RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id='order_verify_topup',
            amount=4900,
            status=RazorpayPayment.STATUS_CREATED,
            notes={'quantity': 1, 'credits': 5, 'plan_slug': 'pro'},
        )

    def test_verify_topup_success(self):
        payment_id = 'pay_topup_test'
        order_id = 'order_verify_topup'
        sig = self._make_signature(f'{order_id}|{payment_id}')

        wallet_before = Wallet.objects.get(user=self.user).balance

        resp = self.client.post('/api/v1/auth/payments/topup/verify/', {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'success')
        self.assertEqual(resp.data['credits_added'], 5)

        # Check wallet was credited
        wallet_after = Wallet.objects.get(user=self.user).balance
        self.assertEqual(wallet_after, wallet_before + 5)

        # Check transaction recorded
        tx = WalletTransaction.objects.filter(
            wallet__user=self.user,
            transaction_type=WalletTransaction.TYPE_TOPUP,
            reference_id=payment_id,
        ).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, 5)

    def test_verify_topup_invalid_signature(self):
        resp = self.client.post('/api/v1/auth/payments/topup/verify/', {
            'razorpay_order_id': 'order_verify_topup',
            'razorpay_payment_id': 'pay_fake',
            'razorpay_signature': 'bad_sig',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_topup_idempotent(self):
        """Double-verify should not double-credit."""
        payment_id = 'pay_topup_idemp'
        order_id = 'order_verify_topup'
        sig = self._make_signature(f'{order_id}|{payment_id}')

        resp1 = self.client.post('/api/v1/auth/payments/topup/verify/', {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig,
        }, format='json')
        self.assertEqual(resp1.data['status'], 'success')

        balance_after_first = resp1.data['balance']

        resp2 = self.client.post('/api/v1/auth/payments/topup/verify/', {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': sig,
        }, format='json')
        self.assertEqual(resp2.data['status'], 'already_processed')

        # Balance should not have changed
        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, balance_after_first)


class WebhookViewTests(PaymentTestMixin, TestCase):
    """Tests for POST /api/auth/payments/webhook/"""

    def _post_webhook(self, event, payload, signature=None):
        """Helper to POST a webhook event."""
        body = json.dumps({'event': event, 'payload': payload})
        body_bytes = body.encode()
        if signature is None:
            signature = self._make_webhook_signature(body_bytes)

        return self.client.post(
            '/api/v1/auth/payments/webhook/',
            body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )

    def test_webhook_missing_signature(self):
        """Webhook without signature should be rejected."""
        # Don't use credentials for webhook
        self.client.credentials()  # Clear auth header

        resp = self.client.post(
            '/api/v1/auth/payments/webhook/',
            json.dumps({'event': 'test', 'payload': {}}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_webhook_invalid_signature(self):
        self.client.credentials()

        resp = self.client.post(
            '/api/v1/auth/payments/webhook/',
            json.dumps({'event': 'test', 'payload': {}}),
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='invalid',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_webhook_payment_captured_topup(self):
        """payment.captured webhook should fulfill a top-up."""
        self.client.credentials()

        # Pre-create payment record
        self.user.profile.plan = self.pro_plan
        self.user.profile.save()

        RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id='order_wh_topup',
            amount=4900,
            status=RazorpayPayment.STATUS_CREATED,
            notes={'quantity': 1, 'credits': 5, 'plan_slug': 'pro'},
        )

        wallet_before = Wallet.objects.get(user=self.user).balance

        resp = self._post_webhook('payment.captured', {
            'payment': {
                'entity': {
                    'id': 'pay_wh_test',
                    'order_id': 'order_wh_topup',
                    'notes': {
                        'user_id': str(self.user.id),
                        'type': 'topup',
                    },
                },
            },
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Credits should be added
        wallet_after = Wallet.objects.get(user=self.user).balance
        self.assertEqual(wallet_after, wallet_before + 5)

    def test_webhook_unhandled_event(self):
        """Unknown events should be acknowledged but ignored."""
        self.client.credentials()

        resp = self._post_webhook('some.unknown.event', {})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'ignored')

    def test_webhook_subscription_cancelled(self):
        """subscription.cancelled should update subscription status."""
        self.client.credentials()

        RazorpaySubscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            razorpay_subscription_id='sub_wh_cancel',
            razorpay_plan_id='plan_pro_monthly',
            status=RazorpaySubscription.STATUS_ACTIVE,
        )

        resp = self._post_webhook('subscription.cancelled', {
            'subscription': {
                'entity': {
                    'id': 'sub_wh_cancel',
                    'status': 'cancelled',
                    'notes': {'user_id': str(self.user.id)},
                },
            },
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        sub = RazorpaySubscription.objects.get(razorpay_subscription_id='sub_wh_cancel')
        self.assertEqual(sub.status, 'cancelled')

    def test_webhook_payment_failed(self):
        """payment.failed webhook should mark payment as failed."""
        self.client.credentials()

        RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id='order_fail',
            amount=4900,
            status=RazorpayPayment.STATUS_CREATED,
        )

        resp = self._post_webhook('payment.failed', {
            'payment': {
                'entity': {
                    'id': 'pay_failed_1',
                    'order_id': 'order_fail',
                },
            },
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        payment = RazorpayPayment.objects.get(razorpay_order_id='order_fail')
        self.assertEqual(payment.status, 'failed')


class PaymentHistoryViewTests(PaymentTestMixin, TestCase):
    """Tests for GET /api/auth/payments/history/"""

    def test_empty_history(self):
        resp = self.client.get('/api/v1/auth/payments/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)
        self.assertEqual(resp.data['results'], [])

    def test_history_with_payments(self):
        RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id='order_hist_1',
            amount=4900,
            status=RazorpayPayment.STATUS_CAPTURED,
        )
        RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_SUBSCRIPTION,
            razorpay_subscription_id='sub_hist_1',
            amount=49900,
            status=RazorpayPayment.STATUS_CAPTURED,
        )

        resp = self.client.get('/api/v1/auth/payments/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 2)

    def test_history_unauthenticated(self):
        self.client.credentials()
        resp = self.client.get('/api/v1/auth/payments/history/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_history_pagination(self):
        for i in range(25):
            RazorpayPayment.objects.create(
                user=self.user,
                payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
                razorpay_order_id=f'order_lim_{i}',
                amount=4900,
            )

        resp = self.client.get('/api/v1/auth/payments/history/')
        self.assertEqual(resp.data['count'], 25)
        self.assertEqual(len(resp.data['results']), 20)  # page_size=20
        self.assertIsNotNone(resp.data['next'])

        # Page 2
        resp2 = self.client.get('/api/v1/auth/payments/history/?page=2')
        self.assertEqual(len(resp2.data['results']), 5)

    def test_history_isolation(self):
        """User should only see their own payments."""
        other_user = User.objects.create_user(
            username='other', email='other@test.com', password='StrongPass123!'
        )
        RazorpayPayment.objects.create(
            user=other_user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id='order_other',
            amount=4900,
        )

        resp = self.client.get('/api/v1/auth/payments/history/')
        self.assertEqual(resp.data['count'], 0)
