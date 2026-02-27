"""
Lightweight health-check endpoint used by Railway (and any load-balancer /
uptime monitor).  Returns 200 with a JSON body so it can double as a
smoke-test for the API layer.
"""
import logging

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
    Returns {"status": "ok"} when the app can reach the database.
    Returns 503 with {"status": "error", "detail": ...} otherwise.
    """
    try:
        connection.ensure_connection()
        return Response({'status': 'ok'})
    except Exception as exc:
        logger.error('Health check failed: %s', exc)
        return Response(
            {'status': 'error', 'detail': 'Database connection failed.'},
            status=503,
        )
