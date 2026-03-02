import logging
import uuid

from django.core.cache import cache
from django.db import models
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import status, filters
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.throttles import AnalyzeThrottle, ReadOnlyThrottle, WriteThrottle
from accounts.services import (
    deduct_credits, refund_credits, check_balance,
    can_use_feature, InsufficientCreditsError,
)
from .models import ResumeAnalysis, Resume, GeneratedResume, JobAlert, JobMatch, DiscoveredJob, Notification, ResumeVersion, InterviewPrep, CoverLetter, ResumeTemplate
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
    ResumeVersionSerializer,
    InterviewPrepSerializer,
    InterviewPrepCreateSerializer,
    CoverLetterSerializer,
    CoverLetterCreateSerializer,
    BulkAnalysisCreateSerializer,
    ResumeTemplateSerializer,
)
from .tasks import run_analysis_task, generate_improved_resume_task, extract_job_search_profile_task, match_jobs_task, generate_interview_prep_task, generate_cover_letter_task

logger = logging.getLogger('analyzer')


class AnalyzeResumeView(APIView):
    """
    POST /api/v1/analyze/
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

        # ── Plan quota: monthly analysis limit ──
        profile = getattr(request.user, 'profile', None)
        plan = getattr(profile, 'plan', None) if profile else None
        if plan and plan.analyses_per_month > 0:
            from django.utils import timezone as tz
            month_start = tz.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_count = ResumeAnalysis.objects.filter(
                user=request.user, created_at__gte=month_start,
            ).exclude(status=ResumeAnalysis.STATUS_FAILED).count()
            if month_count >= plan.analyses_per_month:
                return Response(
                    {
                        'detail': f'Monthly analysis limit reached ({plan.analyses_per_month}). Upgrade your plan for more.',
                        'limit': plan.analyses_per_month,
                        'used': month_count,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # ── Plan quota: max resumes stored ──
        if plan and plan.max_resumes_stored > 0:
            resume_count = Resume.objects.filter(user=request.user).count()
            if resume_count >= plan.max_resumes_stored:
                return Response(
                    {
                        'detail': f'Resume storage limit reached ({plan.max_resumes_stored}). Delete old resumes or upgrade.',
                        'limit': plan.max_resumes_stored,
                        'stored': resume_count,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # ── Plan quota: per-plan resume size limit ──
        resume_file = request.FILES.get('resume')
        if resume_file and plan and plan.max_resume_size_mb:
            max_bytes = plan.max_resume_size_mb * 1024 * 1024
            if resume_file.size > max_bytes:
                return Response(
                    {
                        'detail': f'Resume file exceeds your plan limit of {plan.max_resume_size_mb} MB.',
                        'max_size_mb': plan.max_resume_size_mb,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ── Credit check — deduct upfront, refund on failure ──
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

            # Track activity for streak
            from .models import UserActivity
            UserActivity.record(request.user, UserActivity.ACTION_ANALYSIS)

            # Build response — include duplicate resume warning if applicable
            response_data = {
                'id': analysis.id,
                'status': analysis.status,
                'credits_used': credit_result['cost'],
                'balance': credit_result['balance_after'],
            }

            # Check if resume was a duplicate (file_hash already existed)
            resume_obj = analysis.resume
            if resume_obj:
                existing_analyses = ResumeAnalysis.objects.filter(
                    resume=resume_obj, user=request.user,
                ).exclude(id=analysis.id).count()
                if existing_analyses > 0:
                    response_data['duplicate_resume_warning'] = (
                        f'This resume has been analyzed {existing_analyses} time(s) before. '
                        'Consider uploading an updated version for new insights.'
                    )

            return Response(response_data, status=status.HTTP_202_ACCEPTED)
        except Exception:
            # Release lock and refund credits on unexpected errors
            cache.delete(lock_key)
            refund_credits(request.user, 'resume_analysis', description='Refund: analysis creation failed')
            raise


class RetryAnalysisView(APIView):
    """
    POST /api/v1/analyses/<id>/retry/
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
    GET /api/v1/analyses/
    List all analyses for the authenticated user (paginated).

    Query params:
    - ?search=  — search in jd_role, jd_company, jd_industry
    - ?status=  — filter by status (pending, processing, done, failed)
    - ?ordering= — sort by created_at, ats_score, jd_role (prefix with - for desc)
    - ?score_min= — minimum ats_score (integer)
    - ?score_max= — maximum ats_score (integer)
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = ResumeAnalysisListSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['jd_role', 'jd_company', 'jd_industry']
    ordering_fields = ['created_at', 'ats_score', 'jd_role', 'status']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = ResumeAnalysis.objects.filter(user=self.request.user)

        # Status filter
        status_filter = self.request.query_params.get('status')
        if status_filter and status_filter in dict(ResumeAnalysis.STATUS_CHOICES):
            qs = qs.filter(status=status_filter)

        # Score range filters
        score_min = self.request.query_params.get('score_min')
        if score_min and score_min.isdigit():
            qs = qs.filter(ats_score__gte=int(score_min))

        score_max = self.request.query_params.get('score_max')
        if score_max and score_max.isdigit():
            qs = qs.filter(ats_score__lte=int(score_max))

        return qs


