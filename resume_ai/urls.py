from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from analyzer.views_health import health_check
from analyzer.urls_feed import feed_urlpatterns, dashboard_extra_urlpatterns

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/health/', health_check, name='health-check'),
    path('api/v1/auth/', include('accounts.urls')),
    path('api/v1/ingest/', include('analyzer.urls_ingest')),
    path('api/v1/feed/', include((feed_urlpatterns, 'feed'))),
    path('api/v1/dashboard/', include((dashboard_extra_urlpatterns, 'dashboard-extra'))),
    path('api/v1/', include('analyzer.urls')),
    path('', include('django_prometheus.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
