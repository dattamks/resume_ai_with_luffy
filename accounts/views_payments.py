"""
Razorpay payment views.

Endpoints:
- POST /api/v1/payments/subscribe/            — Create subscription (Pro plan)
- POST /api/v1/payments/subscribe/verify/     — Verify subscription payment
- POST /api/v1/payments/subscribe/cancel/     — Cancel subscription
- GET  /api/v1/payments/subscribe/status/     — Get subscription status
- POST /api/v1/payments/topup/                — Create top-up order
- POST /api/v1/payments/topup/verify/         — Verify top-up payment
- POST /api/v1/payments/webhook/              — Razorpay webhook (no auth)
- GET  /api/v1/payments/history/              — Payment history
"""
import json
import logging

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny

from .serializers import (
    CreateSubscriptionSerializer,
    VerifySubscriptionSerializer,
    CreateTopUpOrderSerializer,
    VerifyTopUpSerializer,
)
from .throttles import PaymentThrottle
from .permissions import IsEmailVerified

logger = logging.getLogger('accounts')


class _WebhookHandlerError(Exception):
    """Internal: raised to roll back a webhook that a handler could not process."""

    def __init__(self, result):
        self.result = result
        super().__init__(str(result))


class CreateSubscriptionView(APIView):
    """
    POST /api/v1/payments/subscribe/
    Create a Razorpay subscription for the Pro plan.

    Request:  { "plan_slug": "pro" }
    Response: { "subscription_id", "key_id", "amount", "currency", ... }
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request):
        serializer = CreateSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from .razorpay_service import create_subscription

        try:
            result = create_subscription(request.user, serializer.validated_data['plan_slug'])
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_201_CREATED)


class VerifySubscriptionView(APIView):
    """
    POST /api/v1/payments/subscribe/verify/
    Verify subscription payment after Razorpay checkout.

    Request: {
        "razorpay_subscription_id": "sub_xxx",
        "razorpay_payment_id": "pay_xxx",
        "razorpay_signature": "hex_signature"
    }
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request):
        serializer = VerifySubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from .razorpay_service import verify_subscription_payment

        try:
            result = verify_subscription_payment(
                user=request.user,
                razorpay_subscription_id=serializer.validated_data['razorpay_subscription_id'],
                razorpay_payment_id=serializer.validated_data['razorpay_payment_id'],
                razorpay_signature=serializer.validated_data['razorpay_signature'],
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


class CancelSubscriptionView(APIView):
    """
    POST /api/v1/payments/subscribe/cancel/
    Cancel the user's active subscription (at end of billing cycle).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request):
        from .razorpay_service import cancel_subscription

        try:
            result = cancel_subscription(request.user)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


class SubscriptionStatusView(APIView):
    """
    GET /api/v1/payments/subscribe/status/
    Get the current subscription status.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def get(self, request):
        from .razorpay_service import get_subscription_status

        result = get_subscription_status(request.user)
        return Response(result)


class CreateTopUpOrderView(APIView):
    """
    POST /api/v1/payments/topup/
    Create a Razorpay order for a credit top-up.

    Request:  { "quantity": 2 }  (default: 1)
    Response: { "order_id", "key_id", "amount", "currency", ... }
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]
    throttle_classes = [PaymentThrottle]

    def post(self, request):
        serializer = CreateTopUpOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from .razorpay_service import create_topup_order

        try:
            result = create_topup_order(request.user, serializer.validated_data.get('quantity', 1))
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_201_CREATED)


class VerifyTopUpView(APIView):
    """
    POST /api/v1/payments/topup/verify/
    Verify a top-up payment after Razorpay checkout.

    Request: {
        "razorpay_order_id": "order_xxx",
        "razorpay_payment_id": "pay_xxx",
        "razorpay_signature": "hex_signature"
    }
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request):
        serializer = VerifyTopUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from .razorpay_service import verify_topup_payment

        try:
            result = verify_topup_payment(
                user=request.user,
                razorpay_order_id=serializer.validated_data['razorpay_order_id'],
                razorpay_payment_id=serializer.validated_data['razorpay_payment_id'],
                razorpay_signature=serializer.validated_data['razorpay_signature'],
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


class RazorpayWebhookView(APIView):
    """
    POST /api/v1/payments/webhook/
    Razorpay webhook endpoint. No JWT auth — uses signature verification.
    Must be idempotent (same event may be delivered multiple times).
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # No JWT — webhook uses signature auth

    def post(self, request):
        from .razorpay_service import verify_webhook_signature, handle_webhook_event

        # Get the raw body and signature header
        signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE', '')

        if not signature:
            logger.warning('Webhook request missing X-Razorpay-Signature header')
            return Response(
                {'detail': 'Missing signature header.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify webhook signature
        raw_body = request.body
        if not verify_webhook_signature(raw_body, signature):
            logger.warning('Webhook signature verification failed')
            return Response(
                {'detail': 'Invalid webhook signature.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Parse event
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return Response(
                {'detail': 'Invalid JSON body.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = body.get('event', '')
        payload = body.get('payload', {})

        # Razorpay's unique delivery ID is sent in the X-Razorpay-Event-Id
        # HEADER (not the JSON body). Prefer it for dedup so that recurring
        # events like subscription.charged — which reuse the same subscription
        # entity id every billing cycle — are NOT collapsed into one another.
        event_id = (
            request.META.get('HTTP_X_RAZORPAY_EVENT_ID', '')
            or body.get('event_id', '')
            or body.get('id', '')
        )
        if not event_id:
            # Fall back to a per-delivery ID. Prefer the payment entity id
            # (distinct for each subscription charge) over the subscription id
            # (constant across cycles) so renewals aren't treated as duplicates.
            entity_id = (
                payload.get('payment', {}).get('entity', {}).get('id', '')
                or payload.get('subscription', {}).get('entity', {}).get('id', '')
                or 'unknown'
            )
            event_id = f'{event}:{entity_id}'

        from django.db import IntegrityError
        from .models import WebhookEvent

        # ── Replay protection (fast path) ──
        if WebhookEvent.objects.filter(event_id=event_id).exists():
            logger.info('Webhook duplicate skipped: event_id=%s event=%s', event_id, event)
            return Response(
                {'status': 'duplicate', 'event_id': event_id},
                status=status.HTTP_200_OK,
            )

        logger.info('Webhook received: event=%s event_id=%s', event, event_id)

        # Process and record atomically. The event is marked processed ONLY if
        # the handler succeeds; on failure we roll back the WebhookEvent insert
        # and return a non-2xx so Razorpay redelivers (no silently-lost credit
        # grants). Concurrent duplicate deliveries collide on the unique
        # event_id and are treated as duplicates.
        try:
            with transaction.atomic():
                WebhookEvent.objects.create(event_id=event_id, event_type=event)
                result = handle_webhook_event(event, payload)
                if isinstance(result, dict) and result.get('status') == 'error':
                    # Force rollback so the event is not marked processed.
                    raise _WebhookHandlerError(result)
        except IntegrityError:
            logger.info('Webhook duplicate (concurrent) skipped: event_id=%s', event_id)
            return Response(
                {'status': 'duplicate', 'event_id': event_id},
                status=status.HTTP_200_OK,
            )
        except _WebhookHandlerError as exc:
            logger.error('Webhook handler failed, will be retried: event_id=%s result=%s',
                         event_id, exc.result)
            return Response(exc.result, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_200_OK)


class PaymentHistoryView(APIView):
    """
    GET /api/v1/payments/history/
    Returns the user's payment history (paginated).
    Supports ?page= for pagination.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        from .models import RazorpayPayment

        qs = RazorpayPayment.objects.filter(user=request.user).order_by('-created_at')

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)

        payments = []
        for p in page:
            payments.append({
                'id': p.id,
                'payment_type': p.payment_type,
                'razorpay_order_id': p.razorpay_order_id or '',
                'razorpay_payment_id': p.razorpay_payment_id or '',
                'amount': p.amount,
                'amount_display': f'₹{p.amount / 100:.2f}',
                'currency': p.currency,
                'status': p.status,
                'created_at': p.created_at.isoformat(),
            })

        return paginator.get_paginated_response(payments)