class AnalysisDetailView(RetrieveAPIView):
    """
    GET /api/v1/analyses/<id>/
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
    DELETE /api/v1/analyses/<id>/delete/
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
    GET /api/v1/analyses/<id>/export-pdf/
    Return the pre-generated PDF from R2, or generate on-the-fly as fallback.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # ── Plan feature flag: pdf_export ──
        profile = getattr(request.user, 'profile', None)
        plan = getattr(profile, 'plan', None) if profile else None
        if plan and not plan.pdf_export:
            return Response(
                {'detail': 'PDF export requires a higher plan.'},
                status=status.HTTP_403_FORBIDDEN,
            )

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
    GET /api/v1/analyses/<id>/status/
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
    GET /api/v1/resumes/
    List the user's deduplicated resume files with analysis counts.

    Query params:
    - ?search=  — search in original_filename
    - ?ordering= — sort by uploaded_at, original_filename, file_size_bytes (prefix - for desc)
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = ResumeSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['original_filename']
    ordering_fields = ['uploaded_at', 'original_filename', 'file_size_bytes']
    ordering = ['-uploaded_at']

    def get_queryset(self):
        return (
            Resume.objects
            .filter(user=self.request.user)
            .annotate(active_analysis_count=Count(
                'analyses',
                filter=Q(analyses__deleted_at__isnull=True),
            ))
        )


class ResumeDeleteView(APIView):
    """
    DELETE /api/v1/resumes/<id>/
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

        # If the deleted resume was the default, promote the most recent remaining resume
        if not Resume.objects.filter(user=request.user, is_default=True).exists():
            next_resume = Resume.objects.filter(user=request.user).order_by('-uploaded_at').first()
            if next_resume:
                next_resume.set_as_default()

        return Response(status=status.HTTP_204_NO_CONTENT)


