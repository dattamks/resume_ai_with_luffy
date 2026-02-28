"""
Admin-only Celery monitoring endpoints.

Provides lightweight task status and worker info without requiring Flower.
"""

import logging

from celery import current_app
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class CeleryWorkersView(APIView):
    """
    GET /api/v1/admin/celery/workers/

    Returns active Celery workers and their stats.
    Admin only.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        inspect = current_app.control.inspect()

        try:
            ping = inspect.ping() or {}
            stats = inspect.stats() or {}
            active = inspect.active() or {}
            reserved = inspect.reserved() or {}
        except Exception as exc:
            logger.warning('Celery inspect failed: %s', exc)
            return Response(
                {'error': 'Unable to reach Celery workers.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        workers = []
        for name in ping:
            worker_stats = stats.get(name, {})
            worker_active = active.get(name, [])
            worker_reserved = reserved.get(name, [])
            workers.append({
                'name': name,
                'status': 'online',
                'active_tasks': len(worker_active),
                'reserved_tasks': len(worker_reserved),
                'total_processed': worker_stats.get('total', {}) if isinstance(worker_stats.get('total'), dict) else {},
                'pool': {
                    'max_concurrency': worker_stats.get('pool', {}).get('max-concurrency'),
                    'processes': worker_stats.get('pool', {}).get('processes', []),
                },
                'uptime': worker_stats.get('uptime'),
            })

        return Response({
            'workers': workers,
            'total_workers': len(workers),
            'checked_at': timezone.now().isoformat(),
        })


class CeleryActiveTasksView(APIView):
    """
    GET /api/v1/admin/celery/tasks/active/

    Returns currently executing tasks across all workers.
    Admin only.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        inspect = current_app.control.inspect()

        try:
            active = inspect.active() or {}
        except Exception as exc:
            logger.warning('Celery inspect failed: %s', exc)
            return Response(
                {'error': 'Unable to reach Celery workers.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        tasks = []
        for worker_name, worker_tasks in active.items():
            for task in worker_tasks:
                tasks.append({
                    'id': task.get('id'),
                    'name': task.get('name'),
                    'worker': worker_name,
                    'started': task.get('time_start'),
                    'args': task.get('args', ''),
                    'kwargs': task.get('kwargs', ''),
                })

        return Response({
            'active_tasks': tasks,
            'total': len(tasks),
            'checked_at': timezone.now().isoformat(),
        })


class CeleryTaskStatusView(APIView):
    """
    GET /api/v1/admin/celery/tasks/<task_id>/

    Check the status of a specific Celery task by ID.
    Admin only.
    """
    permission_classes = [IsAdminUser]

    def get(self, request, task_id):
        result = current_app.AsyncResult(task_id)

        data = {
            'task_id': task_id,
            'status': result.status,
            'ready': result.ready(),
            'successful': result.successful() if result.ready() else None,
            'failed': result.failed() if result.ready() else None,
        }

        if result.ready() and result.successful():
            data['result'] = str(result.result)[:500]  # Truncate for safety
        elif result.failed():
            data['error'] = str(result.result)[:500]

        return Response(data)


class CeleryQueueLengthView(APIView):
    """
    GET /api/v1/admin/celery/queues/

    Returns approximate queue lengths (requires Redis broker).
    Admin only.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        from django.conf import settings

        redis_url = getattr(settings, 'CELERY_BROKER_URL', None)
        if not redis_url:
            return Response(
                {'error': 'No Redis broker configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            import redis
            r = redis.Redis.from_url(redis_url)
            celery_queue = r.llen('celery')
        except Exception as exc:
            logger.warning('Redis queue check failed: %s', exc)
            return Response(
                {'error': 'Unable to check queue lengths.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({
            'queues': {
                'celery': celery_queue,
            },
            'checked_at': timezone.now().isoformat(),
        })
