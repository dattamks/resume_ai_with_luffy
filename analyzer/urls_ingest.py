"""
URL routes for the Crawler Bot Ingest API.

All endpoints live under ``/api/v1/ingest/`` and require the
``X-Crawler-Key`` header for authentication.
"""

from django.urls import path

from .views_ingest import (
    CompanyIngestView, CompanyBulkIngestView,
    CompanyEntityIngestView, CompanyEntityBulkIngestView,
    CareerPageIngestView,
    JobIngestView, JobBulkIngestView,
    CrawlSourceListView, CrawlSourceUpdateView,
    IngestPingView,
)

urlpatterns = [
    # Health / auth check
    path('ping/', IngestPingView.as_view(), name='ingest-ping'),

    # Companies
    path('companies/', CompanyIngestView.as_view(), name='ingest-companies'),
    path('companies/bulk/', CompanyBulkIngestView.as_view(), name='ingest-companies-bulk'),

    # Company Entities
    path('entities/', CompanyEntityIngestView.as_view(), name='ingest-entities'),
    path('entities/bulk/', CompanyEntityBulkIngestView.as_view(), name='ingest-entities-bulk'),

    # Career Pages
    path('career-pages/', CareerPageIngestView.as_view(), name='ingest-career-pages'),

    # Jobs
    path('jobs/', JobIngestView.as_view(), name='ingest-jobs'),
    path('jobs/bulk/', JobBulkIngestView.as_view(), name='ingest-jobs-bulk'),

    # Crawl Sources
    path('crawl-sources/', CrawlSourceListView.as_view(), name='ingest-crawl-sources'),
    path('crawl-sources/<uuid:pk>/', CrawlSourceUpdateView.as_view(), name='ingest-crawl-source-update'),
]