class SetDefaultResumeView(APIView):
    """
    POST /api/v1/resumes/<uuid:pk>/set-default/
    Set the specified resume as the user's default resume.

    The default resume is the source of truth for:
    - Dashboard analytics (score trend, grades, keywords)
    - Feed personalisation (job matching via embedding)
    - Skill-gap and market-insights widgets
    - Recommendations engine

    Only one resume can be default at a time. The previous default
    is automatically cleared.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request, pk):
        try:
            resume = Resume.objects.get(pk=pk, user=request.user)
        except Resume.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        resume.set_as_default()

        # Bust cached dashboard & feed data so they pick up the new default
        cache.delete(f'dashboard_stats:{request.user.id}')

        return Response({
            'detail': 'Default resume updated.',
            'resume_id': str(resume.id),
            'original_filename': resume.original_filename,
        })


# ── Dashboard stats endpoint ──────────────────────────────────────────────

class DashboardStatsView(APIView):
    """
    GET /api/v1/dashboard/stats/
    User-level analytics computed from all analyses (including soft-deleted).
    Enriched with data from resumes, generations, job alerts, interview preps,
    cover letters, chat sessions, credit usage, and activity streak.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user = request.user

        # Cache dashboard stats per user for 5 minutes (heavy aggregate queries)
        cache_key = f'dashboard_stats:{user.id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        from accounts.models import WalletTransaction
        from .models import UserActivity, ResumeChat, LLMResponse
        from collections import Counter

        # ───── Default resume scoping ──────────────────────────────────
        default_resume = Resume.get_default_for_user(user)

        # ───── Analyses ─────────────────────────────────────────────────
        # User-wide totals (overview counts)
        all_qs = ResumeAnalysis.all_objects.filter(user=user)
        active_qs = all_qs.filter(deleted_at__isnull=True)

        total = all_qs.count()
        active = active_qs.count()
        deleted = total - active

        # Personalised analytics scope: default resume only when set
        if default_resume:
            analytics_qs = ResumeAnalysis.all_objects.filter(user=user, resume=default_resume)
        else:
            analytics_qs = all_qs

        done_qs = analytics_qs.filter(
            status=ResumeAnalysis.STATUS_DONE,
            ats_score__isnull=False,
        )

        avg_ats = done_qs.aggregate(avg=Avg('ats_score'))['avg']

        # Best & worst scores
        score_extremes = done_qs.aggregate(
            best=models.Max('ats_score'),
            worst=models.Min('ats_score'),
        )

        # Score trend — last 10 completed analyses (newest first)
        score_trend_raw = list(
            done_qs.order_by('-created_at')[:10]
            .values('ats_score', 'scores', 'jd_role', 'created_at')
        )
        score_trend = []
        for entry in score_trend_raw:
            item = {
                'ats_score': entry['ats_score'],
                'jd_role': entry['jd_role'],
                'created_at': entry['created_at'],
            }
            scores = entry.get('scores') or {}
            item['generic_ats'] = scores.get('generic_ats')
            item['workday_ats'] = scores.get('workday_ats')
            item['greenhouse_ats'] = scores.get('greenhouse_ats')
            item['keyword_match_percent'] = scores.get('keyword_match_percent')
            score_trend.append(item)

        # Grade distribution
        grade_distribution = {
            item['overall_grade']: item['count']
            for item in done_qs
            .filter(overall_grade__gt='')
            .values('overall_grade')
            .annotate(count=Count('id'))
            .order_by('-count')
        }

        # Top roles (all time, top 5)
        top_roles = list(
            all_qs.filter(jd_role__gt='')
            .values('jd_role')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )

        # Top industries (all time, top 5)
        top_industries = list(
            all_qs.filter(jd_industry__gt='')
            .values('jd_industry')
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

        # Top missing keywords (from last 20 done analyses)
        recent_done = done_qs.order_by('-created_at')[:20]
        keyword_counter = Counter()
        for analysis in recent_done:
            ka = analysis.keyword_analysis or {}
            for kw in ka.get('missing_keywords', []):
                if isinstance(kw, str):
                    keyword_counter[kw.lower().strip()] += 1
        top_missing_keywords = [
            {'keyword': kw, 'count': cnt}
            for kw, cnt in keyword_counter.most_common(10)
        ]

        # Keyword match trend (last 10, newest first — parallel to score_trend)
        keyword_match_trend = []
        for entry in score_trend_raw:
            scores = entry.get('scores') or {}
            km = scores.get('keyword_match_percent')
            if km is not None:
                keyword_match_trend.append({
                    'jd_role': entry['jd_role'],
                    'keyword_match_percent': km,
                    'created_at': entry['created_at'],
                })

        # ───── Credit usage (FIXED data contract) ──────────────────────
        # Map transaction_type → (type, subtype) for frontend
        TYPE_MAP = {
            'analysis_debit': ('debit', 'analysis'),
            'topup':          ('credit', 'topup'),
            'plan_credit':    ('credit', 'plan'),
            'refund':         ('credit', 'refund'),
            'upgrade_bonus':  ('credit', 'upgrade_bonus'),
            'admin_adjustment': ('credit', 'admin'),
        }
        credit_usage_raw = list(
            WalletTransaction.objects.filter(
                wallet__user=user,
                created_at__gte=six_months_ago,
            )
            .annotate(month=TruncMonth('created_at'))
            .values('month', 'transaction_type')
            .annotate(
                count=Count('id'),
                amount_sum=Sum('amount'),
            )
            .order_by('month')
        )
        credit_usage = []
        for row in credit_usage_raw:
            tt = row['transaction_type']
            type_label, subtype = TYPE_MAP.get(tt, ('debit', tt))
            credit_usage.append({
                'month': row['month'].strftime('%Y-%m') if row['month'] else None,
                'type': type_label,
                'subtype': subtype,
                'count': row['count'],
                'total': abs(row['amount_sum'] or 0),
            })

        # ───── Resume counts ───────────────────────────────────────────
        resume_count = Resume.objects.filter(user=user).count()

        # ───── Generated resumes ───────────────────────────────────────
        gen_total = GeneratedResume.objects.filter(user=user).count()
        gen_done = GeneratedResume.objects.filter(
            user=user, status=GeneratedResume.STATUS_DONE,
        ).count()

        # ───── Interview preps ─────────────────────────────────────────
        prep_total = InterviewPrep.objects.filter(user=user).count()
        prep_done = InterviewPrep.objects.filter(
            user=user, status=InterviewPrep.STATUS_DONE,
        ).count()

        # ───── Cover letters ──────────────────────────────────────────
        cl_total = CoverLetter.objects.filter(user=user).count()
        cl_done = CoverLetter.objects.filter(
            user=user, status=CoverLetter.STATUS_DONE,
        ).count()

        # ───── Resume chat sessions ───────────────────────────────────
        chat_active = ResumeChat.objects.filter(
            user=user, status=ResumeChat.STATUS_ACTIVE,
        ).count()
        chat_completed = ResumeChat.objects.filter(
            user=user, status=ResumeChat.STATUS_COMPLETED,
        ).count()

        # ───── Job alerts ─────────────────────────────────────────────
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        alert_count = JobAlert.objects.filter(user=user).count()
        active_alerts = JobAlert.objects.filter(user=user, is_active=True).count()
        weekly_job_matches = JobMatch.objects.filter(
            job_alert__user=user,
            created_at__gte=seven_days_ago,
        ).count()
        total_matches = JobMatch.objects.filter(job_alert__user=user).count()
        matches_applied = JobMatch.objects.filter(
            job_alert__user=user, user_feedback='applied',
        ).count()
        matches_relevant = JobMatch.objects.filter(
            job_alert__user=user, user_feedback='relevant',
        ).count()
        matches_irrelevant = JobMatch.objects.filter(
            job_alert__user=user, user_feedback='irrelevant',
        ).count()

        # ───── LLM usage (token + cost totals) ────────────────────────
        llm_agg = LLMResponse.objects.filter(
            user=user, status=LLMResponse.STATUS_DONE,
        ).aggregate(
            total_tokens=Sum('total_tokens'),
            total_cost=Sum('estimated_cost_usd'),
            call_count=Count('id'),
        )

        # ───── Plan usage ─────────────────────────────────────────────
        plan_usage = None
        try:
            profile = user.profile
            plan = profile.plan
            if plan and plan.analyses_per_month > 0:
                start_of_month = timezone.now().replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0,
                )
                analyses_this_month = all_qs.filter(
                    created_at__gte=start_of_month,
                ).count()
                plan_usage = {
                    'plan_name': plan.name,
                    'analyses_this_month': analyses_this_month,
                    'analyses_limit': plan.analyses_per_month,
                    'usage_percent': round(
                        (analyses_this_month / plan.analyses_per_month) * 100, 1,
                    ),
                }
        except Exception:
            pass

        # ───── Industry benchmark (percentile rank) ───────────────────
        industry_benchmark = None
        if avg_ats is not None:
            all_user_avgs = (
                ResumeAnalysis.all_objects
                .filter(status=ResumeAnalysis.STATUS_DONE, ats_score__isnull=False)
                .values('user')
                .annotate(user_avg=Avg('ats_score'))
            )
            total_users = all_user_avgs.count()
            if total_users > 1:
                users_below = sum(
                    1 for row in all_user_avgs if row['user_avg'] < avg_ats
                )
                industry_benchmark = round((users_below / total_users) * 100)
            else:
                industry_benchmark = 50

        # ───── Activity streak ────────────────────────────────────────
        streak_days, actions_this_month = UserActivity.get_streak(user)

        # ───── Assemble response ──────────────────────────────────────
        data = {
            # Default resume powering personalised analytics
            'default_resume_id': str(default_resume.id) if default_resume else None,

            # Analyses
            'total_analyses': total,
            'active_analyses': active,
            'deleted_analyses': deleted,
            'average_ats_score': round(avg_ats, 1) if avg_ats is not None else None,
            'best_ats_score': score_extremes['best'],
            'worst_ats_score': score_extremes['worst'],
            'score_trend': score_trend,
            'grade_distribution': grade_distribution,
            'top_roles': top_roles,
            'top_industries': top_industries,
            'analyses_per_month': monthly,
            'top_missing_keywords': top_missing_keywords,
            'keyword_match_trend': keyword_match_trend,

            # Credits (fixed type/subtype contract)
            'credit_usage': credit_usage,

            # Resumes
            'resume_count': resume_count,

            # Generated resumes
            'generated_resumes_total': gen_total,
            'generated_resumes_done': gen_done,

            # Interview preps
            'interview_preps_total': prep_total,
            'interview_preps_done': prep_done,

            # Cover letters
            'cover_letters_total': cl_total,
            'cover_letters_done': cl_done,

            # Chat builder
            'chat_sessions_active': chat_active,
            'chat_sessions_completed': chat_completed,

            # Job alerts
            'job_alerts_count': alert_count,
            'active_job_alerts': active_alerts,
            'weekly_job_matches': weekly_job_matches,
            'total_job_matches': total_matches,
            'matches_applied': matches_applied,
            'matches_relevant': matches_relevant,
            'matches_irrelevant': matches_irrelevant,

            # LLM usage
            'llm_calls': llm_agg['call_count'] or 0,
            'llm_tokens_used': llm_agg['total_tokens'] or 0,
            'llm_cost_usd': float(llm_agg['total_cost'] or 0),

            # Plan usage
            'plan_usage': plan_usage,

            # Benchmark
            'industry_benchmark_percentile': industry_benchmark,

            # Activity streak
            'activity_streak': {
                'streak_days': streak_days,
                'actions_this_month': actions_this_month,
            },
        }

        cache.set(cache_key, data, timeout=300)  # 5-minute TTL
        return Response(data)


