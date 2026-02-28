"""
Custom DRF throttle classes for i-Luffy.

Scopes (configured in settings.DEFAULT_THROTTLE_RATES):
    anon      – unauthenticated IP-based          (default 60/hr)
    user      – authenticated per-user (global)    (default 200/hr)
    analyze   – resume analysis writes             (default 10/hr)
    readonly  – authenticated read-only endpoints  (default 120/hr)
    write     – authenticated write endpoints      (default 60/hr)
    auth      – auth-related anon endpoints        (default 20/hr)

All throttle classes inherit from ``_HeaderAwareMixin`` which stashes
the resolved throttle instance on ``request._throttle_instances`` so
the ``RateLimitHeadersMiddleware`` can inject ``X-RateLimit-*`` headers.
"""
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle, AnonRateThrottle


class _HeaderAwareMixin:
    """
    Mixin that stashes the throttle instance on the request after
    ``allow_request()`` runs, so downstream middleware can read the
    throttle's ``history``, ``num_requests``, and ``duration`` to
    inject rate-limit headers.
    """

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)
        # Stash this instance on the request for RateLimitHeadersMiddleware
        instances = getattr(request, '_throttle_instances', None)
        if instances is None:
            instances = []
            request._throttle_instances = instances
        instances.append(self)
        return allowed


class HeaderAwareAnonThrottle(_HeaderAwareMixin, AnonRateThrottle):
    """Drop-in replacement for AnonRateThrottle that exposes rate-limit info."""
    pass


class HeaderAwareUserThrottle(_HeaderAwareMixin, UserRateThrottle):
    """Drop-in replacement for UserRateThrottle that exposes rate-limit info."""
    pass


class AnalyzeThrottle(_HeaderAwareMixin, UserRateThrottle):
    """Applies to POST /analyze/ and /retry/ — tighter than general auth rate."""
    scope = 'analyze'


class ReadOnlyThrottle(_HeaderAwareMixin, UserRateThrottle):
    """Applies to authenticated read-only endpoints (list, detail, dashboard)."""
    scope = 'readonly'


class WriteThrottle(_HeaderAwareMixin, UserRateThrottle):
    """Applies to authenticated write endpoints (delete, share, etc.)."""
    scope = 'write'


class PaymentThrottle(_HeaderAwareMixin, UserRateThrottle):
    """Applies to payment-related endpoints — prevents Razorpay API abuse."""
    scope = 'payment'


class AuthEndpointThrottle(_HeaderAwareMixin, SimpleRateThrottle):
    """
    IP-based throttle for public auth endpoints (register, login,
    forgot-password). Prevents brute-force and credential-stuffing attacks.
    """
    scope = 'auth'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }
