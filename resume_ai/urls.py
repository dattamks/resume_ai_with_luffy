from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static

from analyzer.views_health import health_check
from frontend_app.views import FrontendAppView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health_check, name='health-check'),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('analyzer.urls')),
    # Catch-all: serve React for every non-api, non-admin, non-media route.
    # When the frontend is moved out, remove this line and the import above.
    re_path(r'^(?!api/|admin/|media/).*$', FrontendAppView.as_view(), name='frontend'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
