from django.urls import path

from .views import (
    AnalyzeResumeView, AnalysisListView, AnalysisDetailView,
    RetryAnalysisView, AnalysisDeleteView, AnalysisPDFExportView,
    AnalysisStatusView, ResumeListView, ResumeDeleteView,
    DashboardStatsView, AnalysisShareView, SharedAnalysisView,
    JobListCreateView, JobDetailView, JobRelevanceView,
    GenerateResumeView, GeneratedResumeStatusView,
    GeneratedResumeDownloadView, GeneratedResumeListView,
    # Phase 11 — Smart Job Alerts
    JobAlertListCreateView, JobAlertDetailView,
    JobAlertMatchListView, JobAlertMatchFeedbackView, JobAlertManualRunView,
)

urlpatterns = [
    path('analyze/', AnalyzeResumeView.as_view(), name='analyze'),
    path('analyses/', AnalysisListView.as_view(), name='analysis-list'),
    path('analyses/<int:pk>/', AnalysisDetailView.as_view(), name='analysis-detail'),
    path('analyses/<int:pk>/status/', AnalysisStatusView.as_view(), name='analysis-status'),
    path('analyses/<int:pk>/retry/', RetryAnalysisView.as_view(), name='analysis-retry'),
    path('analyses/<int:pk>/delete/', AnalysisDeleteView.as_view(), name='analysis-delete'),
    path('analyses/<int:pk>/export-pdf/', AnalysisPDFExportView.as_view(), name='analysis-export-pdf'),
    path('analyses/<int:pk>/share/', AnalysisShareView.as_view(), name='analysis-share'),
    path('analyses/<int:pk>/generate-resume/', GenerateResumeView.as_view(), name='generate-resume'),
    path('analyses/<int:pk>/generated-resume/', GeneratedResumeStatusView.as_view(), name='generated-resume-status'),
    path('analyses/<int:pk>/generated-resume/download/', GeneratedResumeDownloadView.as_view(), name='generated-resume-download'),
    path('shared/<uuid:token>/', SharedAnalysisView.as_view(), name='shared-analysis'),
    path('resumes/', ResumeListView.as_view(), name='resume-list'),
    path('resumes/<uuid:pk>/', ResumeDeleteView.as_view(), name='resume-delete'),
    path('dashboard/stats/', DashboardStatsView.as_view(), name='dashboard-stats'),
    # Manually tracked jobs (pre-existing)
    path('jobs/', JobListCreateView.as_view(), name='job-list-create'),
    path('jobs/<uuid:pk>/', JobDetailView.as_view(), name='job-detail'),
    path('jobs/<uuid:pk>/relevant/', JobRelevanceView.as_view(), name='job-relevant',
         kwargs={'relevance': 'relevant'}),
    path('jobs/<uuid:pk>/irrelevant/', JobRelevanceView.as_view(), name='job-irrelevant',
         kwargs={'relevance': 'irrelevant'}),
    # Generated resumes
    path('generated-resumes/', GeneratedResumeListView.as_view(), name='generated-resume-list'),
    # Phase 11 — Smart Job Alerts
    path('job-alerts/', JobAlertListCreateView.as_view(), name='job-alert-list-create'),
    path('job-alerts/<uuid:pk>/', JobAlertDetailView.as_view(), name='job-alert-detail'),
    path('job-alerts/<uuid:pk>/matches/', JobAlertMatchListView.as_view(), name='job-alert-matches'),
    path('job-alerts/<uuid:pk>/matches/<uuid:match_pk>/feedback/', JobAlertMatchFeedbackView.as_view(), name='job-alert-match-feedback'),
    path('job-alerts/<uuid:pk>/run/', JobAlertManualRunView.as_view(), name='job-alert-run'),
]
