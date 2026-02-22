import logging

from django.core.cache import cache
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView, DestroyAPIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .models import ResumeAnalysis
from .serializers import (
    ResumeAnalysisCreateSerializer,
    ResumeAnalysisDetailSerializer,
    ResumeAnalysisListSerializer,
)
from .tasks import run_analysis_task

logger = logging.getLogger('analyzer')


class AnalyzeThrottle(UserRateThrottle):
    """Separate, stricter throttle for the expensive AI analysis endpoint."""
    scope = 'analyze'


class AnalyzeResumeView(APIView):
    """
    POST /api/analyze/
    Upload a PDF resume + job description input → kicks off async analysis.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [AnalyzeThrottle]

    # Redis lock TTL — prevents duplicate submissions for the same user
    IDEMPOTENCY_LOCK_TTL = 30  # seconds

    def post(self, request):
        serializer = ResumeAnalysisCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Idempotency guard: prevent double-click / duplicate submissions
        lock_key = f'analyze_lock:{request.user.id}'
        if not cache.add(lock_key, 1, self.IDEMPOTENCY_LOCK_TTL):
            return Response(
                {'detail': 'An analysis is already being submitted. Please wait.'},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            analysis = serializer.save(user=request.user, status=ResumeAnalysis.STATUS_PROCESSING)
            logger.info('Analysis record created (id=%s, status=processing)', analysis.id)

            # Dispatch to Celery worker — returns immediately
            run_analysis_task.delay(analysis.id, request.user.id)

            logger.info('Celery task dispatched for analysis id=%s', analysis.id)
            return Response(
                {'id': analysis.id, 'status': analysis.status},
                status=status.HTTP_202_ACCEPTED,
            )
        except Exception:
            # Release lock on unexpected errors so user can retry
            cache.delete(lock_key)
            raise


class RetryAnalysisView(APIView):
    """
    POST /api/analyses/<id>/retry/
    Retry a failed or interrupted analysis from its last incomplete step.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [AnalyzeThrottle]

    def post(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(id=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response(
                {'detail': 'Analysis not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if analysis.status == ResumeAnalysis.STATUS_DONE:
            return Response(
                {'detail': 'This analysis is already complete.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if analysis.status == ResumeAnalysis.STATUS_PROCESSING:
            return Response(
                {'detail': 'This analysis is already being processed.'},
                status=status.HTTP_409_CONFLICT,
            )

        logger.info('Retrying analysis id=%s from step=%s', analysis.id, analysis.pipeline_step)

        # Reset status to processing but keep pipeline_step (so it resumes from there)
        analysis.status = ResumeAnalysis.STATUS_PROCESSING
        analysis.error_message = ''
        analysis.save(update_fields=['status', 'error_message'])

        # Dispatch to Celery worker
        run_analysis_task.delay(analysis.id, request.user.id)

        return Response(
            {'id': analysis.id, 'status': analysis.status, 'pipeline_step': analysis.pipeline_step},
            status=status.HTTP_202_ACCEPTED,
        )


class AnalysisListView(ListAPIView):
    """
    GET /api/analyses/
    List all analyses for the authenticated user (paginated).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = []  # read-only, no throttle
    serializer_class = ResumeAnalysisListSerializer

    def get_queryset(self):
        return ResumeAnalysis.objects.filter(user=self.request.user)


class AnalysisDetailView(RetrieveAPIView):
    """
    GET /api/analyses/<id>/
    Retrieve full details of a single analysis.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = []  # read-only, no throttle (used by polling)
    serializer_class = ResumeAnalysisDetailSerializer

    def get_queryset(self):
        return (
            ResumeAnalysis.objects
            .filter(user=self.request.user)
            .select_related('scrape_result', 'llm_response')
        )


class AnalysisDeleteView(DestroyAPIView):
    """
    DELETE /api/analyses/<id>/
    Delete a single analysis owned by the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def get_queryset(self):
        return ResumeAnalysis.objects.filter(user=self.request.user)


class AnalysisPDFExportView(APIView):
    """
    GET /api/analyses/<id>/export-pdf/
    Return the pre-generated PDF from R2, or generate on-the-fly as fallback.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def get(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if analysis.status != 'done':
            return Response(
                {'detail': 'Analysis is not complete yet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If a pre-generated PDF exists in R2, redirect to its signed URL
        if analysis.report_pdf:
            from django.shortcuts import redirect
            return redirect(analysis.report_pdf.url)

        # Fallback: generate on-the-fly (e.g. for older analyses before migration)
        from .services.pdf_report import render_analysis_pdf_html
        import weasyprint

        html_string = render_analysis_pdf_html(analysis)
        pdf_bytes = weasyprint.HTML(string=html_string).write_pdf()

        role_slug = (analysis.jd_role or 'analysis').replace(' ', '_')[:30]
        filename = f'resume_ai_{role_slug}_{analysis.pk}.pdf'

        from django.http import HttpResponse
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class AnalysisStatusView(APIView):
    """
    GET /api/analyses/<id>/status/
    Ultra-fast polling endpoint — reads from Redis cache first,
    falls back to DB. Returns minimal payload for polling.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def get(self, request, pk):
        # Try Redis cache first (set by Celery task) — scoped by user to prevent data leakage
        cache_key = f'analysis_status:{request.user.id}:{pk}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        # Fallback to DB
        try:
            analysis = ResumeAnalysis.objects.only(
                'id', 'status', 'pipeline_step', 'ats_score', 'error_message',
            ).get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = {
            'status': analysis.status,
            'pipeline_step': analysis.pipeline_step,
            'ats_score': analysis.ats_score,
            'error_message': analysis.error_message,
        }
        # Populate cache for next poll
        cache.set(cache_key, data, timeout=3600)
        return Response(data)
