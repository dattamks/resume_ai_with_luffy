"""
Views for the Crawler Bot Ingest API.

All endpoints are protected by a shared secret (``X-Crawler-Key`` header)
rather than user JWT auth.  This keeps the crawler service simple — it
only needs one env var and doesn't need to manage user accounts.

Settings required:
    CRAWLER_API_KEY  — shared secret (set in both services' env vars)
"""

import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Company, CompanyEntity, CompanyCareerPage, CrawlSource, DiscoveredJob,
)
from .serializers_ingest import (
    CompanyIngestSerializer, CompanyEntityIngestSerializer,
    CompanyCareerPageIngestSerializer,
    DiscoveredJobIngestSerializer,
    CrawlSourceSerializer, CrawlSourceUpdateSerializer,
    CompanyReadSerializer, CompanyEntityReadSerializer,
)

logger = logging.getLogger('analyzer')


# ── Authentication ───────────────────────────────────────────────────────────


class IsCrawlerAuthenticated(BasePermission):
    """
    Validate the ``X-Crawler-Key`` header against ``settings.CRAWLER_API_KEY``.
    Returns 401 if the key is missing and 403 if it's wrong.
    """

    def has_permission(self, request, view):
        expected = getattr(settings, 'CRAWLER_API_KEY', '')
        if not expected:
            logger.warning('CRAWLER_API_KEY is not set — all ingest requests denied.')
            return False
        provided = request.headers.get('X-Crawler-Key', '')
        return provided == expected


# ── Company Endpoints ────────────────────────────────────────────────────────


