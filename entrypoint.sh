#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Railway entrypoint — a single script that starts the correct process
# based on the SERVICE_TYPE environment variable.
#
# Each Railway service sets SERVICE_TYPE to one of: web, worker, beat
# ─────────────────────────────────────────────────────────────────────────────
set -e

# WeasyPrint (PDF generation) needs system libs installed via aptPkgs
# in nixpacks.toml. The Nix env doesn't search /usr/lib by default,
# so we add it to LD_LIBRARY_PATH at runtime (not build time).
export LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GDK_PIXBUF_MODULE_FILE="/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache"

case "${SERVICE_TYPE}" in
  web)
    echo "▶ Starting web service (gunicorn)…"
    python manage.py migrate --noinput
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
      --concurrency="${CELERY_CONCURRENCY:-2}"
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
