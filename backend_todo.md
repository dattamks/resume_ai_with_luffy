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

<details>
<summary>Phase 9 — Plans & Wallet (Credits System) ✅</summary>

- [x] `Wallet` model (OneToOne User, PositiveIntegerField balance)
- [x] `WalletTransaction` model (append-only audit log: plan_credit, topup, analysis_debit, refund, admin_adjustment, upgrade_bonus)
- [x] `CreditCost` model (admin-managed per-action costs, e.g. resume_analysis = 1)
- [x] Plan credit fields: `credits_per_month`, `max_credits_balance`, `topup_credits_per_pack`, `topup_price`, `job_notifications`
- [x] UserProfile billing fields: `plan_valid_until`, `pending_plan`
- [x] `credits_deducted` flag on ResumeAnalysis for idempotent debit/refund
- [x] `accounts/services.py` — deduct, refund, topup, subscribe, grant_monthly, process_expired, check_balance, can_use_feature
- [x] Credit deduction on POST /api/analyze/ and /retry/ — 402 on insufficient credits
- [x] Auto-refund on Celery task failure + stale analysis cleanup
- [x] Wallet endpoints: GET /wallet/, GET /wallet/transactions/, POST /wallet/topup/
- [x] Plan endpoints: GET /plans/ (public), POST /plans/subscribe/
- [x] seed_credit_costs + updated seed_plans commands
- [x] Admin panels: WalletAdmin, WalletTransactionAdmin, CreditCostAdmin
- [x] All 136 tests passing
- [x] FRONTEND_API_GUIDE.md Section 18 updated, CHANGELOG.md v0.10.0 entry
</details>

---

## Phase 10 — Resume Generation from Analysis Report ✅

> **Goal:** One-click "Generate Improved Resume" that applies all analysis findings (missing keywords, sentence rewrites, section feedback, quick wins) into an ATS-optimized PDF/DOCX.
>
> **Status:** Shipped in v0.11.0 (2026-02-26)

### Models

- [x] **`GeneratedResume` model** — UUID PK, FK to `ResumeAnalysis`, template/format/status/resume_content JSON, file (R2), LLM response reference, `credits_deducted` flag. Indexed on `(analysis, -created_at)` and `(user, -created_at)`.

### Service Layer

- [x] **`analyzer/services/resume_generator.py`** — `build_rewrite_prompt()`, `validate_resume_output()`, `call_llm_for_rewrite()`. Assembles analysis findings into improvement spec. Strict no-fabrication prompt.

### LLM Rewrite Schema

- [x] **Rewrite prompt design** — System prompt enforces no fabrication. User prompt includes missing keywords with placements, sentence rewrites, section feedback for <70 scores, quick wins, formatting guidance, target role context.
- [x] **Output JSON schema** — contact, summary, experience[], education[], skills (grouped), certifications[], projects[] with validation and defaults for optional fields.

### PDF/DOCX Rendering

- [x] **PDF renderer** (`resume_pdf_renderer.py`) — ReportLab-based, ATS-optimized `ats_classic` template. A4, Helvetica, navy accents, KeepTogether for page-break control.
- [x] **DOCX renderer** (`resume_docx_renderer.py`) — python-docx based, same `ats_classic` template. Calibri font, narrow margins, ATS-compatible.
- [x] **Template registry** — Slug-based validation in serializer. Extensible for future templates.

### Celery Task

- [x] **`generate_improved_resume_task`** — Async pipeline: LLM rewrite → render PDF/DOCX → upload to R2 → mark done. Max retries: 2, acks_late. Refund on failure via `_refund_generation_credits()`.

### API Endpoints

- [x] **`POST /api/analyses/<id>/generate-resume/`** — Trigger generation. 1 credit. Returns 202. Validates analysis is `done`. Returns 402 on insufficient credits.
- [x] **`GET /api/analyses/<id>/generated-resume/`** — Poll latest generation status.
- [x] **`GET /api/analyses/<id>/generated-resume/download/`** — 302 redirect to signed R2 URL.
- [x] **`GET /api/generated-resumes/`** — List all user's generated resumes (paginated).

### Credits & Seed Data

- [x] **`resume_generation = 1`** credit cost in `seed_credit_costs` + `_DEFAULT_COSTS` fallback
- [x] **Credit flow:** Deduct on POST, refund if task fails (same pattern as analysis)

### Dependencies

- [x] **`python-docx==1.1.2`** added to requirements.txt

### Tests

- [x] All 136 existing tests pass (no regressions)
- [ ] Unit tests for prompt builder (verify all analysis fields included)
- [ ] Unit tests for JSON schema validation
- [ ] API endpoint tests (202, 402, 400 for non-done analysis, polling)
- [ ] Integration test for PDF render from sample structured JSON

### Documentation

- [x] FRONTEND_API_GUIDE.md — Section 20 with full endpoints, TypeScript types, integration recipe
- [x] CHANGELOG.md — v0.11.0 entry
- [ ] CHANGELOG.md — v0.11.0 entry

---

## Phase 11 — Smart Job Alerts (Job Discovery & Matching Pipeline) ✅

> **Goal:** Users subscribe to job alerts linked to a resume. System periodically discovers matching jobs from external APIs, scores relevance via LLM, and sends email digests. Pro plan only.
> **Status:** Completed in v0.12.0

### Models

