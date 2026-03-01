from django.urls import path

from .views import (
    AnalyzeResumeView, AnalysisListView, AnalysisDetailView,
    RetryAnalysisView, AnalysisDeleteView, AnalysisPDFExportView,
    AnalysisStatusView, ResumeListView, ResumeDeleteView,
    DashboardStatsView, AnalysisShareView, SharedAnalysisView,
    GenerateResumeView, GeneratedResumeStatusView,
    GeneratedResumeDownloadView, GeneratedResumeListView,
    GeneratedResumeDeleteView,
    # New endpoints
    AnalysisCancelView, AnalysisBulkDeleteView, AnalysisExportJSONView,
    AccountDataExportView, ResumeBulkDeleteView, AnalysisCompareView,
    SharedAnalysisSummaryView,
    # Phase 11 — Smart Job Alerts
    JobAlertListCreateView, JobAlertDetailView,
    JobAlertMatchListView, JobAlertMatchFeedbackView, JobAlertManualRunView,
    # Phase 12 — Notifications
    NotificationListView, NotificationUnreadCountView, NotificationMarkReadView,
    # Phase 13 — New features
    ResumeVersionHistoryView, BulkAnalyzeView,
    InterviewPrepView, InterviewPrepStatusView, InterviewPrepListView,
    CoverLetterView, CoverLetterStatusView, CoverLetterListView,
    # Phase 14 — Resume Templates
    TemplateListView,
)
from .views_celery import (
    CeleryWorkersView, CeleryActiveTasksView, CeleryTaskStatusView,
    CeleryQueueLengthView,
)
from .views_chat import (
    ResumeChatStartView, ResumeChatListView, ResumeChatDetailView,
    ResumeChatSubmitView, ResumeChatFinalizeView, ResumeChatResumesView,
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
    # Comparison (must be before analyses/<int:pk>/ but Django int converter won't match 'compare' anyway)
    path('analyses/compare/', AnalysisCompareView.as_view(), name='analysis-compare'),
    # Account data export (GDPR)
    path('account/export/', AccountDataExportView.as_view(), name='account-data-export'),
    # Generated resumes
    path('generated-resumes/', GeneratedResumeListView.as_view(), name='generated-resume-list'),
    path('generated-resumes/<uuid:pk>/', GeneratedResumeDeleteView.as_view(), name='generated-resume-delete'),
    # Bulk operations — resumes
    path('resumes/bulk-delete/', ResumeBulkDeleteView.as_view(), name='resume-bulk-delete'),
    # Share summary (lightweight public endpoint)
    path('shared/<uuid:token>/summary/', SharedAnalysisSummaryView.as_view(), name='shared-analysis-summary'),
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
    # Phase 13 — Resume Version History
    path('resumes/<uuid:pk>/versions/', ResumeVersionHistoryView.as_view(), name='resume-version-history'),
    # Phase 13 — Bulk Analysis
    path('analyze/bulk/', BulkAnalyzeView.as_view(), name='analyze-bulk'),
    # Phase 13 — Interview Prep
    path('analyses/<int:pk>/interview-prep/', InterviewPrepView.as_view(), name='interview-prep'),
    path('interview-preps/', InterviewPrepListView.as_view(), name='interview-prep-list'),
    # Phase 13 — Cover Letter
    path('analyses/<int:pk>/cover-letter/', CoverLetterView.as_view(), name='cover-letter'),
    path('cover-letters/', CoverLetterListView.as_view(), name='cover-letter-list'),
    # Admin — Celery monitoring
    path('admin/celery/workers/', CeleryWorkersView.as_view(), name='celery-workers'),
    path('admin/celery/tasks/active/', CeleryActiveTasksView.as_view(), name='celery-active-tasks'),
    path('admin/celery/tasks/<str:task_id>/', CeleryTaskStatusView.as_view(), name='celery-task-status'),
    path('admin/celery/queues/', CeleryQueueLengthView.as_view(), name='celery-queues'),
    # Phase 14 — Resume Templates
    path('templates/', TemplateListView.as_view(), name='template-list'),
    # Phase 15 — Conversational Resume Builder
    path('resume-chat/start/', ResumeChatStartView.as_view(), name='resume-chat-start'),
    path('resume-chat/', ResumeChatListView.as_view(), name='resume-chat-list'),
    path('resume-chat/resumes/', ResumeChatResumesView.as_view(), name='resume-chat-resumes'),
    path('resume-chat/<uuid:pk>/', ResumeChatDetailView.as_view(), name='resume-chat-detail'),
    path('resume-chat/<uuid:pk>/submit/', ResumeChatSubmitView.as_view(), name='resume-chat-submit'),
    path('resume-chat/<uuid:pk>/finalize/', ResumeChatFinalizeView.as_view(), name='resume-chat-finalize'),
]
