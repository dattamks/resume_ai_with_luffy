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
from .models import ConsentLog
from .throttles import AuthEndpointThrottle

logger = logging.getLogger('accounts')


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthEndpointThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
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

    @staticmethod
    def _get_client_ip(request):
        """Extract client IP, respecting X-Forwarded-For behind reverse proxies."""
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


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


class LogoutAllDevicesView(APIView):
    """
    POST /api/auth/logout-all/
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
    POST /api/auth/google/ — Authenticate with Google.

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
    POST /api/auth/google/complete/ — Complete Google sign-up.

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
        profile.save(update_fields=[
            'agreed_to_terms', 'agreed_to_data_usage', 'marketing_opt_in',
            'auth_provider', 'avatar_url', 'google_sub',
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
