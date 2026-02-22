web: python manage.py migrate --noinput && gunicorn resume_ai.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 120
worker: celery -A resume_ai worker -l info --concurrency=2
beat: celery -A resume_ai beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
