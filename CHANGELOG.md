# Changelog

All notable changes to the Resume AI backend are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
