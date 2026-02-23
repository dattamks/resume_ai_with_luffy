from django.urls import path

from .views import (
    AnalyzeResumeView, AnalysisListView, AnalysisDetailView,
    RetryAnalysisView, AnalysisDeleteView, AnalysisPDFExportView,
    AnalysisStatusView, ResumeListView, ResumeDeleteView,
    DashboardStatsView,
)

urlpatterns = [
    path('analyze/', AnalyzeResumeView.as_view(), name='analyze'),
    path('analyses/', AnalysisListView.as_view(), name='analysis-list'),
    path('analyses/<int:pk>/', AnalysisDetailView.as_view(), name='analysis-detail'),
    path('analyses/<int:pk>/status/', AnalysisStatusView.as_view(), name='analysis-status'),
    path('analyses/<int:pk>/retry/', RetryAnalysisView.as_view(), name='analysis-retry'),
    path('analyses/<int:pk>/delete/', AnalysisDeleteView.as_view(), name='analysis-delete'),
    path('analyses/<int:pk>/export-pdf/', AnalysisPDFExportView.as_view(), name='analysis-export-pdf'),
    path('resumes/', ResumeListView.as_view(), name='resume-list'),
    path('resumes/<uuid:pk>/', ResumeDeleteView.as_view(), name='resume-delete'),
    path('dashboard/stats/', DashboardStatsView.as_view(), name='dashboard-stats'),
]