# ── Share endpoints ───────────────────────────────────────────────────────

class AnalysisShareView(APIView):
    """
    POST /api/v1/analyses/<id>/share/   — Generate a public share token.
    DELETE /api/v1/analyses/<id>/share/  — Revoke the share token.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # ── Plan feature flag: share_analysis ──
        profile = getattr(request.user, 'profile', None)
        plan = getattr(profile, 'plan', None) if profile else None
        if plan and not plan.share_analysis:
            return Response(
                {'detail': 'Sharing analyses requires a higher plan.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if analysis.status != ResumeAnalysis.STATUS_DONE:
            return Response(
                {'detail': 'Only completed analyses can be shared.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If already shared, return existing token (idempotent)
        if analysis.share_token:
            share_path = f'/api/v1/shared/{analysis.share_token}/'
            return Response({
                'share_token': str(analysis.share_token),
                'share_url': request.build_absolute_uri(share_path),
            })

        analysis.share_token = uuid.uuid4()
        analysis.save(update_fields=['share_token'])
        logger.info('Share token created for analysis id=%s user=%s', pk, request.user.id)

        share_path = f'/api/v1/shared/{analysis.share_token}/'
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
    GET /api/v1/shared/<token>/
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
    POST /api/v1/analyses/<id>/generate-resume/
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

        # ── Plan gating for premium templates ──
        template_obj = getattr(serializer, '_template_obj', None)
        if template_obj and template_obj.is_premium:
            profile = getattr(request.user, 'profile', None)
            has_access = (
                profile
                and profile.plan
                and profile.plan.premium_templates
                and (
                    profile.plan.billing_cycle == 'free'
                    or not profile.plan_valid_until
                    or profile.plan_valid_until >= timezone.now()
                )
            )
            if not has_access:
                return Response(
                    {
                        'detail': 'Premium template requires a paid plan with premium templates enabled.',
                        'template': template,
                        'is_premium': True,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # ── Credit check — deduct upfront, refund on failure ──
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

            from .models import UserActivity
            UserActivity.record(request.user, UserActivity.ACTION_RESUME_GEN)

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
            refund_credits(
                request.user, 'resume_generation',
                description='Refund: resume generation creation failed',
            )
            raise


class GeneratedResumeStatusView(APIView):
    """
    GET /api/v1/analyses/<id>/generated-resume/
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
    GET /api/v1/analyses/<id>/generated-resume/download/
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
    GET /api/v1/generated-resumes/
    List all generated resumes for the authenticated user (paginated).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        qs = GeneratedResume.objects.filter(
            user=request.user,
        ).select_related('analysis').order_by('-created_at')
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = GeneratedResumeSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ── Phase 11: Smart Job Alerts ────────────────────────────────────────────────


