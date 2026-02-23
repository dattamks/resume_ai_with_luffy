from django.urls import path

from .views import (
    AnalyzeResumeView, AnalysisListView, AnalysisDetailView,
    RetryAnalysisView, AnalysisDeleteView, AnalysisPDFExportView,
    AnalysisStatusView, ResumeListView, ResumeDeleteView,
    DashboardStatsView, AnalysisShareView, SharedAnalysisView,
    JobListCreateView, JobDetailView, JobRelevanceView,
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
    path('shared/<uuid:token>/', SharedAnalysisView.as_view(), name='shared-analysis'),
    path('resumes/', ResumeListView.as_view(), name='resume-list'),
    path('resumes/<uuid:pk>/', ResumeDeleteView.as_view(), name='resume-delete'),
    path('dashboard/stats/', DashboardStatsView.as_view(), name='dashboard-stats'),
    # Jobs
    path('jobs/', JobListCreateView.as_view(), name='job-list-create'),
    path('jobs/<uuid:pk>/', JobDetailView.as_view(), name='job-detail'),
    path('jobs/<uuid:pk>/relevant/', JobRelevanceView.as_view(), name='job-relevant',
         kwargs={'relevance': 'relevant'}),
    path('jobs/<uuid:pk>/irrelevant/', JobRelevanceView.as_view(), name='job-irrelevant',
         kwargs={'relevance': 'irrelevant'}),
]
