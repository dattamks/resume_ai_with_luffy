import os
from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.views import View


class FrontendAppView(View):
    """
    Serves the built React app (frontend/dist/index.html) for all non-API routes.

    To detach the frontend:
      1. Remove this app from INSTALLED_APPS and re_path from urls.py.
      2. Deploy frontend/dist/ to any static host (Netlify, S3, etc.).
      3. Point VITE_API_BASE_URL in frontend/.env to the Django API URL.
    """

    INDEX_PATH = os.path.join(settings.BASE_DIR, 'frontend', 'dist', 'index.html')

    def get(self, request, *args, **kwargs):
        if not os.path.exists(self.INDEX_PATH):
            return HttpResponse(
                '<html><body>'
                '<h2>Frontend not built yet.</h2>'
                '<p>Run the following commands:</p>'
                '<pre>cd frontend\nnpm install\nnpm run build</pre>'
                '<p>Then restart Django.</p>'
                '</body></html>',
                status=503,
                content_type='text/html',
            )
        return FileResponse(open(self.INDEX_PATH, 'rb'), content_type='text/html')
