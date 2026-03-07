import hashlib
import hmac
import json
import logging
import time
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
from rest_framework.throttling import AnonRateThrottle
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
    GoogleAuthSerializer,
    GoogleCompleteSerializer,
)
from .email_utils import send_templated_email
from .models import ConsentLog, EmailVerificationToken
from .throttles import AuthEndpointThrottle

logger = logging.getLogger('accounts')


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        agree_to_terms = serializer.validated_data.get('agree_to_terms', False)
        agree_to_data_usage = serializer.validated_data.get('agree_to_data_usage', False)
        marketing_opt_in = serializer.validated_data.get('marketing_opt_in', False)

        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        # ── Record consent audit trail ──
        ip = self._get_client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', '')
        consent_entries = [
            ConsentLog(
                user=user,
                consent_type=ConsentLog.CONSENT_TERMS_PRIVACY,
                agreed=agree_to_terms,
                ip_address=ip,
                user_agent=ua,
            ),
            ConsentLog(
                user=user,
                consent_type=ConsentLog.CONSENT_DATA_USAGE_AI,
                agreed=agree_to_data_usage,
                ip_address=ip,
                user_agent=ua,
            ),
            ConsentLog(
                user=user,
                consent_type=ConsentLog.CONSENT_MARKETING,
                agreed=marketing_opt_in,
                ip_address=ip,
                user_agent=ua,
            ),
        ]
        ConsentLog.objects.bulk_create(consent_entries)

        # ── Update profile consent flags ──
        profile = user.profile
        profile.agreed_to_terms = agree_to_terms
        profile.agreed_to_data_usage = agree_to_data_usage
        profile.marketing_opt_in = marketing_opt_in
        profile.save(update_fields=['agreed_to_terms', 'agreed_to_data_usage', 'marketing_opt_in'])

        # ── Sync marketing opt-in to newsletter preference ──
        if hasattr(user, 'notification_preferences'):
            prefs = user.notification_preferences
            prefs.newsletters_email = marketing_opt_in
            prefs.save(update_fields=['newsletters_email'])

        # ── Send email verification link ──
        verification_token = EmailVerificationToken.create_for_user(user)
        verify_url = f'{settings.FRONTEND_URL}/verify-email?token={verification_token.token}'
        send_templated_email(
            slug='email-verification',
            recipient=user.email,
            context={
                'username': user.username,
                'verify_url': verify_url,
            },
            fail_silently=True,
        )

        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'email_verification_required': True,
            'message': 'Account created. Please check your email to verify your address.',
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    def _get_client_ip(request):
        """Extract client IP, respecting X-Forwarded-For behind reverse proxies."""
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


