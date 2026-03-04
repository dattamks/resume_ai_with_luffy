"""
Feed & analytics URL routes.

Mounted under ``/api/v1/feed/`` and ``/api/v1/dashboard/`` in the
root URL configuration.
"""
from django.urls import path

from .views_feed import (
    DashboardActivityView,
    DashboardActivityHistoryView,
    DashboardMarketInsightsView,
    DashboardSkillGapView,
    FeedHubView,
    FeedInsightsView,
    FeedJobsView,
    FeedNewsDetailView,
    FeedNewsListView,
    FeedOnboardingView,
    FeedRecommendationsView,
    FeedTrendingSkillsView,
)

# /api/v1/feed/
feed_urlpatterns = [
    path('jobs/', FeedJobsView.as_view(), name='feed-jobs'),
    path('insights/', FeedInsightsView.as_view(), name='feed-insights'),
    path('trending-skills/', FeedTrendingSkillsView.as_view(), name='feed-trending-skills'),
    path('hub/', FeedHubView.as_view(), name='feed-hub'),
    path('recommendations/', FeedRecommendationsView.as_view(), name='feed-recommendations'),
    path('onboarding/', FeedOnboardingView.as_view(), name='feed-onboarding'),
    path('news/', FeedNewsListView.as_view(), name='feed-news'),
    path('news/<uuid:pk>/', FeedNewsDetailView.as_view(), name='feed-news-detail'),
]

# /api/v1/dashboard/ (extras — existing stats endpoint is in analyzer/urls.py)
dashboard_extra_urlpatterns = [
    path('skill-gap/', DashboardSkillGapView.as_view(), name='dashboard-skill-gap'),
    path('market-insights/', DashboardMarketInsightsView.as_view(), name='dashboard-market-insights'),
    path('activity/', DashboardActivityView.as_view(), name='dashboard-activity'),
    path('activity/history/', DashboardActivityHistoryView.as_view(), name='dashboard-activity-history'),
]
