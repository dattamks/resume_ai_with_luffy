"""
Celery application for resume_ai.

Uses Redis as both broker and result backend.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'resume_ai.settings')

app = Celery('resume_ai')

# Read config from Django settings, namespace='CELERY' means all Celery
# settings must be prefixed with CELERY_ in settings.py.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks.py in all installed apps.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Sanity-check task — prints its own request info."""
    print(f'Request: {self.request!r}')
