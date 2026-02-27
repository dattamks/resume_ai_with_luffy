import logging
import uuid

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.throttles import AnalyzeThrottle, ReadOnlyThrottle, WriteThrottle
from .models import ResumeAnalysis, Resume, GeneratedResume, JobAlert, JobMatch, DiscoveredJob, Notification
from .serializers import (
    ResumeAnalysisCreateSerializer,
    ResumeAnalysisDetailSerializer,
    ResumeAnalysisListSerializer,
    ResumeSerializer,
    SharedAnalysisSerializer,
    GeneratedResumeSerializer,
    GeneratedResumeCreateSerializer,
    JobAlertSerializer,
    JobAlertCreateSerializer,
    JobAlertUpdateSerializer,
    JobMatchSerializer,
    JobMatchFeedbackSerializer,
    JobAlertRunSerializer,
    NotificationSerializer,
    NotificationMarkReadSerializer,
)
from .tasks import run_analysis_task, generate_improved_resume_task, extract_job_search_profile_task, match_jobs_task

logger = logging.getLogger('analyzer')


class AnalyzeResumeView(APIView):
    """
    POST /api/analyze/
    Upload a PDF resume + job description input → kicks off async analysis.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [AnalyzeThrottle]

    # Redis lock TTL — prevents duplicate submissions for the same user
    IDEMPOTENCY_LOCK_TTL = 30  # seconds

    def post(self, request):
        serializer = ResumeAnalysisCreateSerializer(
            data=request.data,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # ── Credit check — deduct upfront, refund on failure ──
        from accounts.services import deduct_credits, InsufficientCreditsError
        try:
            credit_result = deduct_credits(
                request.user,
                'resume_analysis',
                description='Resume analysis',
            )
        except InsufficientCreditsError as e:
            return Response(
                {
                    'detail': 'Insufficient credits.',
                    'balance': e.balance,
                    'cost': e.cost,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        # Idempotency guard: prevent double-click / duplicate submissions
        lock_key = f'analyze_lock:{request.user.id}'
        if not cache.add(lock_key, 1, self.IDEMPOTENCY_LOCK_TTL):
            # Refund since we deducted but can't proceed
            from accounts.services import refund_credits
            refund_credits(request.user, 'resume_analysis', description='Refund: duplicate submission blocked')
            return Response(
                {'detail': 'An analysis is already being submitted. Please wait.'},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            analysis = serializer.save(user=request.user, status=ResumeAnalysis.STATUS_PROCESSING)

            # Mark that credits were deducted for this analysis
            analysis.credits_deducted = True
            analysis.save(update_fields=['credits_deducted'])

            logger.info('Analysis record created (id=%s, status=processing, credits_deducted=True)', analysis.id)

            # Dispatch to Celery worker — returns immediately
            run_analysis_task.delay(analysis.id, request.user.id)

            logger.info('Celery task dispatched for analysis id=%s', analysis.id)
            return Response(
                {
                    'id': analysis.id,
                    'status': analysis.status,
                    'credits_used': credit_result['cost'],
                    'balance': credit_result['balance_after'],
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except Exception:
            # Release lock and refund credits on unexpected errors
            cache.delete(lock_key)
            from accounts.services import refund_credits
            refund_credits(request.user, 'resume_analysis', description='Refund: analysis creation failed')
            raise


class RetryAnalysisView(APIView):
    """
    POST /api/analyses/<id>/retry/
    Retry a failed or interrupted analysis from its last incomplete step.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [AnalyzeThrottle]

    def post(self, request, pk):
        from django.db import transaction

        with transaction.atomic():
            try:
                analysis = ResumeAnalysis.objects.select_for_update().get(
                    id=pk, user=request.user
                )
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

            # ── Credit check for retry — deduct upfront ──
            from accounts.services import deduct_credits, InsufficientCreditsError
            try:
                credit_result = deduct_credits(
                    request.user,
                    'resume_analysis',
                    description=f'Retry analysis #{analysis.id}',
                    reference_id=str(analysis.id),
                )
            except InsufficientCreditsError as e:
                return Response(
                    {
                        'detail': 'Insufficient credits.',
                        'balance': e.balance,
                        'cost': e.cost,
                    },
                    status=status.HTTP_402_PAYMENT_REQUIRED,
                )

            logger.info('Retrying analysis id=%s from step=%s', analysis.id, analysis.pipeline_step)

            # Reset status to processing but keep pipeline_step (so it resumes from there)
            analysis.status = ResumeAnalysis.STATUS_PROCESSING
            analysis.error_message = ''
            analysis.credits_deducted = True
            analysis.save(update_fields=['status', 'error_message', 'credits_deducted'])

        # Dispatch to Celery worker
        run_analysis_task.delay(analysis.id, request.user.id)

        return Response(
            {
                'id': analysis.id,
                'status': analysis.status,
                'pipeline_step': analysis.pipeline_step,
                'credits_used': credit_result['cost'],
                'balance': credit_result['balance_after'],
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AnalysisListView(ListAPIView):
    """
    GET /api/analyses/
    List all analyses for the authenticated user (paginated).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = ResumeAnalysisListSerializer

    def get_queryset(self):
        return ResumeAnalysis.objects.filter(user=self.request.user)


class AnalysisDetailView(RetrieveAPIView):
    """
    GET /api/analyses/<id>/
    Retrieve full details of a single analysis.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = ResumeAnalysisDetailSerializer

    def get_queryset(self):
        return (
            ResumeAnalysis.objects
            .filter(user=self.request.user)
            .select_related('scrape_result', 'llm_response')
        )


class AnalysisDeleteView(APIView):
    """
    DELETE /api/analyses/<id>/delete/
    Soft-delete a single analysis owned by the authenticated user.
    Clears heavy fields, deletes report PDF, orphans ScrapeResult/LLMResponse.
    Keeps lightweight metadata (ats_score, jd_role, etc.) for analytics.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def delete(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        analysis.soft_delete()

        # Invalidate status cache
        cache.delete(f'analysis_status:{request.user.id}:{pk}')

        logger.info('Soft-deleted analysis id=%s user=%s', pk, request.user.id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AnalysisPDFExportView(APIView):
    """
    GET /api/analyses/<id>/export-pdf/
    Return the pre-generated PDF from R2, or generate on-the-fly as fallback.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if analysis.status != ResumeAnalysis.STATUS_DONE:
            return Response(
                {'detail': 'Analysis is not complete yet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If a pre-generated PDF exists in R2, redirect to its signed URL
        if analysis.report_pdf:
            from django.shortcuts import redirect
            return redirect(analysis.report_pdf.url)

        # Fallback: generate on-the-fly (e.g. for older analyses before migration)
        try:
            from .services.pdf_report import generate_analysis_pdf

            pdf_bytes = generate_analysis_pdf(analysis)

            role_slug = (analysis.jd_role or 'analysis').replace(' ', '_')[:30]
            filename = f'resume_ai_{role_slug}_{analysis.pk}.pdf'

            from django.http import HttpResponse
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        except Exception:
            logger.exception('On-the-fly PDF generation failed for analysis %s', pk)
            return Response(
                {'detail': 'PDF generation failed. Please try again later.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class AnalysisStatusView(APIView):
    """
    GET /api/analyses/<id>/status/
    Ultra-fast polling endpoint — reads from Redis cache first,
    falls back to DB. Returns minimal payload for polling.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        # Try Redis cache first (set by Celery task) — scoped by user to prevent data leakage
        cache_key = f'analysis_status:{request.user.id}:{pk}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        # Fallback to DB
        try:
            analysis = ResumeAnalysis.objects.only(
                'id', 'status', 'pipeline_step', 'overall_grade', 'ats_score', 'error_message',
            ).get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = {
            'status': analysis.status,
            'pipeline_step': analysis.pipeline_step,
            'overall_grade': analysis.overall_grade,
            'ats_score': analysis.ats_score,
            'error_message': analysis.error_message,
        }
        # Populate cache for next poll
        cache.set(cache_key, data, timeout=3600)
        return Response(data)


# ── Resume endpoints ──────────────────────────────────────────────────────

class ResumeListView(ListAPIView):
    """
    GET /api/resumes/
    List the user's deduplicated resume files with analysis counts.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = ResumeSerializer

    def get_queryset(self):
        return (
            Resume.objects
            .filter(user=self.request.user)
            .annotate(active_analysis_count=Count(
                'analyses',
                filter=Q(analyses__deleted_at__isnull=True),
            ))
            .order_by('-uploaded_at')
        )


class ResumeDeleteView(APIView):
    """
    DELETE /api/resumes/<id>/
    Delete a resume file from storage.
    Only allowed if no active (non-soft-deleted) analyses reference it.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def delete(self, request, pk):
        try:
            resume = Resume.objects.get(pk=pk, user=request.user)
        except Resume.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Check for active analyses still referencing this resume
        active_count = ResumeAnalysis.objects.filter(resume=resume).count()
        if active_count > 0:
            return Response(
                {'detail': f'Cannot delete: {active_count} active analysis(es) still reference this resume.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Check for active job alerts referencing this resume
        from .models import JobAlert
        alert_count = JobAlert.objects.filter(resume=resume, is_active=True).count()
        if alert_count > 0:
            return Response(
                {'detail': f'Cannot delete: {alert_count} active job alert(s) still reference this resume. '
                           'Deactivate them first.'},
                status=status.HTTP_409_CONFLICT,
            )

        logger.info('Deleting resume id=%s file=%s user=%s', pk, resume.file.name, request.user.id)
        resume.delete()  # post_delete signal cleans up R2 file
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Dashboard stats endpoint ──────────────────────────────────────────────

class DashboardStatsView(APIView):
    """
    GET /api/dashboard/stats/
    User-level analytics computed from all analyses (including soft-deleted).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user = request.user
        # Use all_objects to include soft-deleted rows for analytics
        all_qs = ResumeAnalysis.all_objects.filter(user=user)
        active_qs = all_qs.filter(deleted_at__isnull=True)

        total = all_qs.count()
        active = active_qs.count()
        deleted = total - active

        # Average ATS score (all time, only completed analyses)
        avg_ats = all_qs.filter(
            status=ResumeAnalysis.STATUS_DONE,
            ats_score__isnull=False,
        ).aggregate(avg=Avg('ats_score'))['avg']

        # Score trend — last 10 completed analyses (newest first)
        score_trend = list(
            all_qs.filter(
                status=ResumeAnalysis.STATUS_DONE,
                ats_score__isnull=False,
            )
            .order_by('-created_at')[:10]
            .values('ats_score', 'jd_role', 'created_at')
        )

        # Top roles analyzed (all time)
        top_roles = list(
            all_qs.filter(jd_role__gt='')
            .values('jd_role')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )

        # Analyses per month (last 6 months)
        six_months_ago = timezone.now() - timezone.timedelta(days=180)
        monthly = list(
            all_qs.filter(created_at__gte=six_months_ago)
            .annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(count=Count('id'))
            .order_by('month')
        )

        return Response({
            'total_analyses': total,
            'active_analyses': active,
            'deleted_analyses': deleted,
            'average_ats_score': round(avg_ats, 1) if avg_ats is not None else None,
            'score_trend': score_trend,
            'top_roles': top_roles,
            'analyses_per_month': monthly,
        })


# ── Share endpoints ───────────────────────────────────────────────────────

class AnalysisShareView(APIView):
    """
    POST /api/analyses/<id>/share/   — Generate a public share token.
    DELETE /api/analyses/<id>/share/  — Revoke the share token.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if analysis.status != ResumeAnalysis.STATUS_DONE:
            return Response(
                {'detail': 'Only completed analyses can be shared.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If already shared, return existing token (idempotent)
        if analysis.share_token:
            share_path = f'/api/shared/{analysis.share_token}/'
            return Response({
                'share_token': str(analysis.share_token),
                'share_url': request.build_absolute_uri(share_path),
            })

        analysis.share_token = uuid.uuid4()
        analysis.save(update_fields=['share_token'])
        logger.info('Share token created for analysis id=%s user=%s', pk, request.user.id)

        share_path = f'/api/shared/{analysis.share_token}/'
        return Response({
            'share_token': str(analysis.share_token),
            'share_url': request.build_absolute_uri(share_path),
        }, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not analysis.share_token:
            return Response(
                {'detail': 'This analysis is not currently shared.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        analysis.share_token = None
        analysis.save(update_fields=['share_token'])
        logger.info('Share token revoked for analysis id=%s user=%s', pk, request.user.id)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SharedAnalysisView(APIView):
    """
    GET /api/shared/<token>/
    Public read-only view of a shared analysis. No auth required.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Skip JWT auth entirely for public access

    def get(self, request, token):
        try:
            analysis = ResumeAnalysis.objects.select_related(
                'scrape_result', 'llm_response',
            ).get(share_token=token)
        except ResumeAnalysis.DoesNotExist:
            return Response(
                {'detail': 'Shared analysis not found or link has been revoked.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SharedAnalysisSerializer(analysis)
        return Response(serializer.data)


# ── Resume Generation ────────────────────────────────────────────────────

class GenerateResumeView(APIView):
    """
    POST /api/analyses/<id>/generate-resume/
    Generate an improved resume from analysis findings.
    Costs 1 credit (resume_generation). Requires analysis status == done.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [AnalyzeThrottle]

    def post(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if analysis.status != ResumeAnalysis.STATUS_DONE:
            return Response(
                {'detail': 'Analysis must be complete before generating a resume.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request body
        serializer = GeneratedResumeCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        template = serializer.validated_data['template']
        fmt = serializer.validated_data['format']

        # ── Credit check — deduct upfront, refund on failure ──
        from accounts.services import deduct_credits, InsufficientCreditsError
        try:
            credit_result = deduct_credits(
                request.user,
                'resume_generation',
                description=f'Resume generation (analysis #{analysis.id})',
            )
        except InsufficientCreditsError as e:
            return Response(
                {
                    'detail': 'Insufficient credits.',
                    'balance': e.balance,
                    'cost': e.cost,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            # Create GeneratedResume record
            gen = GeneratedResume.objects.create(
                analysis=analysis,
                user=request.user,
                template=template,
                format=fmt,
                status=GeneratedResume.STATUS_PENDING,
                credits_deducted=True,
            )

            # Dispatch Celery task
            generate_improved_resume_task.delay(str(gen.id))

            logger.info(
                'Resume generation dispatched: gen_id=%s analysis_id=%s template=%s format=%s',
                gen.id, analysis.id, template, fmt,
            )

            return Response(
                {
                    'id': str(gen.id),
                    'status': gen.status,
                    'template': gen.template,
                    'format': gen.format,
                    'credits_used': credit_result['cost'],
                    'balance': credit_result['balance_after'],
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except Exception:
            from accounts.services import refund_credits
            refund_credits(
                request.user, 'resume_generation',
                description='Refund: resume generation creation failed',
            )
            raise


class GeneratedResumeStatusView(APIView):
    """
    GET /api/analyses/<id>/generated-resume/
    Poll the latest generated resume status for an analysis.
    Returns status + file URL when done.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Get the latest generated resume for this analysis
        gen = GeneratedResume.objects.filter(
            analysis=analysis, user=request.user,
        ).order_by('-created_at').first()

        if not gen:
            return Response(
                {'detail': 'No generated resume found for this analysis.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(GeneratedResumeSerializer(gen).data)


class GeneratedResumeDownloadView(APIView):
    """
    GET /api/analyses/<id>/generated-resume/download/
    Redirect to R2 signed URL for the generated resume file.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        gen = GeneratedResume.objects.filter(
            analysis=analysis, user=request.user,
            status=GeneratedResume.STATUS_DONE,
        ).order_by('-created_at').first()

        if not gen or not gen.file:
            return Response(
                {'detail': 'No generated resume file available.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.shortcuts import redirect
        return redirect(gen.file.url)


class GeneratedResumeListView(APIView):
    """
    GET /api/generated-resumes/
    List all generated resumes for the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        qs = GeneratedResume.objects.filter(
            user=request.user,
        ).select_related('analysis').order_by('-created_at')
        serializer = GeneratedResumeSerializer(qs, many=True)
        return Response(serializer.data)


# ── Phase 11: Smart Job Alerts ────────────────────────────────────────────────


class JobAlertListCreateView(APIView):
    """
    GET  /api/job-alerts/  — List the authenticated user's job alerts.
    POST /api/job-alerts/  — Create a new job alert (Pro plan required).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        alerts = (
            JobAlert.objects
            .filter(user=request.user)
            .select_related('resume', 'resume__job_search_profile')
            .order_by('-created_at')
        )
        return Response(JobAlertSerializer(alerts, many=True).data)

    def post(self, request):
        # ── Plan gating: Pro only ──
        from accounts.services import can_use_feature
        if not can_use_feature(request.user, 'job_notifications'):
            return Response(
                {'detail': 'Job alerts require a Pro plan.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Max active alerts quota ──
        profile = getattr(request.user, 'profile', None)
        plan = getattr(profile, 'plan', None) if profile else None
        max_alerts = getattr(plan, 'max_job_alerts', 0) if plan else 0
        if max_alerts > 0:
            active_count = JobAlert.objects.filter(
                user=request.user, is_active=True,
            ).count()
            if active_count >= max_alerts:
                return Response(
                    {
                        'detail': f'You have reached the maximum of {max_alerts} active job alerts for your plan.',
                        'max_job_alerts': max_alerts,
                        'active_count': active_count,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = JobAlertCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        alert = serializer.save(user=request.user)
        # Set next_run_at immediately
        alert.set_next_run()
        alert.save(update_fields=['next_run_at'])

        # Trigger LLM extraction of the resume search profile
        extract_job_search_profile_task.delay(str(alert.resume_id))

        logger.info('JobAlert created: id=%s user=%s resume=%s', alert.id, request.user.id, alert.resume_id)

        return Response(
            JobAlertSerializer(alert).data,
            status=status.HTTP_201_CREATED,
        )


class JobAlertDetailView(APIView):
    """
    GET    /api/job-alerts/<id>/  — Alert detail + latest run stats.
    PUT    /api/job-alerts/<id>/  — Update frequency/preferences/is_active.
    DELETE /api/job-alerts/<id>/  — Deactivate the alert.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def _get_alert(self, request, pk):
        try:
            return JobAlert.objects.select_related(
                'resume', 'resume__job_search_profile',
            ).get(id=pk, user=request.user)
        except (JobAlert.DoesNotExist, ValueError):
            return None

    def get(self, request, pk):
        alert = self._get_alert(request, pk)
        if not alert:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(JobAlertSerializer(alert).data)

    def put(self, request, pk):
        alert = self._get_alert(request, pk)
        if not alert:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = JobAlertUpdateSerializer(alert, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(JobAlertSerializer(alert).data)

    def delete(self, request, pk):
        alert = self._get_alert(request, pk)
        if not alert:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        alert.is_active = False
        alert.save(update_fields=['is_active'])
        logger.info('JobAlert deactivated: id=%s user=%s', alert.id, request.user.id)
        return Response({'detail': 'Job alert deactivated.'}, status=status.HTTP_200_OK)


class JobAlertMatchListView(APIView):
    """
    GET /api/job-alerts/<id>/matches/
    Paginated matched jobs with scores and reasons.
    Supports ?feedback= filter (pending/relevant/irrelevant/applied/dismissed).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        try:
            alert = JobAlert.objects.get(id=pk, user=request.user)
        except (JobAlert.DoesNotExist, ValueError):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        qs = (
            JobMatch.objects
            .filter(job_alert=alert)
            .select_related('discovered_job')
            .order_by('-relevance_score', '-created_at')
        )

        feedback_filter = request.query_params.get('feedback')
        if feedback_filter:
            valid_feedback = {c[0] for c in JobMatch.FEEDBACK_CHOICES}
            if feedback_filter not in valid_feedback:
                return Response(
                    {'detail': f'Invalid feedback filter. Choose from: {" ,".join(sorted(valid_feedback))}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(user_feedback=feedback_filter)

        # Basic pagination (20 per page)
        from django.core.paginator import Paginator
        try:
            page_num = int(request.query_params.get('page', 1))
            if page_num < 1:
                page_num = 1
        except (TypeError, ValueError):
            page_num = 1
        paginator = Paginator(qs, 20)
        page = paginator.get_page(page_num)

        return Response({
            'count': paginator.count,
            'num_pages': paginator.num_pages,
            'page': page_num,
            'results': JobMatchSerializer(page.object_list, many=True).data,
        })


class JobAlertMatchFeedbackView(APIView):
    """
    POST /api/job-alerts/<id>/matches/<match_id>/feedback/
    Update user feedback on a matched job (relevant/irrelevant/applied/dismissed).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def post(self, request, pk, match_pk):
        try:
            alert = JobAlert.objects.get(id=pk, user=request.user)
        except (JobAlert.DoesNotExist, ValueError):
            return Response({'detail': 'Alert not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            match = JobMatch.objects.get(id=match_pk, job_alert=alert)
        except (JobMatch.DoesNotExist, ValueError):
            return Response({'detail': 'Match not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = JobMatchFeedbackSerializer(match, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(JobMatchSerializer(match).data)


class JobAlertManualRunView(APIView):
    """
    POST /api/job-alerts/<id>/run/
    Trigger an on-demand manual job discovery + matching run (costs 1 credit).
    Returns 202 Accepted immediately; results appear in matches when done.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [AnalyzeThrottle]

    def post(self, request, pk):
        try:
            alert = JobAlert.objects.select_related(
                'user', 'resume', 'resume__job_search_profile',
            ).get(id=pk, user=request.user)
        except (JobAlert.DoesNotExist, ValueError):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not alert.is_active:
            return Response(
                {'detail': 'This job alert is deactivated.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if a search profile exists (needed to build queries)
        try:
            profile = alert.resume.job_search_profile
            if not profile.titles:
                raise AttributeError
        except Exception:
            return Response(
                {
                    'detail': 'Job search profile not yet extracted for this resume. '
                    'Please wait a moment and try again.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check credits upfront so we don't waste API calls
        from accounts.services import check_balance
        credit_info = check_balance(request.user, 'job_alert_run')
        if not credit_info['has_enough']:
            return Response(
                {
                    'detail': 'Insufficient credits.',
                    'balance': credit_info['balance'],
                    'cost': credit_info['cost'],
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        # Fire Firecrawl-based crawl for this single alert
        from .tasks import crawl_jobs_for_alert_task
        crawl_jobs_for_alert_task.delay(str(alert.id))

        logger.info('Manual job alert run triggered: alert=%s user=%s', alert.id, request.user.id)

        return Response(
            {
                'detail': 'Job discovery started. Check matches in a few minutes.',
                'alert_id': str(alert.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )


# ── Phase 12: Notification Views ─────────────────────────────────────────────


class NotificationListView(ListAPIView):
    """GET /api/notifications/ — paginated list of user's notifications."""
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class NotificationUnreadCountView(APIView):
    """GET /api/notifications/unread-count/ — unread notification count for badge."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        count = Notification.objects.filter(
            user=request.user, is_read=False,
        ).count()
        return Response({'unread_count': count})


class NotificationMarkReadView(APIView):
    """POST /api/notifications/mark-read/ — mark one or all notifications as read."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request):
        serializer = NotificationMarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        notification_id = serializer.validated_data.get('notification_id')
        mark_all = serializer.validated_data.get('mark_all', False)

        if notification_id:
            updated = Notification.objects.filter(
                id=notification_id, user=request.user, is_read=False,
            ).update(is_read=True)
            return Response({'marked_read': updated})
        elif mark_all:
            updated = Notification.objects.filter(
                user=request.user, is_read=False,
            ).update(is_read=True)
            return Response({'marked_read': updated})
        else:
            return Response(
                {'detail': 'Provide notification_id or set mark_all=true.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

