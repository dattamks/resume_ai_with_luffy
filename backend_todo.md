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
- [x] Run `migrate` on Railway via build command

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
- [x] Celery for async analysis pipeline (replaces threading) — implemented with Redis broker, auto-retry, acks_late, reject_on_worker_lost

## Phase 4 — Separate Frontend & Backend  ✅

### Backend (Django API service)

- [x] Remove `frontend_app` from `INSTALLED_APPS`
- [x] Remove catch-all `re_path` from `urls.py`
- [x] Remove `STATICFILES_DIRS` pointing to `frontend/dist`
- [x] Add `whitenoise` to serve Django's own static files (admin CSS)
- [x] Add `STATIC_ROOT = BASE_DIR / 'staticfiles'`
- [x] Add `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` (Railway terminates SSL)
- [x] Set `CORS_ALLOWED_ORIGINS` to the frontend Railway URL
- [x] Create `Procfile`: `web: gunicorn resume_ai.wsgi --bind 0.0.0.0:$PORT --workers 3`
- [x] Create `runtime.txt`: `python-3.12.x`
- [x] Add `gunicorn` to requirements.txt
- [x] Add health check endpoint at `/api/health/`

### Frontend (React SPA service)

- [x] Change `api/client.js` baseURL from `/api` to `import.meta.env.VITE_API_URL || '/api'`
- [x] Create `frontend/.env.production` with `VITE_API_URL=https://<backend>.up.railway.app/api`
- [x] Add `frontend/Dockerfile` or `nixpacks.toml` for static build + serve
- [x] Railway service: Nixpacks Node build → serves `dist/` as static site
- [x] Remove Vite proxy config for production (keep for local dev)

## Phase 5 — Production Hardening

- [x] Enforce `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` when `DEBUG=False`
- [x] Set `ALLOWED_HOSTS` to Railway domain
- [x] Ensure `collectstatic` runs in Railway build command
- [x] Configure logging to stdout (Railway captures logs automatically)
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

---

## Phase 6 — Performance & Security Optimizations

### Critical

- [x] **Pagination** — `AnalysisListView` returns ALL analyses with no pagination. Add `PageNumberPagination` + `PAGE_SIZE=20`.
- [x] **Status cache user scoping** — `AnalysisStatusView` caches as `analysis_status:{pk}` (no user). User B can see User A's status from Redis. Key by `analysis_status:{user_id}:{pk}`.

### High — Query & DB

- [x] **`select_related` on detail view** — `AnalysisDetailView` fires 3 queries (analysis + scrape_result FK + llm_response FK). Add `.select_related('scrape_result', 'llm_response')`.
- [x] **DB indexes on `ResumeAnalysis`** — No indexes → full table scans. Add `(user, -created_at)` and `(status, updated_at)`.
- [x] **Reduce pipeline `save()` calls** — ~10 `save()` per pipeline run. Combine pre-step `pipeline_step` write with post-step data write.

### High — Serializer Payload

- [x] **Exclude `prompt_sent` / `raw_response`** — `LLMResponseSerializer` sends ~160KB of text the frontend doesn't need.
- [x] **Exclude `markdown` / `json_data`** from `ScrapeResultSerializer` — raw scrape data not needed by frontend.

### High — Celery & LLM

- [x] **OpenRouter timeout** — No `timeout` on API call. Hung call blocks worker until 10 min hard limit.
- [x] **Celery retry scope** — Only retries `ConnectionError`. Add `TimeoutError`, `OSError`.
- [x] **`acks_late` + `reject_on_worker_lost`** — Worker crash = lost message. Add `reject_on_worker_lost=True`.
- [x] **Idempotency guard** — Double-click dispatches two concurrent tasks. Use Redis lock.

### Medium

- [x] **Replace all `print()` with `logger.debug()`** — ~30+ print statements leak internal state to stdout.
- [x] **Fix `LogoutView` bare `except Exception`** — Catch `TokenError` specifically instead.
- [x] **Redundant system prompt** — "Return ONLY valid JSON" in both system message and user prompt.
- [x] **Use Firecrawl `summary`** for LLM prompt instead of full markdown (already fetched, never used).

---

## Phase 7 — Resume Model, Soft-Delete & Dashboard Analytics  ✅

> **Goal:** Separate resume storage from analysis lifecycle, enable audit-trail analytics, and clean up orphaned files.

### 7.1 New `Resume` Model (deduplication)

- [x] Create `Resume` model: `id` (UUID), `user` (FK → User), `file` (FileField → `resumes/`), `file_hash` (SHA-256, unique per user, `db_index=True`), `original_filename`, `file_size_bytes`, `uploaded_at`
- [x] Add `resume` FK (SET_NULL, null=True, blank=True) on `ResumeAnalysis` → `Resume`
- [x] Upload dedup logic: compute SHA-256 before save → if same hash exists for user, reuse existing `Resume` row
- [x] `post_delete` signal on `Resume` → delete file from R2
- [x] Data migration: create `Resume` rows from existing `resume_file` values, compute hashes, deduplicate, link back to analyses

### 7.2 Soft-Delete on `ResumeAnalysis`

- [x] Add `deleted_at` (DateTimeField, null=True, db_index=True) to `ResumeAnalysis`
- [x] Create `ActiveAnalysisManager` (default manager) — filters `deleted_at__isnull=True`
- [x] Add `all_objects = models.Manager()` for unfiltered access (admin, analytics)
- [x] Update `AnalysisDeleteView` → soft-delete: set `deleted_at=now()`, clear heavy fields (`resume_text`, `resolved_jd`), delete `report_pdf` from R2, delete orphaned `ScrapeResult` & `LLMResponse`
- [x] Keep lightweight metadata on soft-deleted rows: `ats_score`, `jd_role`, `jd_company`, `status`, `created_at`, `jd_input_type`
- [x] New compound indexes: `(user, deleted_at)`, `(user, status, -created_at)`

### 7.3 New API Endpoints

- [x] `GET /api/resumes/` — list user's deduplicated resumes (filename, size, upload date, analysis count)
- [x] `DELETE /api/resumes/<id>/` — delete a resume file from R2 (only if no active analyses reference it)
- [x] `GET /api/dashboard/stats/` — user-level analytics from soft-deleted + active rows:
  - Total analyses (all time, including deleted)
  - Active vs deleted count
  - Average ATS score (all time)
  - Score trend (last 10 analyses)
  - Top roles analyzed
  - Analyses per month (last 6 months)

### 7.4 Cleanup & Docs

- [x] Update `FRONTEND_API_GUIDE.md` with new endpoints, soft-delete behavior, and Resume schema
- [x] Update admin site to show soft-deleted analyses and Resume model
- [x] Add tests for: dedup upload, soft-delete, dashboard stats, resume list/delete, orphan cleanup
- [x] Run full test suite & migrate
