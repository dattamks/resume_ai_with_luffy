# Backend TODO — i-Luffy

> Backend-only task tracker. Frontend tasks tracked separately.

---

## Completed Phases

<details>
<summary>Phase 1 — PostgreSQL ✅</summary>

- [x] `psycopg2-binary` + `dj-database-url`
- [x] `DATABASES` via `dj_database_url.config()` with SQLite fallback
- [x] Env var: `DATABASE_URL`
</details>

<details>
<summary>Phase 2 — Cloudflare R2 (S3 storage) ✅</summary>

- [x] `django-storages[boto3]` + `boto3`
- [x] R2 endpoint config, resume uploads to `resumes/`
- [x] PDF extractor reads via `.url` (local + R2)
</details>

<details>
<summary>Phase 3 — Redis + Celery ✅</summary>

- [x] `django-redis` for cache + throttle state
- [x] Celery with Redis broker, auto-retry, acks_late, reject_on_worker_lost
</details>

<details>
<summary>Phase 4 — Deployment (Railway) ✅</summary>

- [x] WhiteNoise, Gunicorn, `Procfile`, `runtime.txt`
- [x] CORS, SSL proxy header, health check endpoint
</details>

<details>
<summary>Phase 5 — Production Hardening ✅ (1 remaining)</summary>

- [x] SSL redirect, secure cookies, `ALLOWED_HOSTS`
- [x] `collectstatic` in build command, structured logging
- [ ] Verify rate limiting works with Redis-backed cache
</details>

<details>
<summary>Phase 6 — Performance & Security ✅</summary>

- [x] Pagination (20/page), status cache user scoping
- [x] `select_related` on detail, DB indexes
- [x] Exclude heavy fields from serializers (`prompt_sent`, `raw_response`, `markdown`, `json_data`)
- [x] OpenRouter timeout, Celery retry scope, idempotency guard
- [x] Replace `print()` with `logger`, fix bare `except`, deduplicate system prompt
</details>

<details>
<summary>Phase 7 — Resume Model, Soft-Delete & Dashboard ✅</summary>

- [x] `Resume` model with SHA-256 dedup, `post_delete` R2 cleanup
- [x] Soft-delete on `ResumeAnalysis` (keeps analytics metadata)
- [x] Resume list/delete endpoints, dashboard stats endpoint
- [x] Data migration, admin updates, tests
</details>

<details>
<summary>Phase 8 — User Profile, Notifications, Email ✅</summary>

- [x] `UserProfile` model (country_code, mobile_number) with auto-creation signal
- [x] `NotificationPreference` model (8 boolean toggles)
- [x] `EmailTemplate` model (DB-stored HTML templates, slug-based lookup)
- [x] `send_templated_email()` utility + 3 seeded templates (welcome, password-reset, password-changed)
- [x] Forgot/reset password endpoints with token-based flow
- [x] Notification preferences endpoint (GET/PUT)
- [x] SMTP config via env vars (Zoho)
</details>

---

## Phase 9 — Quick Wins (Backend Enhancements)

### Notification & Email

- [ ] **Respect notification preferences** — check `NotificationPreference` before sending emails (currently all emails fire unconditionally)
- [ ] **Analysis completion email** — send email when async analysis finishes (seed `analysis-complete` template, add 3 lines to `run_analysis_task`)
- [ ] **Weekly email digest** — Celery Beat task that sends score trends + tips using email templates

### Analysis Pipeline

- [ ] **Duplicate resume warning** — return a message in API response when `Resume.file_hash` matches an existing upload (dedup already works, just not communicated)
- [ ] **Cancel stuck analysis** — use stored `celery_task_id` to `revoke()` + mark as failed
- [ ] **Bulk delete analyses** — accept `{"ids": [1,2,3]}` and soft-delete in batch

### Dashboard & Analytics

- [ ] **Grade distribution** — add `grade_distribution` to `/dashboard/stats/` (group by `overall_grade`)
- [ ] **Industry breakdown** — add `top_industries` stat (same pattern as `top_roles`, group by `jd_industry`)
- [ ] **Per-ATS score trends** — extend `score_trend` to include `workday_ats`, `greenhouse_ats` alongside `generic_ats`
- [ ] **Show AI response time** — expose `LLMResponse.duration_seconds` in detail serializer

### Data & Compliance

- [ ] **Account data export (GDPR)** — endpoint to download all user data as ZIP (analyses JSON + resume PDFs from R2)
- [ ] **Export analysis as JSON** — downloadable raw analysis data via `GET /api/analyses/<id>/export-json/`

### Jobs Feature

- [ ] **Job match scoring** — when user creates a Job, auto-compare JD to their best resume via lightweight LLM prompt
- [ ] **Scheduled re-analysis** — Celery Beat task to rerun analysis weekly with same resume + JD (track improvement over time)

### Infrastructure

- [ ] Verify rate limiting works with Redis-backed cache (carried from Phase 5)

---

## Audit Backlog (Skipped / Deferred)

> Items from the Feb 2026 security & design audit that require larger feature work.

### Security

- [ ] **Email verification on registration (5.5)** — Set `user.is_active = False` until email link is clicked. Requires: verification token model/migration, send-verification endpoint, verify endpoint, resend endpoint, new email template, auth flow changes.

### Design — Plan Quota Enforcement (6.1)

- [ ] **Monthly analysis quota** — Check `plan.analyses_per_month` in `AnalyzeResumeView.post()` before creating analysis
- [ ] **Per-plan resume size limit** — Use `plan.max_resume_size_mb` instead of global `settings.MAX_RESUME_SIZE_MB` in `ResumeAnalysisCreateSerializer`
- [ ] **PDF export feature flag** — Check `plan.pdf_export` in `ExportPDFView`
- [ ] **Share analysis feature flag** — Check `plan.share_analysis` in `AnalysisShareView`
- [ ] **Job tracking feature flag** — Check `plan.job_tracking` in `JobCreateView`
- [ ] **Max resumes stored** — Check `plan.max_resumes_stored` before accepting new uploads

### Design — Other (6.2–6.10)

- [ ] **Structured logging improvements (6.2)** — Consistent log format with request IDs
- [ ] **Admin dashboard enhancements (6.3)** — Better admin views for Plan, UserProfile
- [ ] **Celery task monitoring (6.5)** — Flower or custom task status dashboard
- [ ] **API versioning (6.6)** — URL-based or header-based API versioning
- [ ] **Webhook notifications (6.7)** — Allow users to register webhook URLs for analysis completion
- [ ] **Rate limit headers (6.8)** — Return `X-RateLimit-*` headers in responses
- [ ] **Health check improvements (6.9)** — Check Redis, DB, R2 connectivity in health endpoint
- [ ] **Test coverage (6.10)** — Increase test coverage for edge cases, error paths

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
AWS_STORAGE_BUCKET_NAME=i-luffy
AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=<key>
FIRECRAWL_API_KEY=<key>
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtppro.zoho.in
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<zoho-email>
EMAIL_HOST_PASSWORD=<zoho-password>
DEFAULT_FROM_EMAIL=<zoho-email>
FRONTEND_URL=https://<frontend>.up.railway.app
```
