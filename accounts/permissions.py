"""Custom DRF permissions for the accounts app."""
from django.conf import settings
from rest_framework.permissions import BasePermission


class IsEmailVerified(BasePermission):
    """
    Allow the request only if the authenticated user's email is verified.

    Enforcement is gated on ``settings.REQUIRE_EMAIL_VERIFICATION`` so it can be
    toggled per environment (and is disabled during tests). Google OAuth users
    are auto-verified at sign-in, so this only ever blocks email/password users
    who registered but never confirmed their address.

    Apply alongside ``IsAuthenticated`` on the high-value actions that should
    require a confirmed email (analysis, resume generation, purchases).
    """

    message = (
        'Please verify your email address to use this feature. '
        'Check your inbox for the verification link or request a new one.'
    )
    code = 'email_not_verified'

    def has_permission(self, request, view):
        if not getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', False):
            return True
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        profile = getattr(user, 'profile', None)
        return bool(profile and profile.is_email_verified)