class VerifyEmailView(APIView):
    """
    POST /api/v1/auth/verify-email/
    Verify a user's email address using the token sent during registration.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        token_str = request.data.get('token', '').strip()
        if not token_str:
            return Response(
                {'detail': 'Verification token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = EmailVerificationToken.objects.select_related('user__profile').get(token=token_str)
        except EmailVerificationToken.DoesNotExist:
            return Response(
                {'detail': 'Invalid verification token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if token.used_at:
            return Response(
                {'detail': 'This token has already been used.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if token.is_expired:
            return Response(
                {'detail': 'This verification token has expired. Please request a new one.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark token as used and verify user's email
        token.used_at = timezone.now()
        token.save(update_fields=['used_at'])

        profile = token.user.profile
        profile.is_email_verified = True
        profile.save(update_fields=['is_email_verified'])

        # Send welcome email now that email is verified
        send_templated_email(
            slug='welcome',
            recipient=token.user.email,
            context={'username': token.user.username},
            fail_silently=True,
        )

        logger.info('Email verified for user=%s', token.user.username)

        return Response({
            'detail': 'Email verified successfully.',
            'email': token.user.email,
        })


class ResendVerificationEmailView(APIView):
    """
    POST /api/v1/auth/resend-verification/
    Resend the email verification link. Requires authentication.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        profile = getattr(request.user, 'profile', None)
        if profile and profile.is_email_verified:
            return Response(
                {'detail': 'Email is already verified.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Invalidate previous unused tokens
        EmailVerificationToken.objects.filter(
            user=request.user, used_at__isnull=True,
        ).update(used_at=timezone.now())

        # Create new token
        verification_token = EmailVerificationToken.create_for_user(request.user)
        verify_url = f'{settings.FRONTEND_URL}/verify-email?token={verification_token.token}'
        send_templated_email(
            slug='email-verification',
            recipient=request.user.email,
            context={
                'username': request.user.username,
                'verify_url': verify_url,
            },
            fail_silently=False,
        )

        logger.info('Verification email resent for user=%s', request.user.username)

        return Response({
            'detail': 'Verification email sent.',
        })


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            try:
                from analyzer.models import UserActivity
                # Serializer validates credentials; extract user from the token
                from rest_framework_simplejwt.tokens import AccessToken
                token = AccessToken(response.data['access'])
                from django.contrib.auth.models import User
                user = User.objects.get(id=token['user_id'])
                UserActivity.record(user, UserActivity.ACTION_LOGIN)
            except Exception:
                pass  # Non-critical — don't block login
        return response


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


class LogoutAllDevicesView(APIView):
    """
    POST /api/v1/auth/logout-all/
    Invalidate all active JWT sessions for the authenticated user.
    Blacklists all outstanding tokens at once.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        from rest_framework_simplejwt.token_blacklist.models import (
            OutstandingToken, BlacklistedToken,
        )

        outstanding = OutstandingToken.objects.filter(user=request.user)
        count = outstanding.count()

        if count == 0:
            return Response({'detail': 'No active sessions found.', 'invalidated': 0})

        # Bulk blacklist all tokens
        blacklist_entries = [
            BlacklistedToken(token=token)
            for token in outstanding
            if not hasattr(token, 'blacklistedtoken')
        ]
        if blacklist_entries:
            BlacklistedToken.objects.bulk_create(blacklist_entries, ignore_conflicts=True)

        logger.info('Logout all devices: user=%s invalidated=%d tokens', request.user.username, count)

        return Response({
            'detail': 'All sessions invalidated.',
            'invalidated': count,
        })


class MeView(APIView):
    """
    GET    /api/v1/auth/me/  — Return current user profile.
    PUT    /api/v1/auth/me/  — Update username and/or email.
    DELETE /api/v1/auth/me/  — Permanently delete account and all associated data.
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
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)

    def delete(self, request):
        from .serializers import DeleteAccountSerializer
        serializer = DeleteAccountSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        logger.warning('Account deletion requested for user=%s (id=%s)', user.username, user.id)

        # Cancel any active Razorpay subscription (stop billing on Razorpay side)
        try:
            from .razorpay_service import cancel_subscription
            cancel_subscription(user)
            logger.info('Razorpay subscription cancelled during account deletion: user=%s', user.username)
        except Exception as e:
            # User may not have a subscription, or Razorpay API may fail — log but don't block deletion
            logger.info('No active subscription to cancel (or API error) during account deletion: user=%s err=%s',
                        user.username, str(e))

        # Blacklist all outstanding tokens for this user
        try:
            tokens = OutstandingToken.objects.filter(user=user)
            BlacklistedToken.objects.bulk_create(
                [BlacklistedToken(token=t) for t in tokens],
                ignore_conflicts=True,
            )
        except Exception:
            pass  # best-effort; user is being deleted anyway

        # Hard-delete user (cascades to Resume, ScrapeResult, LLMResponse, analyses via FK)
        # Note: no need to soft-delete analyses separately — user.delete() cascades.
        user.delete()

        logger.info('Account deleted: username=%s', user.username)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/change-password/
    Change the authenticated user's password.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)

        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])

        # Invalidate all existing JWT sessions so the old tokens can't be reused
        try:
            tokens = OutstandingToken.objects.filter(user=request.user)
            BlacklistedToken.objects.bulk_create(
                [BlacklistedToken(token=t) for t in tokens],
                ignore_conflicts=True,
            )
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
    GET  /api/v1/auth/notifications/  — Return current notification preferences.
    PUT  /api/v1/auth/notifications/  — Update notification preferences (partial).
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
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ForgotPasswordView(APIView):
    """
    POST /api/v1/auth/forgot-password/
    Sends a password reset email with uid + token.
    Always returns 200 regardless of whether the email exists (security).
    """
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

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
    POST /api/v1/auth/reset-password/
    Validates uid + token from the reset email and sets a new password.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        logger.info('Password reset completed for user=%s', user.username)

        return Response({'detail': 'Password has been reset successfully. You can now log in.'})


