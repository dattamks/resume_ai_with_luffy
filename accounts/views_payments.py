"""
Razorpay payment views.

Endpoints:
- POST /api/payments/subscribe/            — Create subscription (Pro plan)
- POST /api/payments/subscribe/verify/     — Verify subscription payment
- POST /api/payments/subscribe/cancel/     — Cancel subscription
- GET  /api/payments/subscribe/status/     — Get subscription status
- POST /api/payments/topup/                — Create top-up order
- POST /api/payments/topup/verify/         — Verify top-up payment
- POST /api/payments/webhook/              — Razorpay webhook (no auth)
- GET  /api/payments/history/              — Payment history
"""
import json
import logging

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

logger = logging.getLogger('accounts')


class CreateSubscriptionView(APIView):
    """
    POST /api/payments/subscribe/
    Create a Razorpay subscription for the Pro plan.

    Request:  { "plan_slug": "pro" }
    Response: { "subscription_id", "key_id", "amount", "currency", ... }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateSubscriptionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from .razorpay_service import create_subscription

        try:
            result = create_subscription(request.user, serializer.validated_data['plan_slug'])
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_201_CREATED)


class VerifySubscriptionView(APIView):
    """
    POST /api/payments/subscribe/verify/
    Verify subscription payment after Razorpay checkout.

    Request: {
        "razorpay_subscription_id": "sub_xxx",
        "razorpay_payment_id": "pay_xxx",
        "razorpay_signature": "hex_signature"
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = VerifySubscriptionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
    POST /api/payments/subscribe/cancel/
    Cancel the user's active subscription (at end of billing cycle).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .razorpay_service import cancel_subscription

        try:
            result = cancel_subscription(request.user)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


class SubscriptionStatusView(APIView):
    """
    GET /api/payments/subscribe/status/
    Get the current subscription status.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .razorpay_service import get_subscription_status

        result = get_subscription_status(request.user)
        return Response(result)


class CreateTopUpOrderView(APIView):
    """
    POST /api/payments/topup/
    Create a Razorpay order for a credit top-up.

    Request:  { "quantity": 2 }  (default: 1)
    Response: { "order_id", "key_id", "amount", "currency", ... }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateTopUpOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from .razorpay_service import create_topup_order

        try:
            result = create_topup_order(request.user, serializer.validated_data.get('quantity', 1))
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_201_CREATED)


class VerifyTopUpView(APIView):
    """
    POST /api/payments/topup/verify/
    Verify a top-up payment after Razorpay checkout.

    Request: {
        "razorpay_order_id": "order_xxx",
        "razorpay_payment_id": "pay_xxx",
        "razorpay_signature": "hex_signature"
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = VerifyTopUpSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
    POST /api/payments/webhook/
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

        logger.info('Webhook received: event=%s', event)

        # Process the event
        result = handle_webhook_event(event, payload)

        # Always return 200 to acknowledge receipt (Razorpay retries on non-2xx)
        return Response(result, status=status.HTTP_200_OK)


class PaymentHistoryView(APIView):
    """
    GET /api/payments/history/
    Returns the user's payment history.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .razorpay_service import get_payment_history

        limit = request.query_params.get('limit', 20)
        try:
            limit = min(int(limit), 100)
        except (TypeError, ValueError):
            limit = 20

        history = get_payment_history(request.user, limit=limit)
        return Response({'payments': history, 'count': len(history)})
