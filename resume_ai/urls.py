from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from analyzer.views_health import health_check

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health_check, name='health-check'),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('analyzer.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
