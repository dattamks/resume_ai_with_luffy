from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ResumeAnalysis
from .serializers import (
    ResumeAnalysisCreateSerializer,
    ResumeAnalysisDetailSerializer,
    ResumeAnalysisListSerializer,
)
from .services.analyzer import ResumeAnalyzer


class AnalyzeResumeView(APIView):
    """
    POST /api/analyze/
    Upload a PDF resume + job description input → returns full analysis.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = ResumeAnalysisCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        analysis = serializer.save(user=request.user, status=ResumeAnalysis.STATUS_PROCESSING)

        try:
            analyzer = ResumeAnalyzer()
            result = analyzer.run(analysis)
            detail = ResumeAnalysisDetailSerializer(result)
            return Response(detail.data, status=status.HTTP_201_CREATED)
        except Exception as exc:
            analysis.status = ResumeAnalysis.STATUS_FAILED
            analysis.error_message = str(exc)
            analysis.save(update_fields=['status', 'error_message'])
            return Response(
                {'detail': 'Analysis failed.', 'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AnalysisListView(ListAPIView):
    """
    GET /api/analyses/
    List all analyses for the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ResumeAnalysisListSerializer

    def get_queryset(self):
        return ResumeAnalysis.objects.filter(user=self.request.user)


class AnalysisDetailView(RetrieveAPIView):
    """
    GET /api/analyses/<id>/
    Retrieve full details of a single analysis.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ResumeAnalysisDetailSerializer

    def get_queryset(self):
        return ResumeAnalysis.objects.filter(user=self.request.user)
