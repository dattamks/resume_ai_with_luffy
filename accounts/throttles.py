"""
Custom DRF throttle classes for i-Luffy.

Scopes (configured in settings.DEFAULT_THROTTLE_RATES):
    anon      – unauthenticated IP-based          (default 60/hr)
    user      – authenticated per-user (global)    (default 200/hr)
    analyze   – resume analysis writes             (default 10/hr)
    readonly  – authenticated read-only endpoints  (default 120/hr)
    auth      – auth-related anon endpoints        (default 20/hr)
"""
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class AnalyzeThrottle(UserRateThrottle):
    """Applies to POST /analyze/ and /retry/ — tighter than general auth rate."""
    scope = 'analyze'


class ReadOnlyThrottle(UserRateThrottle):
    """Applies to authenticated read-only endpoints (list, detail, dashboard)."""
    scope = 'readonly'


class AuthEndpointThrottle(SimpleRateThrottle):
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
