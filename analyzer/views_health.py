"""
Lightweight health-check endpoint used by Railway (and any load-balancer /
uptime monitor).  Returns 200 with a JSON body so it can double as a
smoke-test for the API layer.
"""
import logging

from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger('analyzer')


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([])  # health checks must never be rate-limited
def health_check(request):
    """
    GET /api/health/
    Returns {"status": "ok"} when the app can reach the database and Redis.
    Returns 503 with {"status": "error", ...} otherwise.
    """
    checks = {}

    # Database check
    try:
        connection.ensure_connection()
        checks['database'] = 'ok'
    except Exception as exc:
        logger.error('Health check DB failed: %s', exc)
        checks['database'] = 'error'

    # Redis/cache check
    try:
        cache.set('_health_check', '1', timeout=5)
        val = cache.get('_health_check')
        checks['cache'] = 'ok' if val == '1' else 'error'
    except Exception as exc:
        logger.error('Health check cache failed: %s', exc)
        checks['cache'] = 'error'

    # Celery check (lightweight ping)
    try:
        from resume_ai.celery import app as celery_app
        insp = celery_app.control.inspect(timeout=2.0)
        ping_result = insp.ping()
        checks['celery'] = 'ok' if ping_result else 'unavailable'
    except Exception as exc:
        logger.error('Health check celery failed: %s', exc)
        checks['celery'] = 'unavailable'

    all_ok = checks.get('database') == 'ok' and checks.get('cache') == 'ok'
    return Response(
        {'status': 'ok' if all_ok else 'error', 'checks': checks},
        status=200 if all_ok else 503,
    )
