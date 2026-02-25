# Changelog

All notable changes to the Resume AI backend are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.9.1] — 2026-02-25

### Bug Fixes & Security Hardening (Audit Sweep)

### Changed
- **PDF export: WeasyPrint → ReportLab** — Replaced WeasyPrint (C-library dependency) with ReportLab 4.4.0 (pure Python). Eliminates native `libpango`, `libcairo` linking failures on Railway Nixpacks. PDF report visuals fully rebuilt with Platypus flowables, score bars, keyword pills, and section feedback.
- **Share URLs now absolute** — `share_url` in API responses changed from relative (`/api/shared/<uuid>/`) to absolute (`https://host/api/shared/<uuid>/`) using `request.build_absolute_uri()`. Affects `POST /api/analyses/<id>/share/`, list serializer, and detail serializer.
- **CORS: wildcard removed** — Removed `CORS_ALLOW_ALL_ORIGINS=True` path. Only explicit comma-separated origins via `CORS_ALLOWED_ORIGINS` env var are accepted. Prevents accidental wildcard + credentials misconfiguration.
- **R2 signed URL TTL explicit** — Added `AWS_QUERYSTRING_EXPIRE = 3600` (1 hour). Was relying on django-storages default; now discoverable and tunable.
- **ScrapeResult cache scoped to user** — `find_cached()` now filters by requesting user, preventing cross-user cache hits and cascade-delete breakage.
- **SharedAnalysisView throttling restored** — Removed `throttle_classes = []` that was silently disabling all rate limiting on the public share endpoint. Now inherits global `AnonRateThrottle`.
- **`STATUS_DONE` constant** — `ExportPDFView` replaced `'done'` string literal with `ResumeAnalysis.STATUS_DONE`.
- **Removed unused `anthropic` dependency** — Not imported anywhere; LLM calls use OpenRouter (openai SDK) exclusively.

### Fixed
- **Lazy-init JDFetcher** — `JDFetcher.__init__` raised `ValueError` when `FIRECRAWL_API_KEY` was missing, breaking text/form analysis types that never use Firecrawl. Now instantiated lazily only for URL inputs.
- **LogoutView refresh guard** — Returns 400 with `"Refresh token is required."` when `refresh` key is missing from request body, instead of potential 500.
- **Removed redundant `save_user_profile` signal** — Was causing an extra DB write on every `user.save()`. Profile saves handled explicitly in serializers.
- **Bulk soft-delete on account deletion** — Replaced N+1 loop with single `QuerySet.update()` for soft-deleting analyses during account deletion.
- **AI response validation** — `quick_wins` now enforced to exactly 3 items; all score values coerced to `int` to prevent float leakage from LLM responses.
- **Idempotency lock release** — Analysis lock (`analyze_lock:{user_id}`) now explicitly deleted when Celery task starts, instead of waiting for 30s TTL expiry.

---

## [0.9.0] — 2026-02-23

### Phase 9: Profile Management, Jobs Model & Resume Download

### Added
- **`PUT /api/auth/me/`** — Update username and/or email (partial update supported). Validates uniqueness of both fields.
- **`POST /api/auth/change-password/`** — Change password with `current_password` + `new_password`. Validates current password and runs Django password validators on the new one.
- **`DELETE /api/auth/me/`** — Permanently delete account. Blacklists all tokens, soft-deletes analyses (clears heavy data), cascade-deletes user + resumes + related objects.
- **`file_url` field on `ResumeSerializer`** — `GET /api/resumes/` now returns the download URL for each resume, so the frontend ResumesPage can link directly.
- **`Job` model** — Tracked job postings linked to user and optionally a resume. Fields: `id` (UUID), `user`, `resume` (FK, nullable), `job_url`, `title`, `company`, `description`, `relevance` (pending/relevant/irrelevant), `source`, `created_at`, `updated_at`. Migration `0008_add_job_model`.
- **Job endpoints:**
  - `GET /api/jobs/` — List user's tracked jobs, filterable by `?relevance=relevant|irrelevant|pending`.
  - `POST /api/jobs/` — Create a tracked job (optionally linking a `resume_id`).
  - `GET /api/jobs/<uuid>/` — Retrieve a single job.
  - `DELETE /api/jobs/<uuid>/` — Delete a tracked job.
  - `POST /api/jobs/<uuid>/relevant/` — Mark job as relevant.
  - `POST /api/jobs/<uuid>/irrelevant/` — Mark job as irrelevant.
