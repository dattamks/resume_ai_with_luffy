from django.urls import path

from .views import (
    AnalyzeResumeView, AnalysisListView, AnalysisDetailView,
    RetryAnalysisView, AnalysisDeleteView, AnalysisPDFExportView,
    AnalysisStatusView, ResumeListView, ResumeDeleteView,
    DashboardStatsView, AnalysisShareView, SharedAnalysisView,
    GenerateResumeView, GeneratedResumeStatusView,
    GeneratedResumeDownloadView, GeneratedResumeListView,
    # New endpoints
    AnalysisCancelView, AnalysisBulkDeleteView, AnalysisExportJSONView,
    AccountDataExportView,
    # Phase 11 — Smart Job Alerts
    JobAlertListCreateView, JobAlertDetailView,
    JobAlertMatchListView, JobAlertMatchFeedbackView, JobAlertManualRunView,
    # Phase 12 — Notifications
    NotificationListView, NotificationUnreadCountView, NotificationMarkReadView,
)

urlpatterns = [
    path('analyze/', AnalyzeResumeView.as_view(), name='analyze'),
    path('analyses/', AnalysisListView.as_view(), name='analysis-list'),
    path('analyses/<int:pk>/', AnalysisDetailView.as_view(), name='analysis-detail'),
    path('analyses/<int:pk>/status/', AnalysisStatusView.as_view(), name='analysis-status'),
    path('analyses/<int:pk>/retry/', RetryAnalysisView.as_view(), name='analysis-retry'),
    path('analyses/<int:pk>/delete/', AnalysisDeleteView.as_view(), name='analysis-delete'),
    path('analyses/<int:pk>/cancel/', AnalysisCancelView.as_view(), name='analysis-cancel'),
    path('analyses/<int:pk>/export-pdf/', AnalysisPDFExportView.as_view(), name='analysis-export-pdf'),
    path('analyses/<int:pk>/export-json/', AnalysisExportJSONView.as_view(), name='analysis-export-json'),
    path('analyses/<int:pk>/share/', AnalysisShareView.as_view(), name='analysis-share'),
    path('analyses/<int:pk>/generate-resume/', GenerateResumeView.as_view(), name='generate-resume'),
    path('analyses/<int:pk>/generated-resume/', GeneratedResumeStatusView.as_view(), name='generated-resume-status'),
    path('analyses/<int:pk>/generated-resume/download/', GeneratedResumeDownloadView.as_view(), name='generated-resume-download'),
    path('shared/<uuid:token>/', SharedAnalysisView.as_view(), name='shared-analysis'),
    path('resumes/', ResumeListView.as_view(), name='resume-list'),
    path('resumes/<uuid:pk>/', ResumeDeleteView.as_view(), name='resume-delete'),
    path('dashboard/stats/', DashboardStatsView.as_view(), name='dashboard-stats'),
    # Bulk operations
    path('analyses/bulk-delete/', AnalysisBulkDeleteView.as_view(), name='analysis-bulk-delete'),
    # Account data export (GDPR)
    path('account/export/', AccountDataExportView.as_view(), name='account-data-export'),
    # Generated resumes
    path('generated-resumes/', GeneratedResumeListView.as_view(), name='generated-resume-list'),
    # Phase 11 — Smart Job Alerts
    path('job-alerts/', JobAlertListCreateView.as_view(), name='job-alert-list-create'),
    path('job-alerts/<uuid:pk>/', JobAlertDetailView.as_view(), name='job-alert-detail'),
    path('job-alerts/<uuid:pk>/matches/', JobAlertMatchListView.as_view(), name='job-alert-matches'),
    path('job-alerts/<uuid:pk>/matches/<uuid:match_pk>/feedback/', JobAlertMatchFeedbackView.as_view(), name='job-alert-match-feedback'),
    path('job-alerts/<uuid:pk>/run/', JobAlertManualRunView.as_view(), name='job-alert-run'),
    # Phase 12 — Notifications
    path('notifications/', NotificationListView.as_view(), name='notification-list'),
    path('notifications/unread-count/', NotificationUnreadCountView.as_view(), name='notification-unread-count'),
    path('notifications/mark-read/', NotificationMarkReadView.as_view(), name='notification-mark-read'),
]
