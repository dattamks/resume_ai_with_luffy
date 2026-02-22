# Backend Deployment TODO — Railway.app

> Target: Django API + React SPA deployed as **separate Railway services**

## Architecture

```
┌─────────────┐     HTTPS      ┌──────────────┐
│  Frontend   │ ──────────────→ │   Backend    │
│  (Static)   │   VITE_API_URL  │  (Gunicorn)  │
│  React SPA  │                 │  Django DRF  │
└─────────────┘                 └──────┬───┬───┘
                                       │   │
                              ┌────────┘   └────────┐
                              ▼                      ▼
                     ┌──────────────┐      ┌──────────────┐
                     │  PostgreSQL  │      │    Redis     │
                     │  (Railway)   │      │  (Railway)   │
                     └──────────────┘      └──────────────┘

                     ┌──────────────┐
                     │ Cloudflare   │
                     │ R2 (files)   │
                     └──────────────┘
```

---

## Phase 1 — PostgreSQL  ✅

- [x] Add `psycopg2-binary` and `dj-database-url` to requirements.txt
- [x] Replace `DATABASES` block with `dj_database_url.config(default='sqlite:///db.sqlite3')`
- [x] Falls back to SQLite in local dev (no env var needed)
- [x] Env var: `DATABASE_URL=postgresql://user:pass@host:5432/dbname`
- [ ] Run `migrate` on Railway via build command

## Phase 2 — Cloudflare R2 (S3-compatible file storage)  ✅

- [x] Add `django-storages[boto3]` and `boto3` to requirements.txt
- [x] Configure `DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'`
- [x] Point at R2 endpoint (S3-compatible API)
- [x] Env vars: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`
- [x] Resume PDF uploads (`resumes/`) stored in R2 instead of local `media/`
- [x] PDF extractor reads file via `analysis.resume_file.url` (works with both local and R2)

## Phase 3 — Redis  ✅

- [x] Add `django-redis` to requirements.txt
- [x] Wire `CACHES` setting to Redis for DRF throttle state + general caching
- [x] Env var: `REDIS_URL=redis://host:6379/0`
- [ ] Optional future: Celery for async analysis pipeline (currently uses threading)

## Phase 4 — Separate Frontend & Backend

### Backend (Django API service)

- [ ] Remove `frontend_app` from `INSTALLED_APPS`
- [ ] Remove catch-all `re_path` from `urls.py`
- [ ] Remove `STATICFILES_DIRS` pointing to `frontend/dist`
- [ ] Add `whitenoise` to serve Django's own static files (admin CSS)
- [ ] Add `STATIC_ROOT = BASE_DIR / 'staticfiles'`
- [ ] Add `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` (Railway terminates SSL)
- [ ] Set `CORS_ALLOWED_ORIGINS` to the frontend Railway URL
- [ ] Create `Procfile`: `web: gunicorn resume_ai.wsgi --bind 0.0.0.0:$PORT --workers 3`
- [ ] Create `runtime.txt`: `python-3.12.x`
- [ ] Add `gunicorn` to requirements.txt
- [ ] Add health check endpoint at `/api/health/`

### Frontend (React SPA service)

- [ ] Change `api/client.js` baseURL from `/api` to `import.meta.env.VITE_API_URL || '/api'`
- [ ] Create `frontend/.env.production` with `VITE_API_URL=https://<backend>.up.railway.app/api`
- [ ] Add `frontend/Dockerfile` or `nixpacks.toml` for static build + serve
- [ ] Railway service: Nixpacks Node build → serves `dist/` as static site
- [ ] Remove Vite proxy config for production (keep for local dev)

## Phase 5 — Production Hardening

- [ ] Enforce `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` when `DEBUG=False`
- [ ] Set `ALLOWED_HOSTS` to Railway domain
- [ ] Ensure `collectstatic` runs in Railway build command
- [ ] Configure logging to stdout (Railway captures logs automatically)
- [ ] Verify rate limiting works with Redis-backed cache

---

## Env Vars Summary (Railway backend service)

```
SECRET_KEY=<random-64-char>
DEBUG=False
ALLOWED_HOSTS=<backend>.up.railway.app
CORS_ALLOWED_ORIGINS=https://<frontend>.up.railway.app
DATABASE_URL=<auto-injected by Railway Postgres plugin>
REDIS_URL=<auto-injected by Railway Redis plugin>
AWS_ACCESS_KEY_ID=<R2 key>
AWS_SECRET_ACCESS_KEY=<R2 secret>
AWS_STORAGE_BUCKET_NAME=resume-ai
AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
AI_PROVIDER=luffy
LUFFY_API_URL=<your-llm-endpoint>
LUFFY_API_KEY=<key>
FIRECRAWL_API_KEY=<key>
```

## Env Vars Summary (Railway frontend service)

```
VITE_API_URL=https://<backend>.up.railway.app/api
```