class WalletView(APIView):
    """
    GET /api/v1/auth/wallet/
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
    GET /api/v1/auth/wallet/transactions/
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
    POST /api/v1/auth/wallet/topup/
    Buy credit packs. Pro users only.
    Body: { "quantity": 3 }  (default: 1)

    DEPRECATED: This endpoint now redirects to the Razorpay payment flow.
    Use POST /api/v1/auth/payments/topup/ to create a paid order instead.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response(
            {
                'detail': 'Credit top-ups require payment. '
                           'Use POST /api/v1/auth/payments/topup/ instead.',
                'payment_url': '/api/v1/auth/payments/topup/',
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )


class PlanListView(APIView):
    """
    GET /api/v1/auth/plans/
    List all active plans. Public endpoint.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from .models import Plan
        plans = Plan.objects.filter(is_active=True)
        return Response(PlanSerializer(plans, many=True).data)


class PlanSubscribeView(APIView):
    """
    POST /api/v1/auth/plans/subscribe/
    Switch to a different plan.
    Body: { "plan_slug": "pro" }

    NOTE: Upgrading to a paid plan requires payment via /api/v1/auth/payments/subscribe/.
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
                              'Use POST /api/v1/auth/payments/subscribe/ instead.',
                    'payment_url': '/api/v1/auth/payments/subscribe/',
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            result = subscribe_plan(request.user, plan_slug)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


# ── Google OAuth ──────────────────────────────────────────────────────────────

def _sign_temp_token(payload: dict) -> str:
    """Create an HMAC-signed, base64-encoded temporary token."""
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    sig = hmac.new(
        settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256,
    ).hexdigest()
    import base64
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()
    return f'{encoded}.{sig}'


def _verify_temp_token(token: str) -> dict | None:
    """Verify HMAC signature and TTL. Returns payload dict or None."""
    import base64
    parts = token.rsplit('.', 1)
    if len(parts) != 2:
        return None
    encoded, sig = parts
    try:
        raw = base64.urlsafe_b64decode(encoded).decode()
    except Exception:
        return None
    expected_sig = hmac.new(
        settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    # Check TTL
    if payload.get('exp', 0) < time.time():
        return None
    return payload


class GoogleLoginView(APIView):
    """
    POST /api/v1/auth/google/ — Authenticate with Google.

    Receives a Google ID token (from Google Sign-In / One Tap on the frontend),
    verifies it, and either:
      - Returns JWT tokens if the user already exists.
      - Returns a temp_token + needs_registration flag if the user is new.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        id_token_str = serializer.validated_data['token']

        # Verify Google ID token
        google_client_id = settings.GOOGLE_OAUTH2_CLIENT_ID
        if not google_client_id:
            return Response(
                {'detail': 'Google OAuth is not configured on this server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests as google_requests

            idinfo = google_id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                google_client_id,
            )
        except ValueError as e:
            logger.warning('Google token verification failed: %s', e)
            return Response(
                {'detail': 'Invalid or expired Google token.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email = idinfo.get('email', '').lower().strip()
        if not email or not idinfo.get('email_verified'):
            return Response(
                {'detail': 'Google account email is not verified.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        google_sub = idinfo.get('sub', '')
        name = idinfo.get('name', '')
        given_name = idinfo.get('given_name', '')
        family_name = idinfo.get('family_name', '')
        picture = idinfo.get('picture', '')

        # Check if user exists
        try:
            user = User.objects.get(email__iexact=email)

            # ── Smart profile sync (only fill blanks, never overwrite manual edits) ──
            profile = user.profile
            profile_updates = []

            # Always keep google_sub current (identifier, not user-editable)
            if profile.google_sub != google_sub and google_sub:
                profile.google_sub = google_sub
                profile_updates.append('google_sub')

            # Upgrade auth_provider if user originally registered via email
            if profile.auth_provider == 'email':
                profile.auth_provider = 'google'
                profile_updates.append('auth_provider')

            # Only fill avatar if user hasn't set one manually
            if not profile.avatar_url and picture:
                profile.avatar_url = picture
                profile_updates.append('avatar_url')

            if profile_updates:
                profile.save(update_fields=profile_updates)

            # Only fill name fields if currently blank
            user_updates = []
            if not user.first_name and given_name:
                user.first_name = given_name
                user_updates.append('first_name')
            if not user.last_name and family_name:
                user.last_name = family_name
                user_updates.append('last_name')
            if user_updates:
                user.save(update_fields=user_updates)

            # Existing user — issue JWT tokens
            refresh = RefreshToken.for_user(user)
            logger.info('Google login: existing user=%s synced_fields=%s',
                        user.username, profile_updates + user_updates or 'none')

            try:
                from analyzer.models import UserActivity
                UserActivity.record(user, UserActivity.ACTION_LOGIN)
            except Exception:
                pass

            return Response({
                'user': UserSerializer(user).data,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            })
        except User.DoesNotExist:
            pass

        # New user — issue temp token for registration completion
        ttl = getattr(settings, 'GOOGLE_OAUTH2_TEMP_TOKEN_TTL', 600)
        payload = {
            'email': email,
            'google_sub': google_sub,
            'name': name,
            'given_name': given_name,
            'family_name': family_name,
            'picture': picture,
            'exp': int(time.time()) + ttl,
        }
        temp_token = _sign_temp_token(payload)

        logger.info('Google login: new user email=%s — needs registration', email)
        return Response({
            'needs_registration': True,
            'temp_token': temp_token,
            'email': email,
            'name': name,
            'given_name': given_name,
            'family_name': family_name,
            'picture': picture,
        })


class GoogleCompleteView(APIView):
    """
    POST /api/v1/auth/google/complete/ — Complete Google sign-up.

    For new Google users: accepts the temp_token, chosen username, password,
    and consent checkboxes. Creates the account and returns JWT tokens.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = GoogleCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token = serializer.validated_data['temp_token']
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        agree_to_terms = serializer.validated_data['agree_to_terms']
        agree_to_data_usage = serializer.validated_data['agree_to_data_usage']
        marketing_opt_in = serializer.validated_data.get('marketing_opt_in', False)

        # Verify temp token
        payload = _verify_temp_token(temp_token)
        if not payload:
            return Response(
                {'detail': 'Invalid or expired temporary token. Please sign in with Google again.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = payload['email']
        google_sub = payload.get('google_sub', '')
        given_name = payload.get('given_name', '')
        family_name = payload.get('family_name', '')
        picture = payload.get('picture', '')

        # Guard against race condition — email taken between step 1 and step 2
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {'detail': 'An account with this email already exists. Please log in instead.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Create user with Google profile details
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=given_name,
            last_name=family_name,
        )

        # Update profile: consent flags + Google-specific fields
        profile = user.profile
        profile.agreed_to_terms = agree_to_terms
        profile.agreed_to_data_usage = agree_to_data_usage
        profile.marketing_opt_in = marketing_opt_in
        profile.auth_provider = 'google'
        profile.avatar_url = picture
        profile.google_sub = google_sub
        profile.is_email_verified = True
        profile.save(update_fields=[
            'agreed_to_terms', 'agreed_to_data_usage', 'marketing_opt_in',
            'auth_provider', 'avatar_url', 'google_sub', 'is_email_verified',
        ])

        # Sync marketing opt-in to newsletter preference
        if hasattr(user, 'notification_preferences'):
            prefs = user.notification_preferences
            prefs.newsletters_email = marketing_opt_in
            prefs.save(update_fields=['newsletters_email'])

        # Record consent audit trail
        ip = self._get_client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', '')
        ConsentLog.objects.bulk_create([
            ConsentLog(
                user=user,
                consent_type=ConsentLog.CONSENT_TERMS_PRIVACY,
                agreed=agree_to_terms,
                ip_address=ip, user_agent=ua,
            ),
            ConsentLog(
                user=user,
                consent_type=ConsentLog.CONSENT_DATA_USAGE_AI,
                agreed=agree_to_data_usage,
                ip_address=ip, user_agent=ua,
            ),
            ConsentLog(
                user=user,
                consent_type=ConsentLog.CONSENT_MARKETING,
                agreed=marketing_opt_in,
                ip_address=ip, user_agent=ua,
            ),
        ])

        # Issue JWT tokens
        refresh = RefreshToken.for_user(user)

        # Send welcome email
        send_templated_email(
            slug='welcome',
            recipient=user.email,
            context={'username': user.username},
            fail_silently=True,
        )

        logger.info('Google sign-up completed: user=%s email=%s google_sub=%s',
                     user.username, email, google_sub)

        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    def _get_client_ip(request):
        """Extract client IP, respecting X-Forwarded-For behind reverse proxies."""
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


# ── Wallet CSV export ─────────────────────────────────────────────────────────


class WalletTransactionExportView(APIView):
    """
    GET /api/v1/auth/wallet/transactions/export/
    Export all wallet transactions as a CSV file.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import csv
        from django.http import HttpResponse
        from .models import Wallet, WalletTransaction

        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        transactions = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="wallet-transactions-{request.user.username}.csv"'
        )

        writer = csv.writer(response)
        writer.writerow(['Date', 'Type', 'Amount', 'Balance After', 'Description', 'Reference'])
        for tx in transactions:
            writer.writerow([
                tx.created_at.isoformat(),
                tx.transaction_type,
                tx.amount,
                tx.balance_after,
                tx.description,
                tx.reference_id or '',
            ])

        return response


# ── Avatar upload ─────────────────────────────────────────────────────────────


class AvatarUploadView(APIView):
    """
    POST /api/v1/auth/avatar/
    Upload a profile picture (JPEG/PNG, max 2 MB).
    Stores the file in R2 and updates avatar_url on the user profile.

    DELETE /api/v1/auth/avatar/
    Remove the current avatar.
    """
    permission_classes = [IsAuthenticated]

    MAX_SIZE = 2 * 1024 * 1024  # 2 MB
    ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp'}

    def post(self, request):
        from django.core.files.storage import default_storage
        from PIL import Image
        import io

        f = request.FILES.get('avatar')
        if not f:
            return Response(
                {'detail': 'No file uploaded. Send a file with key "avatar".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if f.content_type not in self.ALLOWED_TYPES:
            return Response(
                {'detail': f'Invalid file type "{f.content_type}". Allowed: JPEG, PNG, WebP.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if f.size > self.MAX_SIZE:
            return Response(
                {'detail': f'File too large ({f.size / 1024 / 1024:.1f} MB). Maximum is 2 MB.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate it's a real image
        try:
            img = Image.open(f)
            img.verify()
            f.seek(0)
        except Exception:
            return Response(
                {'detail': 'Invalid image file.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Delete old avatar if it was an uploaded file (not a Google URL)
        profile = request.user.profile
        old_url = profile.avatar_url
        if old_url and 'r2.cloudflarestorage' in old_url:
            try:
                # Extract the path from the URL
                old_path = old_url.split('/avatars/')[-1] if '/avatars/' in old_url else None
                if old_path:
                    default_storage.delete(f'avatars/{old_path}')
            except Exception:
                pass  # best-effort cleanup

        # Save new avatar
        ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else 'jpg'
        filename = f'avatars/{request.user.id}.{ext}'

        # Save to storage (R2 / local filesystem)
        saved_name = default_storage.save(filename, f)
        avatar_url = default_storage.url(saved_name)

        profile.avatar_url = avatar_url
        profile.save(update_fields=['avatar_url'])

        logger.info('Avatar uploaded: user=%s url=%s', request.user.username, avatar_url)
        return Response({
            'avatar_url': avatar_url,
            'detail': 'Avatar updated successfully.',
        })

    def delete(self, request):
        profile = request.user.profile
        if not profile.avatar_url:
            return Response({'detail': 'No avatar to remove.'}, status=status.HTTP_404_NOT_FOUND)

        profile.avatar_url = ''
        profile.save(update_fields=['avatar_url'])
        logger.info('Avatar removed: user=%s', request.user.username)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ContactSubmissionView(APIView):
    """Public endpoint for landing-page contact form (no auth required)."""
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        from .serializers import ContactSubmissionSerializer
        serializer = ContactSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {'detail': 'Your message has been submitted successfully.'},
            status=status.HTTP_201_CREATED,
        )