- [x] **`JobSearchProfile` model** — OneToOne with `Resume`. LLM-extracted search criteria: `titles` (JSONField — list of target job titles), `skills` (JSONField), `seniority` (CharField: junior/mid/senior/lead/executive), `industries` (JSONField), `locations` (JSONField), `experience_years` (int), `raw_extraction` (JSONField — full LLM output), `created_at`, `updated_at`
- [x] **`JobAlert` model** — FK to User + Resume. Config: `frequency` (daily/weekly), `is_active` (bool), `preferences` (JSONField: remote_ok, location, salary_min, excluded_companies), `last_run_at`, `next_run_at`, `created_at`
- [x] **`DiscoveredJob` model** — Global (not per-user). Fields: `source` (serpapi/adzuna/remotive), `external_id` (unique with source), `url`, `title`, `company`, `location`, `salary_range`, `description_snippet`, `posted_at`, `raw_data` (JSONField), `created_at`. Unique constraint on (source, external_id).
- [x] **`JobMatch` model** — Junction: FK to `JobAlert` + `DiscoveredJob`. Fields: `relevance_score` (0-100), `match_reason` (TextField — LLM-generated), `user_feedback` (pending/relevant/irrelevant/applied/dismissed), `created_at`
- [x] **`JobAlertRun` model** — Audit log: FK to `JobAlert`. Fields: `jobs_discovered`, `jobs_matched`, `notification_sent` (bool), `credits_used`, `error_message`, `duration_seconds`, `created_at`

### Service Layer

- [x] **`analyzer/services/job_search_profile.py`** — `extract_search_profile(resume)` → LLM call to extract titles, skills, seniority, industries, locations from resume text. Saves to `JobSearchProfile`.
- [x] **`analyzer/services/job_sources/`** — Provider pattern (like `ai_providers/`):
  - `base.py` — `BaseJobSource` abstract class with `search(queries, location, date_filter) → [DiscoveredJob]`
  - `serpapi_source.py` — Google Jobs via SerpAPI
  - `adzuna_source.py` — Adzuna free API
  - `factory.py` — Source selection based on config
- [x] **`analyzer/services/job_matcher.py`** — `match_jobs(job_alert, discovered_jobs)` → Batch LLM call: "Score these jobs 0-100 for this resume. Return [{id, score, reason}]". Filters by threshold (≥60), creates `JobMatch` records.

### Celery Tasks

- [x] **`extract_job_search_profile_task(resume_id)`** — Runs on alert creation. Extracts search profile from resume via LLM.
- [x] **`discover_jobs_task()`** — Periodic (Celery Beat, every 6h). For each active JobAlert where `next_run_at ≤ now`: build search queries from profile, call job source APIs, dedup via `external_id`, insert new `DiscoveredJob` records, chain `match_jobs_task`.
- [x] **`match_jobs_task(job_alert_id, discovered_job_ids)`** — Batch LLM relevance scoring. Create `JobMatch` records for score ≥ threshold. Chain `send_job_alert_notification_task`.
- [x] **`send_job_alert_notification_task(job_alert_id, run_id)`** — If new matches found + user has `job_alerts_email` enabled: render email digest via `EmailTemplate` (top 5-10 matches with title, company, score, reason, apply URL). Update `last_run_at`, log to `JobAlertRun`.

### API Endpoints

- [x] **`GET /api/job-alerts/`** — List user's alert subscriptions
- [x] **`POST /api/job-alerts/`** — Create alert (link to resume, set frequency + preferences). Pro only. Triggers profile extraction.
- [x] **`GET /api/job-alerts/<id>/`** — Alert detail + latest run stats
- [x] **`PUT /api/job-alerts/<id>/`** — Update preferences (frequency, location, etc.)
- [x] **`DELETE /api/job-alerts/<id>/`** — Deactivate alert
- [x] **`GET /api/job-alerts/<id>/matches/`** — Paginated matched jobs with scores + reasons
- [x] **`POST /api/job-alerts/<id>/matches/<id>/feedback/`** — User marks relevant/irrelevant/applied/dismissed
- [x] **`POST /api/job-alerts/<id>/run/`** — On-demand manual run (costs 1 credit)

### Credits & Plan Gating

- [x] `job_alert_run = 1` credit cost in `seed_credit_costs`
- [x] Create alert: Pro only (`plan.job_notifications` check)
- [x] Max active alerts: Plan-configurable (add `max_job_alerts` field to Plan, Pro = 3)
- [x] Automated runs: 1 credit per run
- [x] Manual runs: 1 credit per run

### External API Integration

- [x] **SerpAPI** — Google Jobs endpoint. Env var: `SERPAPI_API_KEY`. Package: `google-search-results` or raw `requests`.
- [x] **Adzuna** — Free tier (250 req/day). Env var: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`. Raw `requests`.

### Migration from Existing Job Model

- [x] Existing `Job` model stays as "manually tracked jobs" (user-created via POST /api/jobs/)
- [x] `DiscoveredJob` + `JobMatch` = system-discovered pipeline
- [ ] Frontend shows tabs: "My Jobs" vs "Discovered Jobs" *(frontend task)*

### Tests

- [x] Unit tests for search profile extraction prompt
- [x] Unit tests for job source providers (mock API responses)
- [x] Unit tests for LLM batch matching
- [x] API endpoint tests (CRUD, plan gating, credit deduction)
- [x] Integration test for full pipeline (discover → match → notify)

### Dependencies

- [x] Add `google-search-results` (SerpAPI) or use raw `requests` *(used raw requests — no extra dependency)*
- [ ] Env vars: `SERPAPI_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`

### Documentation

- [ ] FRONTEND_API_GUIDE.md — new section with endpoints, example flows, TypeScript types
- [ ] CHANGELOG.md — v0.12.0 entry
- [ ] Seed `job_alert_digest` email template

---

## Backlog — Quick Wins (Backend Enhancements)

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