- `UpdateUserSerializer` and `ChangePasswordSerializer` in accounts app.
- `JobSerializer` and `JobCreateSerializer` in analyzer app.
- `Job` registered in Django admin.
- **32 new tests**: 14 in `accounts/test_profile.py` (profile update, change password, delete account), 18 in `analyzer/tests/test_jobs.py` (CRUD, relevance, user isolation, auth).

### Changed
- `MeView` now handles GET, PUT, and DELETE (was GET-only).
- Total test count: **131** (all passing).

---

## [0.8.1] — 2026-02-23

### Resume Reuse & Test Infrastructure

### Added
- **`resume_id` support in `POST /api/analyze/`** — submit an existing Resume UUID instead of re-uploading the PDF. Send `resume_id` (UUID) as JSON or form field; the analysis reuses the stored file. Exactly one of `resume_file` or `resume_id` is required.
- `JSONParser` added to `AnalyzeResumeView` so `resume_id`-only requests can be sent as `application/json`.
- **10 new tests** in `test_resume_id.py`: success with JSON, multipart, and form JD; validation for neither/both provided, invalid UUID, non-existent resume, other user's resume, multiple analyses from same resume, file upload regression.

### Fixed
- **Test infrastructure — rate-limit isolation** — tests were hitting real Redis-backed throttle counters, causing spurious 429 responses after repeated runs. Root cause: `CACHES` used shared Redis and DRF throttle state persisted across test runs.
  - Added `TESTING` flag (`'test' in sys.argv`) to `settings.py`.
  - During tests: `CACHES` falls back to `LocMemCache` (in-memory, per-process) instead of Redis.
  - During tests: throttle rates set to `10000/minute` (effectively unlimited) so all 99 tests pass reliably.

### Changed
- `resume_file` field on `ResumeAnalysisCreateSerializer` is now `required=False` (was implicitly required). The `validate()` method enforces that exactly one of `resume_file` / `resume_id` is provided.
- `serializer.save(user=…)` now passes `request` context for `resume_id` owner validation.
- Total test count: **99** (78 existing + 10 resume_id + 11 schema/serializer, all passing).

---

## [0.8.0] — 2026-02-23

### Phase 8: SSRF Protection & Shareable Analysis Links

### Added
- **Shareable results link** — owners of a completed analysis can generate a public, read-only URL. No authentication required to view a shared analysis.
  - `POST /api/analyses/<id>/share/` — generate a UUID share token (idempotent; returns existing token if already shared).
  - `DELETE /api/analyses/<id>/share/` — revoke the share token (link stops working immediately).
  - `GET /api/shared/<token>/` — public read-only view returning ATS score, breakdown, keyword gaps, section suggestions, rewritten bullets, and assessment. Excludes all sensitive data (resume file, user info, celery task ID, raw JD text).
- `share_token` (UUID, nullable, unique) field on `ResumeAnalysis` model. Migration `0007_add_share_token`.
- `SharedAnalysisSerializer` — public read-only serializer with curated safe fields only.
- `share_token` and `share_url` exposed in `ResumeAnalysisDetailSerializer` and `ResumeAnalysisListSerializer`.
- **18 new tests** in `test_share.py`: token generation, idempotency, auth enforcement, user isolation, revocation, public access, sensitive field exclusion, soft-deleted analysis handling.

### Fixed
- **SSRF protection** in `JDFetcher._validate_url()` — now resolves hostnames via `socket.getaddrinfo` and rejects private/reserved/loopback/link-local IP addresses (`127.0.0.1`, `10.x`, `172.16-31.x`, `192.168.x`, `169.254.x`, `::1`, etc.). Previously only checked URL scheme. All 5 pre-existing SSRF test failures now pass (10/10 `test_jd_fetcher` tests green).

### Changed
- Total test count: **78** (50 existing + 18 share + 10 JD fetcher all passing).

---

## [0.7.0] — 2026-02-23