class JobAlertListCreateView(APIView):
    """
    GET  /api/v1/job-alerts/  — List the authenticated user's job alerts.
    POST /api/v1/job-alerts/  — Create a new job alert (Pro plan required).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        alerts = (
            JobAlert.objects
            .filter(user=request.user)
            .select_related('resume', 'resume__job_search_profile')
            .annotate(total_matches=Count('matches'))
            .order_by('-created_at')
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(alerts, request)
        return paginator.get_paginated_response(
            JobAlertSerializer(page, many=True).data
        )

    def post(self, request):
        # ── Plan gating: Pro only ──
        if not can_use_feature(request.user, 'job_notifications'):
            return Response(
                {'detail': 'Job alerts require a Pro plan.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Alert quota: enforce max_job_alerts ──
        profile = getattr(request.user, 'profile', None)
        max_alerts = getattr(profile.plan, 'max_job_alerts', 0) if profile and profile.plan else 0
        current_count = JobAlert.objects.filter(user=request.user, is_active=True).count()
        if max_alerts and current_count >= max_alerts:
            return Response(
                {
                    'detail': f'You have reached the maximum of {max_alerts} active job alerts for your plan.',
                    'max_alerts': max_alerts,
                    'current_count': current_count,
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
    GET    /api/v1/job-alerts/<id>/  — Alert detail + latest run stats.
    PUT    /api/v1/job-alerts/<id>/  — Update frequency/preferences/is_active.
    DELETE /api/v1/job-alerts/<id>/  — Deactivate the alert.
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
    GET /api/v1/job-alerts/<id>/matches/
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

        from rest_framework.pagination import PageNumberPagination
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            JobMatchSerializer(page, many=True).data
        )


class JobAlertMatchFeedbackView(APIView):
    """
    POST /api/v1/job-alerts/<id>/matches/<match_id>/feedback/
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
    POST /api/v1/job-alerts/<id>/run/
    Trigger an on-demand manual job discovery + matching run (free).
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

        # Fire Firecrawl-based crawl for this single alert
        from .tasks import crawl_jobs_for_alert_task
        crawl_jobs_for_alert_task.delay(str(alert.id))

        logger.info('Manual job alert run triggered: alert=%s user=%s', alert.id, request.user.id)

        from .models import UserActivity
        UserActivity.record(request.user, UserActivity.ACTION_JOB_ALERT_RUN)

        return Response(
            {
                'detail': 'Job discovery started. Check matches in a few minutes.',
                'alert_id': str(alert.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )


# ── Phase 12: Notification Views ─────────────────────────────────────────────


class NotificationListView(ListAPIView):
    """GET /api/v1/notifications/ — paginated list of user's notifications."""
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class NotificationUnreadCountView(APIView):
    """GET /api/v1/notifications/unread-count/ — unread notification count for badge."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        count = Notification.objects.filter(
            user=request.user, is_read=False,
        ).count()
        return Response({'unread_count': count})


class NotificationMarkReadView(APIView):
    """POST /api/v1/notifications/mark-read/ — mark one or all notifications as read."""
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


# ── Cancel stuck analysis ────────────────────────────────────────────────────


class AnalysisCancelView(APIView):
    """
    POST /api/v1/analyses/<id>/cancel/
    Cancel a stuck/processing analysis by revoking the Celery task.
    Marks as failed and refunds credits.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if analysis.status != ResumeAnalysis.STATUS_PROCESSING:
            return Response(
                {'detail': 'Only processing analyses can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Revoke the Celery task if we have the ID
        if analysis.celery_task_id:
            try:
                from resume_ai.celery import app as celery_app
                celery_app.control.revoke(analysis.celery_task_id, terminate=True)
                logger.info('Revoked Celery task %s for analysis %s', analysis.celery_task_id, pk)
            except Exception:
                logger.warning('Failed to revoke Celery task %s', analysis.celery_task_id)

        # Mark as failed
        analysis.status = ResumeAnalysis.STATUS_FAILED
        analysis.pipeline_step = ResumeAnalysis.STEP_FAILED
        analysis.error_message = 'Cancelled by user.'
        analysis.save(update_fields=['status', 'pipeline_step', 'error_message'])

        # Refund credits
        if analysis.credits_deducted:
            refund_credits(
                request.user, 'resume_analysis',
                description=f'Refund: analysis #{analysis.id} cancelled by user',
                reference_id=str(analysis.id),
            )
            analysis.credits_deducted = False
            analysis.save(update_fields=['credits_deducted'])

        cache.delete(f'analysis_status:{request.user.id}:{pk}')

        return Response({
            'id': analysis.id,
            'status': analysis.status,
            'detail': 'Analysis cancelled and credits refunded.',
        })


# ── Bulk delete analyses ─────────────────────────────────────────────────────


class AnalysisBulkDeleteView(APIView):
    """
    POST /api/v1/analyses/bulk-delete/
    Soft-delete multiple analyses at once.
    Body: {"ids": [1, 2, 3]}
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request):
        ids = request.data.get('ids', [])
        if not isinstance(ids, list) or not ids:
            return Response(
                {'detail': 'Provide a non-empty list of analysis IDs in "ids".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(ids) > 50:
            return Response(
                {'detail': 'Cannot delete more than 50 analyses at once.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        analyses = ResumeAnalysis.objects.filter(
            pk__in=ids, user=request.user, deleted_at__isnull=True,
        )
        deleted_count = 0
        for analysis in analyses:
            analysis.soft_delete()
            cache.delete(f'analysis_status:{request.user.id}:{analysis.id}')
            deleted_count += 1

        logger.info('Bulk soft-deleted %d analyses for user=%s', deleted_count, request.user.id)
        return Response({
            'deleted': deleted_count,
            'requested': len(ids),
        })


# ── Export analysis as JSON ──────────────────────────────────────────────────


class AnalysisExportJSONView(APIView):
    """
    GET /api/v1/analyses/<id>/export-json/
    Download the full analysis data as a JSON file.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.select_related(
                'scrape_result', 'llm_response',
            ).get(pk=pk, user=request.user)
        except ResumeAnalysis.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if analysis.status != ResumeAnalysis.STATUS_DONE:
            return Response(
                {'detail': 'Analysis must be complete to export.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ResumeAnalysisDetailSerializer(analysis, context={'request': request})

        import json
        from django.http import HttpResponse
        json_bytes = json.dumps(serializer.data, indent=2, default=str).encode('utf-8')

        role_slug = (analysis.jd_role or 'analysis').replace(' ', '_')[:30]
        filename = f'analysis_{role_slug}_{analysis.pk}.json'

        response = HttpResponse(json_bytes, content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# ── Account data export (GDPR) ──────────────────────────────────────────────


class AccountDataExportView(APIView):
    """
    GET /api/v1/account/export/
    Download all user data as a JSON file (GDPR compliance).
    Includes profile, analyses, resumes, wallet, notifications.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def get(self, request):
        import json
        from django.http import HttpResponse
        from accounts.models import WalletTransaction, ConsentLog

        user = request.user

        # Profile data
        profile = getattr(user, 'profile', None)
        profile_data = {
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'date_joined': str(user.date_joined),
            'last_login': str(user.last_login) if user.last_login else None,
        }
        if profile:
            profile_data.update({
                'country_code': profile.country_code,
                'mobile_number': profile.mobile_number,
                'plan': profile.plan.name if profile.plan else 'Free',
                'auth_provider': profile.auth_provider,
                'agreed_to_terms': profile.agreed_to_terms,
                'agreed_to_data_usage': profile.agreed_to_data_usage,
                'marketing_opt_in': profile.marketing_opt_in,
            })

        # Analyses (metadata only, no heavy text fields)
        analyses = list(
            ResumeAnalysis.all_objects.filter(user=user).values(
                'id', 'jd_role', 'jd_company', 'jd_industry', 'status',
                'overall_grade', 'ats_score', 'created_at', 'deleted_at',
            )
        )

        # Resumes
        resumes = list(
            Resume.objects.filter(user=user).values(
                'id', 'original_filename', 'file_size_bytes', 'uploaded_at',
            )
        )

        # Wallet transactions
        try:
            wallet = user.wallet
            transactions = list(
                WalletTransaction.objects.filter(wallet=wallet).values(
                    'amount', 'balance_after', 'transaction_type',
                    'description', 'created_at',
                )
            )
            wallet_data = {
                'balance': wallet.balance,
                'transactions': transactions,
            }
        except Exception:
            wallet_data = {'balance': 0, 'transactions': []}

        # Consent logs
        consents = list(
            ConsentLog.objects.filter(user=user).values(
                'consent_type', 'agreed', 'version', 'created_at',
            )
        )

        # Notifications
        notifications = list(
            Notification.objects.filter(user=user).values(
                'title', 'body', 'notification_type', 'is_read', 'created_at',
            )
        )

        export_data = {
            'export_date': str(timezone.now()),
            'profile': profile_data,
            'analyses': analyses,
            'resumes': resumes,
            'wallet': wallet_data,
            'consent_logs': consents,
            'notifications': notifications,
        }

        json_bytes = json.dumps(export_data, indent=2, default=str).encode('utf-8')
        response = HttpResponse(json_bytes, content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="i-luffy-data-export-{user.username}.json"'
        return response


# ── Generated resume delete ──────────────────────────────────────────────────


class GeneratedResumeDeleteView(APIView):
    """
    DELETE /api/v1/generated-resumes/<uuid:pk>/
    Delete a generated resume owned by the authenticated user.
    Removes the file from R2 storage.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def delete(self, request, pk):
        try:
            gen = GeneratedResume.objects.get(pk=pk, user=request.user)
        except GeneratedResume.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Delete file from R2
        if gen.file:
            try:
                gen.file.delete(save=False)
            except Exception:
                logger.warning('Failed to delete generated resume file: %s', gen.pk)

        gen.delete()
        logger.info('Generated resume deleted: id=%s user=%s', pk, request.user.id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Bulk delete resumes ──────────────────────────────────────────────────────


class ResumeBulkDeleteView(APIView):
    """
    POST /api/v1/resumes/bulk-delete/
    Delete multiple resumes at once.
    Body: {"ids": ["uuid1", "uuid2", ...]}
    Only deletes resumes with no active analyses or job alerts referencing them.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request):
        ids = request.data.get('ids', [])
        if not isinstance(ids, list) or not ids:
            return Response(
                {'detail': 'Provide a non-empty list of resume IDs in "ids".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(ids) > 50:
            return Response(
                {'detail': 'Maximum 50 resumes per request.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resumes = Resume.objects.filter(pk__in=ids, user=request.user)
        found = resumes.count()

        deleted = 0
        skipped = []
        for resume in resumes:
            # Check active analyses
            active_count = ResumeAnalysis.objects.filter(resume=resume).count()
            if active_count > 0:
                skipped.append({
                    'id': str(resume.pk),
                    'reason': f'{active_count} active analysis(es) reference this resume',
                })
                continue

            # Check active job alerts
            alert_count = JobAlert.objects.filter(resume=resume, is_active=True).count()
            if alert_count > 0:
                skipped.append({
                    'id': str(resume.pk),
                    'reason': f'{alert_count} active job alert(s) reference this resume',
                })
                continue

            resume.delete()
            deleted += 1

        return Response({
            'deleted': deleted,
            'skipped': skipped,
            'not_found': len(ids) - found,
        })


# ── Comparison endpoint ──────────────────────────────────────────────────────


class AnalysisCompareView(APIView):
    """
    GET /api/v1/analyses/compare/?ids=1,2
    Compare two or more analyses side-by-side.
    Returns full detail for each analysis.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        ids_param = request.query_params.get('ids', '')
        try:
            ids = [int(x.strip()) for x in ids_param.split(',') if x.strip()]
        except ValueError:
            return Response(
                {'detail': 'ids must be comma-separated integers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(ids) < 2:
            return Response(
                {'detail': 'Provide at least 2 analysis IDs to compare.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(ids) > 5:
            return Response(
                {'detail': 'Maximum 5 analyses per comparison.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        analyses = (
            ResumeAnalysis.objects
            .filter(pk__in=ids, user=request.user)
            .select_related('scrape_result', 'llm_response')
        )
        if analyses.count() != len(ids):
            return Response(
                {'detail': 'One or more analyses not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ResumeAnalysisDetailSerializer(analyses, many=True)
        return Response({
            'count': len(ids),
            'analyses': serializer.data,
        })


# ── Share score summary ──────────────────────────────────────────────────────


class SharedAnalysisSummaryView(APIView):
    """
    GET /api/v1/shared/<uuid:token>/summary/
    Lightweight public summary of a shared analysis — for social card previews.
    Returns only score, grade, and role (no PII).
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        try:
            analysis = ResumeAnalysis.objects.get(share_token=token)
        except ResumeAnalysis.DoesNotExist:
            return Response(
                {'detail': 'Shared analysis not found or link has been revoked.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            'ats_score': analysis.ats_score,
            'overall_grade': analysis.overall_grade,
            'jd_role': analysis.jd_role,
            'jd_company': analysis.jd_company,
            'scores': analysis.scores,
            'summary': analysis.summary,
        })


# ── Resume Version History ───────────────────────────────────────────────────


class ResumeVersionHistoryView(APIView):
    """
    GET /api/v1/resumes/<uuid:pk>/versions/
    Returns the version history for a specific resume, including ATS score progression.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        try:
            resume = Resume.objects.get(id=pk, user=request.user)
        except Resume.DoesNotExist:
            return Response(
                {'detail': 'Resume not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get the version chain — follow previous_resume links
        versions = []
        seen_ids = set()
        current = resume

        while current and current.id not in seen_ids:
            seen_ids.add(current.id)
            version = ResumeVersion.objects.filter(
                user=request.user, resume=current,
            ).first()

            # Get best analysis for this version
            best_analysis = ResumeAnalysis.objects.filter(
                resume=current, user=request.user,
                deleted_at__isnull=True, status='done',
            ).order_by('-ats_score').first()

            # Update best scores on the version entry if needed
            if version and best_analysis:
                updated = False
                if best_analysis.ats_score and (not version.best_ats_score or best_analysis.ats_score > version.best_ats_score):
                    version.best_ats_score = best_analysis.ats_score
                    updated = True
                if best_analysis.overall_grade and (not version.best_grade or best_analysis.overall_grade < version.best_grade):
                    version.best_grade = best_analysis.overall_grade
                    updated = True
                if updated:
                    version.save(update_fields=['best_ats_score', 'best_grade'])

            if version:
                versions.append(version)

            # Follow the previous link
            if version and version.previous_resume:
                current = version.previous_resume
            else:
                break

        serializer = ResumeVersionSerializer(versions, many=True)
        return Response({
            'resume_id': str(resume.id),
            'filename': resume.original_filename,
            'total_versions': len(versions),
            'versions': serializer.data,
        })


# ── Bulk Analysis ────────────────────────────────────────────────────────────


class BulkAnalyzeView(APIView):
    """
    POST /api/v1/analyze/bulk/
    Analyze one resume against multiple job descriptions (up to 10).
    Creates separate analysis entries for each JD.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [AnalyzeThrottle]

    def post(self, request):
        serializer = BulkAnalysisCreateSerializer(
            data=request.data,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        jd_list = serializer.validated_data['job_descriptions']
        total_count = len(jd_list)

        # ── Plan quota checks ──
        profile = getattr(request.user, 'profile', None)
        plan = getattr(profile, 'plan', None) if profile else None

        if plan and plan.analyses_per_month > 0:
            month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_count = ResumeAnalysis.objects.filter(
                user=request.user, created_at__gte=month_start,
            ).exclude(status=ResumeAnalysis.STATUS_FAILED).count()
            remaining = plan.analyses_per_month - month_count
            if remaining < total_count:
                return Response(
                    {
                        'detail': f'Monthly analysis limit allows only {remaining} more analyses. Requested {total_count}.',
                        'limit': plan.analyses_per_month,
                        'used': month_count,
                        'requested': total_count,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # ── Check total credit balance ──
        balance = check_balance(request.user)
        from accounts.models import CreditCost
        cost_per = CreditCost.objects.filter(action='resume_analysis').first()
        cost_each = cost_per.cost if cost_per else 1
        total_cost = cost_each * total_count
        if balance < total_cost:
            return Response(
                {
                    'detail': f'Insufficient credits for {total_count} analyses.',
                    'balance': balance,
                    'total_cost': total_cost,
                    'cost_per_analysis': cost_each,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        # ── Resolve resume ──
        resume_file = serializer.validated_data.get('resume_file')
        resume_id = serializer.validated_data.get('resume_id')

        if resume_id:
            try:
                resume_obj = Resume.objects.get(id=resume_id, user=request.user)
            except Resume.DoesNotExist:
                return Response(
                    {'detail': 'Resume not found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
        elif resume_file:
            resume_obj, _ = Resume.get_or_create_from_upload(request.user, resume_file)
        else:
            return Response(
                {'detail': 'Resume is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Create analyses ──
        created_analyses = []
        for jd in jd_list:
            try:
                credit_result = deduct_credits(
                    request.user,
                    'resume_analysis',
                    description=f'Bulk analysis: {jd.get("jd_role", "Untitled")}',
                )
            except InsufficientCreditsError as e:
                break

            analysis = ResumeAnalysis.objects.create(
                user=request.user,
                resume_file=resume_obj.file.name,
                resume=resume_obj,
                jd_input_type=jd.get('jd_input_type', 'text'),
                jd_text=jd.get('jd_text', ''),
                jd_url=jd.get('jd_url', ''),
                jd_role=jd.get('jd_role', ''),
                jd_company=jd.get('jd_company', ''),
                jd_skills=jd.get('jd_skills', ''),
                jd_experience_years=jd.get('jd_experience_years'),
                jd_industry=jd.get('jd_industry', ''),
                jd_extra_details=jd.get('jd_extra_details', ''),
                status=ResumeAnalysis.STATUS_PROCESSING,
                credits_deducted=True,
            )

            run_analysis_task.delay(analysis.id, request.user.id)
            created_analyses.append({
                'id': analysis.id,
                'jd_role': analysis.jd_role,
                'jd_company': analysis.jd_company,
                'status': analysis.status,
                'credits_used': credit_result['cost'],
            })

        return Response({
            'total_requested': total_count,
            'total_created': len(created_analyses),
            'analyses': created_analyses,
        }, status=status.HTTP_202_ACCEPTED)


# ── Interview Prep ───────────────────────────────────────────────────────────


class InterviewPrepView(APIView):
    """
    POST /api/v1/analyses/<id>/interview-prep/  — Generate interview prep (free)
    GET  /api/v1/analyses/<id>/interview-prep/  — Get latest interview prep status
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def get(self, request, pk):
        """Return the latest interview prep for this analysis."""
        prep = InterviewPrep.objects.filter(
            analysis_id=pk, user=request.user,
        ).order_by('-created_at').first()

        if not prep:
            return Response(
                {'detail': 'No interview prep found for this analysis.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(InterviewPrepSerializer(prep).data)

    def post(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.select_related('resume').get(
                id=pk, user=request.user,
            )
        except ResumeAnalysis.DoesNotExist:
            return Response(
                {'detail': 'Analysis not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if analysis.status != ResumeAnalysis.STATUS_DONE:
            return Response(
                {'detail': 'Analysis must be complete before generating interview prep.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check for existing pending/processing
        existing = InterviewPrep.objects.filter(
            analysis=analysis,
            status__in=[InterviewPrep.STATUS_PENDING, InterviewPrep.STATUS_PROCESSING],
        ).first()
        if existing:
            return Response(
                InterviewPrepSerializer(existing).data,
                status=status.HTTP_200_OK,
            )

        prep = InterviewPrep.objects.create(
            analysis=analysis,
            user=request.user,
            status=InterviewPrep.STATUS_PROCESSING,
            credits_deducted=False,
        )

        generate_interview_prep_task.delay(str(prep.id), request.user.id)

        from .models import UserActivity
        UserActivity.record(request.user, UserActivity.ACTION_INTERVIEW_PREP)

        return Response({
            'id': str(prep.id),
            'status': prep.status,
        }, status=status.HTTP_202_ACCEPTED)


class InterviewPrepStatusView(APIView):
    """
    GET /api/v1/analyses/<id>/interview-prep/
    Get the latest interview prep for an analysis.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        prep = InterviewPrep.objects.filter(
            analysis_id=pk, user=request.user,
        ).order_by('-created_at').first()

        if not prep:
            return Response(
                {'detail': 'No interview prep found for this analysis.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(InterviewPrepSerializer(prep).data)


class InterviewPrepListView(ListAPIView):
    """
    GET /api/v1/interview-preps/
    List all interview preps for the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = InterviewPrepSerializer

    def get_queryset(self):
        return InterviewPrep.objects.filter(user=self.request.user)


# ── Cover Letter ─────────────────────────────────────────────────────────────


class CoverLetterView(APIView):
    """
    POST /api/v1/analyses/<id>/cover-letter/  — Generate cover letter (1 credit)
    GET  /api/v1/analyses/<id>/cover-letter/  — Get latest cover letter status
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def get(self, request, pk):
        """Return the latest cover letter for this analysis."""
        cover_letter = CoverLetter.objects.filter(
            analysis_id=pk, user=request.user,
        ).order_by('-created_at').first()

        if not cover_letter:
            return Response(
                {'detail': 'No cover letter found for this analysis.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(CoverLetterSerializer(cover_letter).data)

    def post(self, request, pk):
        try:
            analysis = ResumeAnalysis.objects.select_related('resume').get(
                id=pk, user=request.user,
            )
        except ResumeAnalysis.DoesNotExist:
            return Response(
                {'detail': 'Analysis not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if analysis.status != ResumeAnalysis.STATUS_DONE:
            return Response(
                {'detail': 'Analysis must be complete before generating a cover letter.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CoverLetterCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        tone = serializer.validated_data.get('tone', 'professional')

        # Check for existing pending/processing
        existing = CoverLetter.objects.filter(
            analysis=analysis, tone=tone,
            status__in=[CoverLetter.STATUS_PENDING, CoverLetter.STATUS_PROCESSING],
        ).first()
        if existing:
            return Response(
                CoverLetterSerializer(existing).data,
                status=status.HTTP_200_OK,
            )

        cover_letter = CoverLetter.objects.create(
            analysis=analysis,
            user=request.user,
            tone=tone,
            status=CoverLetter.STATUS_PROCESSING,
            credits_deducted=False,
        )

        generate_cover_letter_task.delay(str(cover_letter.id), request.user.id)

        from .models import UserActivity
        UserActivity.record(request.user, UserActivity.ACTION_COVER_LETTER)

        return Response({
            'id': str(cover_letter.id),
            'status': cover_letter.status,
            'tone': tone,
        }, status=status.HTTP_202_ACCEPTED)


class CoverLetterStatusView(APIView):
    """
    GET /api/v1/analyses/<id>/cover-letter/
    Get the latest cover letter for an analysis.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        cover_letter = CoverLetter.objects.filter(
            analysis_id=pk, user=request.user,
        ).order_by('-created_at').first()

        if not cover_letter:
            return Response(
                {'detail': 'No cover letter found for this analysis.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(CoverLetterSerializer(cover_letter).data)


class CoverLetterListView(ListAPIView):
    """
    GET /api/v1/cover-letters/
    List all cover letters for the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = CoverLetterSerializer

    def get_queryset(self):
        return CoverLetter.objects.filter(user=self.request.user)


# ── Resume Templates ─────────────────────────────────────────────────────


class TemplateListView(ListAPIView):
    """
    GET /api/v1/templates/
    List all active resume templates with access info for the requesting user.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = ResumeTemplateSerializer

    def get_queryset(self):
        return ResumeTemplate.objects.filter(is_active=True)

