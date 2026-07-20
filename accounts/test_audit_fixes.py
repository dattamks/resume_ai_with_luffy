"""
Regression tests for the payment / credit / auth fixes from the audit.

Covered:
- subscription.charged recurring grant + per-cycle & event-id idempotency
- first-cycle grant suppressed (no double with the activation upgrade bonus)
- webhook handler failure → non-2xx, event NOT marked processed (retriable)
- refund_credits idempotency (single credit for repeated refunds)
- add_credits negative floor (balance never goes below 0)
- LogoutView refresh-token ownership
- top-up fulfilment cross-account guard (IDOR)
"""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import (
    Plan, Wallet, WalletTransaction, RazorpaySubscription, RazorpayPayment,
    WebhookEvent,
)
from accounts.services import refund_credits, add_credits
from accounts.test_payments import PaymentTestMixin


class SubscriptionChargedWebhookTests(PaymentTestMixin, TestCase):
    """subscription.charged is the recurring-billing money path."""

    def setUp(self):
        super().setUp()
        self.client.credentials()  # webhook is unauthenticated
        self.user.profile.plan = self.pro_plan
        self.user.profile.save()
        self.sub = RazorpaySubscription.objects.create(
            user=self.user,
            plan=self.pro_plan,
            razorpay_subscription_id='sub_recurring',
            status=RazorpaySubscription.STATUS_ACTIVE,
            current_start=timezone.now(),
            current_end=timezone.now() + timezone.timedelta(days=30),
        )

    def _charged_payload(self, payment_id='', paid_count=2):
        entity = {
            'id': 'sub_recurring',
            'paid_count': paid_count,
            'notes': {'user_id': str(self.user.id)},
        }
        if payment_id:
            entity['payment_id'] = payment_id
        return {'subscription': {'entity': entity}}

    def _post(self, payload, event_id=None):
        body = json.dumps({'event': 'subscription.charged', 'payload': payload})
        body_bytes = body.encode()
        extra = {'HTTP_X_RAZORPAY_SIGNATURE': self._make_webhook_signature(body_bytes)}
        if event_id:
            extra['HTTP_X_RAZORPAY_EVENT_ID'] = event_id
        return self.client.post(
            '/api/v1/auth/payments/webhook/', body,
            content_type='application/json', **extra,
        )

    def _plan_credits(self):
        # Count only the recurring monthly grants (exclude the initial
        # free-plan wallet credit, which is also a PLAN_CREDIT transaction).
        return WalletTransaction.objects.filter(
            wallet__user=self.user,
            transaction_type=WalletTransaction.TYPE_PLAN_CREDIT,
            description__startswith='Monthly',
        ).count()

    def test_handler_error_returns_non_2xx_and_allows_retry(self):
        with patch('accounts.razorpay_service.handle_webhook_event',
                   return_value={'status': 'error', 'error': 'boom'}):
            resp = self._post(self._charged_payload(payment_id='p', paid_count=2),
                              event_id='evt_fail')
        self.assertGreaterEqual(resp.status_code, 500)
        # Event must NOT be recorded, so Razorpay's retry is accepted later.
        self.assertFalse(WebhookEvent.objects.filter(event_id='evt_fail').exists())

    def test_recurring_charge_grants_credits(self):
        resp = self._post(self._charged_payload(payment_id='pay_c2', paid_count=2),
                          event_id='evt_cycle2')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(self._plan_credits(), 1)

    def test_duplicate_delivery_same_event_id_is_idempotent(self):
        p = self._charged_payload(payment_id='pay_c2', paid_count=2)
        self._post(p, event_id='evt_cycle2')
        # Same X-Razorpay-Event-Id header → duplicate, no second grant.
        resp = self._post(p, event_id='evt_cycle2')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data.get('status'), 'duplicate')
        self.assertEqual(self._plan_credits(), 1)

    def test_redelivery_without_header_still_idempotent_per_cycle(self):
        # No event-id header, no payment_id → dedup falls back to paid_count via
        # the grant idempotency key. Two deliveries of the same cycle grant once.
        self._post(self._charged_payload(paid_count=3), event_id=None)
        self._post(self._charged_payload(paid_count=3), event_id=None)
        self.assertEqual(self._plan_credits(), 1)

    def test_distinct_cycles_are_not_collapsed(self):
        # The old bug collapsed every cycle onto the subscription id. Distinct
        # cycles (distinct event ids) must both grant.
        self._post(self._charged_payload(payment_id='pay_c2', paid_count=2), event_id='evt_c2')
        self._post(self._charged_payload(payment_id='pay_c3', paid_count=3), event_id='evt_c3')
        self.assertEqual(self._plan_credits(), 2)

    def test_first_cycle_grant_suppressed(self):
        # Cycle 1 coincides with activation (upgrade bonus), so no plan grant.
        resp = self._post(self._charged_payload(payment_id='pay_c1', paid_count=1),
                          event_id='evt_c1')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(self._plan_credits(), 0)

    def test_charge_after_cancel_does_not_reactivate_or_grant(self):
        self.sub.status = RazorpaySubscription.STATUS_CANCELLED
        self.sub.save(update_fields=['status'])
        resp = self._post(self._charged_payload(payment_id='pay_late', paid_count=2),
                          event_id='evt_late')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data.get('status'), 'ignored')
        self.assertEqual(self._plan_credits(), 0)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, RazorpaySubscription.STATUS_CANCELLED)


class RefundIdempotencyTests(PaymentTestMixin, TestCase):
    def test_double_refund_credits_once(self):
        from accounts.models import CreditCost
        CreditCost.objects.update_or_create(action='resume_analysis', defaults={'cost': 1})
        wallet = Wallet.objects.get(user=self.user)
        start = wallet.balance
        refund_credits(self.user, 'resume_analysis', reference_id='an-1')
        refund_credits(self.user, 'resume_analysis', reference_id='an-1')  # dup
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, start + 1)
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=wallet, transaction_type=WalletTransaction.TYPE_REFUND,
            ).count(), 1,
        )


class AddCreditsFloorTests(PaymentTestMixin, TestCase):
    def test_large_negative_adjustment_floors_at_zero(self):
        wallet = Wallet.objects.get(user=self.user)
        add_credits(self.user, -99999, WalletTransaction.TYPE_ADMIN_ADJUSTMENT)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 0)


class LogoutOwnershipTests(PaymentTestMixin, TestCase):
    def test_cannot_blacklist_another_users_token(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        other = User.objects.create_user(username='victim', password='StrongPass123!')
        others_refresh = str(RefreshToken.for_user(other))
        # self.user is authenticated (PaymentTestMixin logs them in).
        resp = self.client.post('/api/v1/auth/logout/', {'refresh': others_refresh}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TopupOwnershipTests(PaymentTestMixin, TestCase):
    def test_frontend_fulfil_rejects_other_users_order(self):
        from accounts.razorpay_service import _fulfill_topup
        attacker = User.objects.create_user(username='attacker', password='StrongPass123!')
        # Order belongs to self.user, attacker tries to fulfil it (frontend path).
        RazorpayPayment.objects.create(
            user=self.user,
            payment_type=RazorpayPayment.PAYMENT_TYPE_TOPUP,
            razorpay_order_id='order_victim',
            amount=4900, status=RazorpayPayment.STATUS_CREATED,
            notes={'quantity': 1, 'credits': 5},
        )
        with self.assertRaises(ValueError):
            _fulfill_topup(attacker, 'order_victim', 'pay_x', via_webhook=False)
