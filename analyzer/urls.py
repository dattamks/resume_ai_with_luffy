from django.urls import path

from .views import AnalyzeResumeView, AnalysisListView, AnalysisDetailView, RetryAnalysisView

urlpatterns = [
    path('analyze/', AnalyzeResumeView.as_view(), name='analyze'),
    path('analyses/', AnalysisListView.as_view(), name='analysis-list'),
    path('analyses/<int:pk>/', AnalysisDetailView.as_view(), name='analysis-detail'),
    path('analyses/<int:pk>/retry/', RetryAnalysisView.as_view(), name='analysis-retry'),
]