### Phase 7: Resume Model, Soft-Delete & Dashboard Analytics

### Added
- **`Resume` model** — deduplicated resume file storage with SHA-256 hashing per user. Same PDF uploaded multiple times creates only one stored file. Fields: `id` (UUID), `user`, `file`, `file_hash`, `original_filename`, `file_size_bytes`, `uploaded_at`.
- **Soft-delete on `ResumeAnalysis`** — `deleted_at` field (DateTimeField, nullable). `ActiveAnalysisManager` (default) excludes soft-deleted rows; `all_objects` manager for admin/analytics.
- **`soft_delete()` method** on `ResumeAnalysis` — sets `deleted_at`, clears heavy fields (`resume_text`, `resolved_jd`, `jd_text`), deletes `report_pdf` from R2, orphan-cleans `ScrapeResult` and `LLMResponse`.
- **`GET /api/resumes/`** — paginated list of user's deduplicated resumes with `active_analysis_count`.
- **`DELETE /api/resumes/<uuid:id>/`** — delete resume from R2 storage (blocked if active analyses reference it, returns 409).
- **`GET /api/dashboard/stats/`** — user-level analytics: total/active/deleted counts, average ATS score, score trend (last 10), top 5 roles, analyses per month (last 6 months). Uses `all_objects` to include soft-deleted rows.
- **`post_delete` signal** on `Resume` — automatically deletes file from R2 when Resume row is hard-deleted.
- **Admin enhancements** — `Resume`, `ScrapeResult`, `LLMResponse` registered in admin. `ResumeAnalysis` admin shows soft-deleted rows with `is_deleted` column.
- **DB indexes** — `(user, deleted_at)` and `(user, status, -created_at)` on `ResumeAnalysis`; `(user, -uploaded_at)` on `Resume`; unique constraint `(user, file_hash)` on `Resume`.
- **Data migration** `0006_populate_resume_from_existing` — creates `Resume` rows from existing `resume_file` values, computes SHA-256 hashes, deduplicates, links analyses.
- **27 new tests** in `test_phase7.py` covering: Resume model, dedup, soft-delete, orphan cleanup, API endpoints, dashboard stats, user isolation.

### Changed
- **`DELETE /api/analyses/<id>/delete/`** — now performs soft-delete instead of hard-delete (⚠️ breaking behavior change, same 204 response).
- **`POST /api/analyze/`** — now creates a `Resume` row (deduplicated) and links it to the analysis via `resume` FK.
- **`FRONTEND_API_GUIDE.md`** — updated with 3 new endpoints, soft-delete documentation, new sections 9-10, updated ToC and quick reference table.

---

## [0.6.0] — 2026-02-22

### Phase 6: Performance & Security Optimizations

**Commit:** `563e34f` — 15 files changed, 1,002 insertions, 134 deletions

### Added
- **Pagination** on `GET /api/analyses/` — `PageNumberPagination`, PAGE_SIZE=20. Response is now a `{ count, next, previous, results }` envelope (⚠️ breaking change).
- **Idempotency guard** on `POST /api/analyze/` — Redis lock prevents duplicate submissions within 30 seconds. Returns `409 Conflict` on double-submit.
- **DB indexes** on `ResumeAnalysis`: `(user, -created_at)` and `(status, updated_at)`. Migration `0004_add_resumeanalysis_indexes`.
- **`FRONTEND_API_GUIDE.md`** — comprehensive 750-line technical reference covering all 13 endpoints, schemas, pagination, rate limiting, polling, LLM output schema, and breaking changes.
- Test `test_analyze_double_submit_blocked` for idempotency guard.

