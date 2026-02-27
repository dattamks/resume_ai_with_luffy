#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Railway entrypoint — a single script that starts the correct process
# based on the SERVICE_TYPE environment variable.
#
# Each Railway service sets SERVICE_TYPE to one of: web, worker, beat
# ─────────────────────────────────────────────────────────────────────────────
set -e

case "${SERVICE_TYPE}" in
  web)
    echo "▶ Starting web service (gunicorn)…"
    # Use flock to prevent concurrent migration runs across replicas.
    # Only one replica acquires the lock; others wait (max 120s) then proceed.
    echo "▶ Running migrations (with lock)…"
    flock -w 120 /tmp/migrate.lock python manage.py migrate --noinput || true
    python manage.py seed_email_templates
    python manage.py seed_plans
    exec gunicorn resume_ai.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${GUNICORN_WORKERS:-2}" \
      --threads "${GUNICORN_THREADS:-2}" \
      --timeout "${GUNICORN_TIMEOUT:-120}"
    ;;

  worker)
    echo "▶ Starting Celery worker…"
    exec celery -A resume_ai worker \
      -l "${LOG_LEVEL:-info}" \
      --concurrency="${CELERY_CONCURRENCY:-2}" \
      --max-tasks-per-child="${CELERY_MAX_TASKS_PER_CHILD:-50}"
    ;;

  beat)
    echo "▶ Starting Celery beat scheduler…"
    exec celery -A resume_ai beat \
      -l "${LOG_LEVEL:-info}" \
      --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;

  *)
    echo "ERROR: SERVICE_TYPE must be one of: web, worker, beat"
    echo "       Got: '${SERVICE_TYPE}'"
    exit 1
    ;;
esac
