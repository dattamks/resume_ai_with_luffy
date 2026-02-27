import logging
from datetime import datetime

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken, OutstandingToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from .serializers import (
    RegisterSerializer,
    UserSerializer,
    UpdateUserSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    NotificationPreferenceSerializer,
    CustomTokenObtainPairSerializer,
    PlanSerializer,
    WalletSerializer,
    WalletTransactionSerializer,
)
from .email_utils import send_templated_email
from .throttles import AuthEndpointThrottle

logger = logging.getLogger('accounts')


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)

            # Send welcome email (best-effort, don't block registration)
            send_templated_email(
                slug='welcome',
                recipient=user.email,
                context={'username': user.username},
                fail_silently=True,
            )

            return Response({
                'user': UserSerializer(user).data,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [AuthEndpointThrottle]


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'detail': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'detail': 'Successfully logged out.'}, status=status.HTTP_200_OK)
        except TokenError:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)


class MeView(APIView):
    """
    GET    /api/auth/me/  — Return current user profile.
    PUT    /api/auth/me/  — Update username and/or email.
    DELETE /api/auth/me/  — Permanently delete account and all associated data.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Ensure profile exists (for users created before migration)
        from .models import UserProfile, NotificationPreference
        UserProfile.objects.get_or_create(user=request.user)
        NotificationPreference.objects.get_or_create(user=request.user)
        return Response(UserSerializer(request.user).data)

    def put(self, request):
        serializer = UpdateUserSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(UserSerializer(request.user).data)

    def delete(self, request):
        from .serializers import DeleteAccountSerializer
        serializer = DeleteAccountSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        logger.warning('Account deletion requested for user=%s (id=%s)', user.username, user.id)

        # Cancel any active Razorpay subscription (stop billing on Razorpay side)
        try:
            from .razorpay_service import cancel_subscription
            cancel_subscription(user)
            logger.info('Razorpay subscription cancelled during account deletion: user=%s', user.username)
        except (ValueError, Exception) as e:
            # User may not have a subscription, or Razorpay API may fail — log but don't block deletion
            logger.info('No active subscription to cancel (or API error) during account deletion: user=%s err=%s',
                        user.username, str(e))

        # Blacklist all outstanding tokens for this user
        try:
            tokens = OutstandingToken.objects.filter(user=user)
            for token in tokens:
                BlacklistedToken.objects.get_or_create(token=token)
        except Exception:
            pass  # best-effort; user is being deleted anyway

        # Hard-delete user (cascades to Resume, ScrapeResult, LLMResponse, analyses via FK)
        # Note: no need to soft-delete analyses separately — user.delete() cascades.
        user.delete()

        logger.info('Account deleted: username=%s', user.username)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
    """
    POST /api/auth/change-password/
    Change the authenticated user's password.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])

        # Invalidate all existing JWT sessions so the old tokens can't be reused
        try:
            tokens = OutstandingToken.objects.filter(user=request.user)
            for token in tokens:
                BlacklistedToken.objects.get_or_create(token=token)
        except Exception:
            pass  # best-effort

        logger.info('Password changed for user=%s', request.user.username)

        # Send confirmation email (best-effort)
        send_templated_email(
            slug='password-changed',
            recipient=request.user.email,
            context={
                'username': request.user.username,
                'changed_at': timezone.now().strftime('%B %d, %Y at %I:%M %p'),
            },
            fail_silently=True,
        )

        return Response({'detail': 'Password updated successfully.'})


