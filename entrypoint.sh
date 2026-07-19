#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Railway entrypoint — a single script that starts the correct process
# based on the SERVICE_TYPE environment variable.
#
# Each Railway service sets SERVICE_TYPE to one of: web, worker, beat
# ─────────────────────────────────────────────────────────────────────────────
set -e

# Playwright browser path — must match where `playwright install chromium` put browsers.
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/root/.cache/ms-playwright}"

case "${SERVICE_TYPE}" in
  web)
    echo "▶ Starting web service (gunicorn)…"
    # Use flock to prevent concurrent migration runs across replicas.
    # Only one replica acquires the lock; others wait (max 120s) then proceed.
    # A failed migration must abort the boot — starting gunicorn against a
    # half-migrated schema causes silent, hard-to-debug 500s.
    echo "▶ Running migrations (with lock)…"
    flock -w 120 /tmp/migrate.lock python manage.py migrate --noinput
    python manage.py seed_email_templates
    python manage.py seed_plans
    python manage.py seed_credit_costs
    exec gunicorn resume_ai.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${GUNICORN_WORKERS:-2}" \
      --threads "${GUNICORN_THREADS:-2}" \
      --timeout "${GUNICORN_TIMEOUT:-110}"
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

  flower)
    echo "▶ Starting Flower monitoring dashboard…"
    if [ -z "${FLOWER_PASSWORD}" ]; then
      echo "ERROR: FLOWER_PASSWORD must be set — refusing to start Flower with a default password."
      exit 1
    fi
    exec celery -A resume_ai flower \
      --port="${PORT:-5555}" \
      --basic-auth="${FLOWER_USER:-admin}:${FLOWER_PASSWORD}" \
      --broker_api= \
      --persistent=True \
      --db=/tmp/flower.db
    ;;

  *)
    echo "ERROR: SERVICE_TYPE must be one of: web, worker, beat, flower"
    echo "       Got: '${SERVICE_TYPE}'"
    exit 1
    ;;
esac
