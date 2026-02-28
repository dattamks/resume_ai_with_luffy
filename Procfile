web: gunicorn resume_ai.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 110
worker: celery -A resume_ai worker -l info --concurrency=2 --max-tasks-per-child=50
beat: celery -A resume_ai beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
flower: celery -A resume_ai flower --port=${PORT:-5555} --basic-auth=${FLOWER_USER:-admin}:${FLOWER_PASSWORD:-changeme} --broker_api= --persistent=True --db=/tmp/flower.db