class NotificationPreferenceView(APIView):
    """
    GET  /api/auth/notifications/  — Return current notification preferences.
    PUT  /api/auth/notifications/  — Update notification preferences (partial).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import NotificationPreference
        prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return Response(NotificationPreferenceSerializer(prefs).data)

    def put(self, request):
        from .models import NotificationPreference
        prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(prefs, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/
    Sends a password reset email with uid + token.
    Always returns 200 regardless of whether the email exists (security).
    """
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't reveal whether the email exists — always return success
            logger.info('Password reset requested for non-existent email=%s', email)
            return Response({'detail': 'If an account with that email exists, a reset link has been sent.'})

        # Generate token
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # Build reset URL (frontend handles the actual reset form)
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        reset_link = f'{frontend_url}/reset-password?uid={uid}&token={token}'

        # Send templated email
        try:
            send_templated_email(
                slug='password-reset',
                recipient=user.email,
                context={
                    'username': user.username,
                    'reset_link': reset_link,
                    'expiry_hours': str(settings.PASSWORD_RESET_TIMEOUT // 3600),
                },
            )
            logger.info('Password reset email sent to user=%s', user.username)
        except Exception as exc:
            logger.error('Failed to send password reset email to user=%s: %s', user.username, exc)
            return Response(
                {'detail': 'Failed to send reset email. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({'detail': 'If an account with that email exists, a reset link has been sent.'})


class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/
    Validates uid + token from the reset email and sets a new password.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()
        logger.info('Password reset completed for user=%s', user.username)

        return Response({'detail': 'Password has been reset successfully. You can now log in.'})


class WalletView(APIView):
    """
    GET /api/auth/wallet/
    Return wallet balance, plan credits info, and top-up availability.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Wallet
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        profile = request.user.profile
        plan = profile.plan

        return Response({
            'balance': wallet.balance,
            'updated_at': wallet.updated_at,
            'plan_name': plan.name if plan else 'Free',
            'credits_per_month': plan.credits_per_month if plan else 0,
            'can_topup': bool(plan and plan.topup_credits_per_pack > 0 and profile.pending_plan is None),
            'topup_credits_per_pack': plan.topup_credits_per_pack if plan else 0,
            'topup_price': float(plan.topup_price) if plan else 0,
            'plan_valid_until': profile.plan_valid_until,
            'pending_downgrade': profile.pending_plan.slug if profile.pending_plan else None,
        })


class WalletTransactionListView(APIView):
    """
    GET /api/auth/wallet/transactions/
    Paginated transaction history for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Wallet, WalletTransaction
        from rest_framework.pagination import PageNumberPagination

        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        transactions = WalletTransaction.objects.filter(wallet=wallet)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(transactions, request)
        serializer = WalletTransactionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class WalletTopUpView(APIView):
    """
    POST /api/auth/wallet/topup/
    Buy credit packs. Pro users only.
    Body: { "quantity": 3 }  (default: 1)

    DEPRECATED: This endpoint now redirects to the Razorpay payment flow.
    Use POST /api/auth/payments/topup/ to create a paid order instead.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response(
            {
                'detail': 'Credit top-ups require payment. '
                           'Use POST /api/auth/payments/topup/ instead.',
                'payment_url': '/api/auth/payments/topup/',
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )


class PlanListView(APIView):
    """
    GET /api/auth/plans/
    List all active plans. Public endpoint.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from .models import Plan
        plans = Plan.objects.filter(is_active=True)
        return Response(PlanSerializer(plans, many=True).data)


class PlanSubscribeView(APIView):
    """
    POST /api/auth/plans/subscribe/
    Switch to a different plan.
    Body: { "plan_slug": "pro" }

    NOTE: Upgrading to a paid plan requires payment via /api/auth/payments/subscribe/.
    This endpoint only allows downgrade to free plan (or same-plan no-op).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .services import subscribe_plan
        from .models import Plan

        plan_slug = request.data.get('plan_slug')
        if not plan_slug:
            return Response(
                {'detail': 'plan_slug is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Block direct upgrade to paid plans — must go through Razorpay flow
        try:
            target_plan = Plan.objects.get(slug=plan_slug, is_active=True)
        except Plan.DoesNotExist:
            return Response(
                {'detail': f'Plan "{plan_slug}" not found or inactive.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if target_plan.price > 0:
            return Response(
                {
                    'detail': 'Upgrading to a paid plan requires payment. '
                              'Use POST /api/auth/payments/subscribe/ instead.',
                    'payment_url': '/api/auth/payments/subscribe/',
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            result = subscribe_plan(request.user, plan_slug)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)
