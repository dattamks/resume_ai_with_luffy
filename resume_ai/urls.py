import hmac

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponseForbidden

from analyzer.views_health import health_check
from analyzer.urls_feed import feed_urlpatterns, dashboard_extra_urlpatterns
from analyzer.urls_skills import skills_urlpatterns


def metrics_view(request):
    """
    Token-guarded Prometheus metrics endpoint.

    - If METRICS_TOKEN is set, require `Authorization: Bearer <token>`.
    - If it's unset, only serve metrics in DEBUG so business/operational
      metrics (token usage, payment failures, credit ops) aren't exposed to
      the public internet in production.
    """
    from django_prometheus.exports import ExportToDjangoView

    token = getattr(settings, 'METRICS_TOKEN', '')
    if token:
        provided = request.headers.get('Authorization', '')
        if not hmac.compare_digest(provided, f'Bearer {token}'):
            return HttpResponseForbidden('Forbidden')
    elif not settings.DEBUG:
        return HttpResponseForbidden('Metrics endpoint disabled. Set METRICS_TOKEN to enable.')
    return ExportToDjangoView(request)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/health/', health_check, name='health-check'),
    path('api/v1/auth/', include('accounts.urls')),
    path('api/v1/ingest/', include('analyzer.urls_ingest')),
    path('api/v1/feed/', include((feed_urlpatterns, 'feed'))),
    path('api/v1/dashboard/', include((dashboard_extra_urlpatterns, 'dashboard-extra'))),
    path('api/v1/skills/', include((skills_urlpatterns, 'skills'))),
    path('api/v1/', include('analyzer.urls')),
    path('metrics', metrics_view, name='prometheus-django-metrics'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
