"""
Custom middleware for the resume_ai project.
"""
import time

from rest_framework.throttling import SimpleRateThrottle


class RateLimitHeadersMiddleware:
    """
    Inject standard rate-limit headers into every API response.

    Headers added (when throttle info is available):
      - X-RateLimit-Limit      Total allowed requests in the current window
      - X-RateLimit-Remaining   Requests remaining in the current window
      - X-RateLimit-Reset       Unix timestamp when the window resets

    How it works:
      DRF's ``APIView.check_throttles()`` calls ``allow_request()`` on each
      throttle instance. Our custom throttle classes (``HeaderAwareAnon`` and
      ``HeaderAwareUser`` in ``accounts/throttles.py``) stash themselves on
      ``request._throttle_instances`` after ``allow_request()`` runs.
      This middleware reads those instances and injects rate-limit headers.

      For 429 responses, DRF already sets ``Retry-After``. We supplement it
      with ``X-RateLimit-Remaining: 0`` and ``X-RateLimit-Reset``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Check if throttle data was stashed on the request
        throttles = getattr(request, '_throttle_instances', None)
        if throttles:
            self._inject_headers(response, throttles)
        elif response.status_code == 429:
            wait = response.get('Retry-After')
            if wait:
                try:
                    wait_seconds = float(wait)
                    response['X-RateLimit-Remaining'] = '0'
                    response['X-RateLimit-Reset'] = str(int(time.time() + wait_seconds))
                except (ValueError, TypeError):
                    pass

        return response

    @staticmethod
    def _inject_headers(response, throttles):
        """Find the most restrictive throttle and set headers."""
        best_remaining = None
        best_limit = None
        best_reset = None

        for throttle in throttles:
            if not isinstance(throttle, SimpleRateThrottle):
                continue

            history = getattr(throttle, 'history', None)
            duration = getattr(throttle, 'duration', None)
            num_requests = getattr(throttle, 'num_requests', None)

            if num_requests is None or duration is None:
                continue

            if history:
                remaining = max(0, num_requests - len(history))
                reset_at = history[-1] + duration
            else:
                remaining = num_requests
                reset_at = time.time() + duration

            if best_remaining is None or remaining < best_remaining:
                best_remaining = remaining
                best_limit = num_requests
                best_reset = reset_at

        if best_remaining is not None:
            response['X-RateLimit-Limit'] = str(best_limit)
            response['X-RateLimit-Remaining'] = str(best_remaining)
            response['X-RateLimit-Reset'] = str(int(best_reset))
