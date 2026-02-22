import logging
import threading

from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
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
from .services.analyzer import ResumeAnalyzer

logger = logging.getLogger('analyzer')


def _run_analysis_in_background(analysis_id, user_id):
    """Run the analysis pipeline in a background thread."""
    import django
    django.db.connections.close_all()

    try:
        analysis = ResumeAnalysis.objects.get(id=analysis_id)
        analyzer = ResumeAnalyzer()
        print(f'[DEBUG] Background thread: starting analysis pipeline (id={analysis_id})')
        result = analyzer.run(analysis)
        print(f'[DEBUG] Background thread: ✅ analysis complete (id={analysis_id}, ATS={result.ats_score})')
    except ValueError as exc:
        print(f'[DEBUG] Background thread: ❌ ValueError: {exc}')
        logger.warning('Analysis failed (user=%s): %s', user_id, exc)
        try:
            analysis = ResumeAnalysis.objects.get(id=analysis_id)
            analysis.status = ResumeAnalysis.STATUS_FAILED
            analysis.pipeline_step = ResumeAnalysis.STEP_FAILED
            analysis.error_message = str(exc)
            analysis.save(update_fields=['status', 'pipeline_step', 'error_message'])
        except Exception:
            pass
    except Exception as exc:
        print(f'[DEBUG] Background thread: ❌ Unexpected error: {type(exc).__name__}: {exc}')
        logger.exception('Unexpected error during analysis (user=%s)', user_id)
        try:
            analysis = ResumeAnalysis.objects.get(id=analysis_id)
            analysis.status = ResumeAnalysis.STATUS_FAILED
            analysis.pipeline_step = ResumeAnalysis.STEP_FAILED
            analysis.error_message = str(exc)
            analysis.save(update_fields=['status', 'pipeline_step', 'error_message'])
        except Exception:
            pass


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

    def post(self, request):
        print(f'\n{"="*60}')
        print(f'[DEBUG] POST /api/analyze/ — user={request.user.username}')
        print(f'[DEBUG] Request data keys: {list(request.data.keys())}')
        print(f'[DEBUG] jd_input_type: {request.data.get("jd_input_type")}')
        if request.FILES.get('resume_file'):
            f = request.FILES['resume_file']
            print(f'[DEBUG] Resume file: {f.name} ({f.size} bytes)')
        print(f'{"="*60}')

        print('[DEBUG] Step: Validating request data...')
        serializer = ResumeAnalysisCreateSerializer(data=request.data)
        if not serializer.is_valid():
            print(f'[DEBUG] ❌ Validation FAILED: {serializer.errors}')
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        print('[DEBUG] ✅ Validation passed')

        analysis = serializer.save(user=request.user, status=ResumeAnalysis.STATUS_PROCESSING)
        print(f'[DEBUG] ✅ Analysis record created (id={analysis.id}, status=processing)')

        # Launch analysis in background thread — return immediately to avoid gateway timeout
        print(f'[DEBUG] Launching background thread for analysis id={analysis.id}')
        thread = threading.Thread(
            target=_run_analysis_in_background,
            args=(analysis.id, request.user.id),
            daemon=True,
        )
        thread.start()

        print(f'[DEBUG] ✅ Returning 202 Accepted (id={analysis.id})')
        print(f'{"="*60}\n')
        return Response(
            {'id': analysis.id, 'status': analysis.status},
            status=status.HTTP_202_ACCEPTED,
        )


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

        print(f'[DEBUG] Retrying analysis id={analysis.id} from step={analysis.pipeline_step}')

        # Reset status to processing but keep pipeline_step (so it resumes from there)
        analysis.status = ResumeAnalysis.STATUS_PROCESSING
        analysis.error_message = ''
        analysis.save(update_fields=['status', 'error_message'])

        thread = threading.Thread(
            target=_run_analysis_in_background,
            args=(analysis.id, request.user.id),
            daemon=True,
        )
        thread.start()

        return Response(
            {'id': analysis.id, 'status': analysis.status, 'pipeline_step': analysis.pipeline_step},
            status=status.HTTP_202_ACCEPTED,
        )


class AnalysisListView(ListAPIView):
    """
    GET /api/analyses/
    List all analyses for the authenticated user.
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
        return ResumeAnalysis.objects.filter(user=self.request.user)