class CompanyIngestView(APIView):
    """
    POST /api/v1/ingest/companies/  — Upsert a single company.
    GET  /api/v1/ingest/companies/  — List all companies (for crawler reference).
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []  # No JWT — uses X-Crawler-Key
    throttle_classes = []        # No rate limit — protected by API key

    def get(self, request):
        qs = Company.objects.filter(is_active=True).order_by('name')
        serializer = CompanyReadSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = CompanyIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = serializer.save()
        logger.info('Company ingested: %s (id=%s)', company.name, company.id)
        return Response(
            CompanyReadSerializer(company).data,
            status=status.HTTP_201_CREATED,
        )


class CompanyBulkIngestView(APIView):
    """
    POST /api/v1/ingest/companies/bulk/  — Upsert multiple companies at once.
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        companies_data = request.data.get('companies', [])
        if not isinstance(companies_data, list):
            return Response(
                {'detail': '"companies" must be a list.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        errors = []
        for i, item in enumerate(companies_data):
            serializer = CompanyIngestSerializer(data=item)
            if serializer.is_valid():
                company = serializer.save()
                results.append({'name': company.name, 'id': str(company.id)})
            else:
                errors.append({'index': i, 'errors': serializer.errors})

        logger.info('Bulk company ingest: %d success, %d errors', len(results), len(errors))
        return Response(
            {'created_or_updated': results, 'errors': errors},
            status=status.HTTP_201_CREATED if results else status.HTTP_400_BAD_REQUEST,
        )


# ── CompanyEntity Endpoints ──────────────────────────────────────────────────


class CompanyEntityIngestView(APIView):
    """
    POST /api/v1/ingest/entities/  — Upsert a single company entity.
    GET  /api/v1/ingest/entities/  — List entities (optionally filter by company).
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        qs = CompanyEntity.objects.filter(is_active=True).select_related('company')
        company_name = request.query_params.get('company')
        if company_name:
            qs = qs.filter(company__name__iexact=company_name.strip())
        serializer = CompanyEntityReadSerializer(qs.order_by('company__name', 'operating_country'), many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = CompanyEntityIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = serializer.save()
        logger.info('CompanyEntity ingested: %s (id=%s)', entity.display_name, entity.id)
        return Response(
            CompanyEntityReadSerializer(entity).data,
            status=status.HTTP_201_CREATED,
        )


class CompanyEntityBulkIngestView(APIView):
    """
    POST /api/v1/ingest/entities/bulk/  — Upsert multiple entities at once.
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        entities_data = request.data.get('entities', [])
        if not isinstance(entities_data, list):
            return Response(
                {'detail': '"entities" must be a list.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        errors = []
        for i, item in enumerate(entities_data):
            serializer = CompanyEntityIngestSerializer(data=item)
            if serializer.is_valid():
                entity = serializer.save()
                results.append({'display_name': entity.display_name, 'id': str(entity.id)})
            else:
                errors.append({'index': i, 'errors': serializer.errors})

        logger.info('Bulk entity ingest: %d success, %d errors', len(results), len(errors))
        return Response(
            {'created_or_updated': results, 'errors': errors},
            status=status.HTTP_201_CREATED if results else status.HTTP_400_BAD_REQUEST,
        )


# ── Career Page Endpoints ────────────────────────────────────────────────────


class CareerPageIngestView(APIView):
    """
    POST /api/v1/ingest/career-pages/  — Upsert a single career page.
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        serializer = CompanyCareerPageIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        page = serializer.save()
        logger.info('CareerPage ingested: %s (id=%s)', page.url[:60], page.id)
        return Response(
            {'id': str(page.id), 'url': page.url, 'label': page.label},
            status=status.HTTP_201_CREATED,
        )


# ── Job Endpoints ────────────────────────────────────────────────────────────


class JobIngestView(APIView):
    """
    POST /api/v1/ingest/jobs/  — Upsert a single discovered job.

    On newly created jobs, queues the job ID for batch embedding +
    matching via a debounced Celery task (10s countdown). This avoids
    firing a heavy pipeline per single POST when the bot sends many
    individual requests in quick succession.
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        serializer = DiscoveredJobIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = serializer.save()
        logger.info(
            'Job ingested: %s @ %s (id=%s, source=%s, external_id=%s)',
            job.title, job.company, job.id, job.source, job.external_id,
        )
        # Queue for debounced batch processing
        if getattr(job, '_was_created', False):
            from django.core.cache import cache
            from .tasks import process_ingested_jobs_task

            # Accumulate job IDs in Redis list; a debounced task drains it
            queue_key = 'ingest:pending_job_ids'
            lock_key = 'ingest:pending_job_ids:scheduled'
            cache.set(queue_key, cache.get(queue_key, '') + str(job.id) + ',', timeout=120)
            # Schedule the processing task only once (10s countdown debounce)
            if cache.add(lock_key, 1, timeout=15):
                process_ingested_jobs_task.apply_async(
                    args=[None],  # None = drain from Redis queue
                    countdown=10,
                )
        return Response(
            {
                'id': str(job.id),
                'source': job.source,
                'external_id': job.external_id,
                'title': job.title,
            },
            status=status.HTTP_201_CREATED,
        )


class JobBulkIngestView(APIView):
    """
    POST /api/v1/ingest/jobs/bulk/  — Upsert multiple jobs at once.

    Accepts: ``{ "jobs": [ { ... }, { ... } ] }``

    On newly created jobs, fires a background task to compute pgvector
    embeddings and run matching against all active job alerts.
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        jobs_data = request.data.get('jobs', [])
        if not isinstance(jobs_data, list):
            return Response(
                {'detail': '"jobs" must be a list.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(jobs_data) > 500:
            return Response(
                {'detail': 'Maximum 500 jobs per bulk request.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        errors = []
        new_job_ids = []
        for i, item in enumerate(jobs_data):
            serializer = DiscoveredJobIngestSerializer(data=item)
            if serializer.is_valid():
                job = serializer.save()
                results.append({
                    'id': str(job.id),
                    'external_id': job.external_id,
                    'title': job.title,
                })
                if getattr(job, '_was_created', False):
                    new_job_ids.append(str(job.id))
            else:
                errors.append({'index': i, 'errors': serializer.errors})

        logger.info('Bulk job ingest: %d success, %d errors, %d new', len(results), len(errors), len(new_job_ids))

        # Trigger embedding + matching pipeline for newly created jobs
        if new_job_ids:
            from .tasks import process_ingested_jobs_task
            process_ingested_jobs_task.delay(new_job_ids)

        return Response(
            {
                'ingested': len(results),
                'failed': len(errors),
                'results': results,
                'errors': errors,
            },
            status=status.HTTP_201_CREATED if results else status.HTTP_400_BAD_REQUEST,
        )


# ── CrawlSource Endpoints ───────────────────────────────────────────────────


class CrawlSourceListView(APIView):
    """
    GET /api/v1/ingest/crawl-sources/  — List active crawl sources.

    The crawler queries this to know which URLs to crawl.
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        qs = CrawlSource.objects.filter(is_active=True).order_by('priority', 'name')
        serializer = CrawlSourceSerializer(qs, many=True)
        return Response(serializer.data)


class CrawlSourceUpdateView(APIView):
    """
    PATCH /api/v1/ingest/crawl-sources/<id>/  — Update last_crawled_at after crawl.
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def patch(self, request, pk):
        try:
            source = CrawlSource.objects.get(pk=pk)
        except CrawlSource.DoesNotExist:
            return Response(
                {'detail': 'CrawlSource not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CrawlSourceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source.last_crawled_at = serializer.validated_data['last_crawled_at']
        source.save(update_fields=['last_crawled_at', 'updated_at'])
        logger.info('CrawlSource updated: %s last_crawled_at=%s', source.name, source.last_crawled_at)
        return Response(CrawlSourceSerializer(source).data)


# ── Health / Ping ────────────────────────────────────────────────────────────


class IngestPingView(APIView):
    """
    GET /api/v1/ingest/ping/  — Quick auth check for the crawler.

    Returns 200 if the X-Crawler-Key is valid.
    """
    permission_classes = [IsCrawlerAuthenticated]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        return Response({
            'status': 'ok',
            'service': 'resume-ai-ingest',
            'timestamp': timezone.now().isoformat(),
        })