### Changed
- **OpenRouter provider** — switched from Luffy self-hosted LLM to OpenRouter API with `anthropic/claude-haiku-4.5` via OpenAI SDK. Configurable via `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` env vars.
- **LLM job metadata extraction** — for `text` and `url` JD input types, the LLM now extracts `job_metadata` (job_title, company, skills, experience_years, industry, extra_details) and populates `jd_*` fields on the analysis. All JD input types now have consistent metadata.
- **Status cache scoped to user** — cache key changed from `analysis_status:{pk}` to `analysis_status:{user_id}:{pk}` to prevent cross-user data leakage.
- **`select_related`** on `AnalysisDetailView` — reduces 3 DB queries to 1 via `select_related('scrape_result', 'llm_response')`.
- **Pipeline `save()` reduction** — combined pre-step `pipeline_step` write with post-step data write, reducing ~10 saves to ~5 per pipeline run.
- **Celery retry expansion** — `autoretry_for` now includes `ConnectionError`, `OSError`, `TimeoutError`. Added `reject_on_worker_lost=True` and `acks_late=True`.
- **OpenRouter timeout** — 120-second timeout on API calls to prevent hung workers.
- **Firecrawl summary usage** — LLM prompt now uses the Firecrawl `summary` field for URL inputs instead of full markdown, reducing token usage.
- **Redundant JSON instruction removed** — "Return ONLY valid JSON" kept only in system message, removed from user prompt.
- **`LogoutView`** — catches `TokenError` specifically instead of bare `except Exception`.
- **All `print()` → `logger`** — ~30+ print statements replaced with structured logging across all service files.

### Removed
- `prompt_sent` and `raw_response` from `LLMResponseSerializer` (~160KB saved per response).
- `markdown` and `json_data` from `ScrapeResultSerializer` (only `summary` exposed now).

---

## [0.5.0] — 2026-02-22

### OpenRouter Integration & Bug Fixes

**Commits:** `92df0e8`, `498e7cb`

### Added
- `openrouter_provider.py` — OpenRouter AI provider using OpenAI Python SDK pointed at `https://openrouter.ai/api/v1`.
- Markdown fence stripping (`_MD_FENCE_RE`) — handles Haiku wrapping JSON in ```json fences.
- JSON repair fallback for malformed LLM responses.

### Changed
- AI provider factory updated to support `openrouter` provider selection.
- Default `AI_PROVIDER` set to `openrouter` in settings.

---

## [0.4.0] — 2026-02-22

### Railway Deployment Fixes

**Commits:** `97b92d5` → `bb48ed5`

### Fixed
- Updated requirements.txt for deployment compatibility.
- Railway deployment configuration (`railway.json`, `Procfile`).
- `ALLOWED_HOSTS` auto-appends `.railway.app` in production.
- CORS configuration for frontend ↔ backend communication.
- Removed frontend from `railway.json` (separate service).

---

## [0.3.0] — 2026-02-22

### Celery + Redis + R2 + PostgreSQL

**Commit:** `0162e01`

### Added
- Celery task queue with Redis broker for async analysis pipeline (replaces threading).
- Cloudflare R2 (S3-compatible) file storage for resume PDFs and report PDFs via `django-storages[boto3]`.
- PostgreSQL support via `dj-database-url` (falls back to SQLite locally).
- Redis-backed caching for DRF throttle state and status polling.
- `entrypoint.sh` for Railway deployment.

---

## [0.2.0] — 2026-02-22

### UI/UX Overhaul + Pipeline + Deployment Plan

**Commits:** `85ce713`, `8532c61`

### Added
- Atomic analysis pipeline: PDF extraction → JD resolution → LLM call → result parsing.
- Luffy LLM provider integration.
- Firecrawl URL scraping for JD URLs.
- Retry mechanism for failed analyses.
- PDF report generation via WeasyPrint.
- Complete frontend UI/UX overhaul (React + Tailwind).
- `backend_todo.md` and `UI_UX_TODO.md` deployment plans.

---

## [0.1.0] — 2026-02-21

### Initial Release

**Commits:** `0aabef7` → `0eed7da`

### Added
- Django REST Framework API for resume analysis.
- JWT authentication (access: 1hr, refresh: 7d, rotation + blacklist).
- User registration, login, logout, profile endpoints.
- Resume upload with PDF validation.
- Job description input via text, URL, or structured form.
- Analysis CRUD endpoints (create, list, detail, delete).
- Status polling endpoint with pipeline step tracking.
- PDF export endpoint.
- Health check endpoint.
- React + Vite + Tailwind frontend SPA.
- React Native + Expo mobile app scaffold.

### Fixed
- Security, quality, and reliability issues from code review (`8f8d4a6`).
