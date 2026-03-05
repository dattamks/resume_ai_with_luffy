# Changelog

All notable changes to the Resume AI backend are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.45.1] — 2026-03-05

### Template Refinements & Modern Template Disabled

#### Changed — Template Visual Fixes (v2–v4)
- All 5 HTML templates iterated through multiple visual QA rounds.
- **ats_classic** — Proper `@page` margins (40px 48px) for consistent multi-page rendering.
- **executive** — Proper `@page` margins (44px 52px), body padding removed.
- **creative** — Fully redesigned: gradient purple hero header with negative-margin bleed, lavender skills bar with pill tags, single-column body with purple left-border job entries. Fixed header padding so text doesn't touch edges (v4).
- **modern** — Fully rewritten: dark navy header banner with name/contact + skill pills, single-column body with blue left-border section titles. **Disabled** — needs further design modification.
- **minimal** — Text contrast improved (darkened section titles to #777, secondary text to #666).

#### Changed — Modern Template Disabled
- `modern` removed from `TEMPLATE_RENDERERS` in `template_registry.py`. Requesting `modern` now returns a `ValueError`. Will be re-enabled after redesign.
- Frontend should filter out `modern` from template picker or rely on the `is_active` flag from `GET /api/v1/templates/`.

#### Fixed — Multi-Page Layout
- Replaced flex two-column sidebar layouts (modern, creative) with single-column layouts using `@page` CSS margins. Flex sidebars broke on page 2 in Chromium PDF rendering.
- All templates now render consistently across page breaks.

---

## [0.45.0] — 2026-03-05

### Resume Rendering Overhaul — HTML/CSS → PDF via Playwright

#### Added — HTML→PDF Rendering Pipeline
- **Playwright headless Chromium** replaces ReportLab for all PDF resume rendering. Produces pixel-perfect output with full CSS support (flexbox, grid, `@font-face`, gradients).
- `analyzer/services/resume_html_renderer.py` — singleton browser, `render_html_to_pdf()`, thread-safe, auto-restart on crash.
- `analyzer/services/resume_template_env.py` — Jinja2 environment with Google Fonts embedded as base64 WOFF2 data URIs.
- `analyzer/services/resume_html_pdf_renderers.py` — bridge module mapping template slugs to HTML→PDF rendering.

#### Added — 5 Distinct HTML Resume Templates
Each template has a **fundamentally different layout** (not just color swaps):
- **ats_classic** — Clean single-column, Inter font, ALL CAPS section headers with underline, ATS-optimized
- **modern** — Dark navy header banner, Montserrat headings, blue-accent section titles *(currently disabled)*
- **executive** — Full-width, Lato font, gold accent (#c5a55a), gradient section underlines, generous whitespace
- **creative** — Gradient purple hero header, lavender skills bar with pill tags, purple-accent job entries
- **minimal** — Ultra-clean single column, Courier New monospace dates, subdued gray palette

#### Added — Google Fonts Bundle
- 9 WOFF2 font files (Inter, Lato, Montserrat — regular/bold/italic) in `analyzer/static/fonts/`

#### Changed — Template Registry
- `template_registry.py` now routes PDF rendering through HTML→Playwright pipeline with automatic ReportLab fallback when Playwright/Chromium is unavailable.
- DOCX rendering unchanged (python-docx).

#### Changed — Build & Deployment
- `requirements.txt` — added `playwright==1.50.0`, `Jinja2==3.1.6`
- `nixpacks.toml` — added Chromium system dependencies and `playwright install chromium` build command
- `entrypoint.sh` — exports `PLAYWRIGHT_BROWSERS_PATH` env var

#### Added — Tests
- `RenderHtmlPdfTests` — 9 integration tests covering all 5 templates, minimal content, special characters/XSS safety, template registry routing, and template distinctness.
- All 90 resume generation tests pass (zero regressions).

---

## [0.44.0] — 2026-03-04

### Skill Catalogue & Rate Limit Increase

#### Added — Skill Model & API
- Skill model: 17-field normalised catalogue (`analyzer/models.py`) with LLM-generated description, category, aliases, roles, demand stats, salary, trending flag, and timestamps.
- Migration: `0037_add_skill_model.py` — seeded 1,803 skills from 822 jobs, all with LLM descriptions.
- API endpoints:
  - `GET /api/v1/skills/` — paginated, searchable, filterable list
  - `GET /api/v1/skills/<name>/` — full skill detail

#### Added — Skill Aggregation & Management
- Automatic pipeline enrichment: every job ingested triggers skill upsert (counter increments for existing, row creation for new). New skills get LLM descriptions via async `enrich_new_skills_task`.
- Pipeline hooks in `process_ingested_jobs_task`, `crawl_jobs_daily_task`, `sync_analyzed_job_task`.
- Service module: `analyzer/services/skill_enrichment.py`.
- Management command: `aggregate_skills` — backfill/repair only (not needed for normal operation).
- Admin: Full Django admin registration with filters, search, inline editing.

#### Changed — Rate Limits Increased
| Scope     | Before | After   |
|-----------|--------|---------|
| user      | 200/hr | 500/hr  |
| analyze   | 10/hr  | 20/hr   |
| readonly  | 120/hr | 1000/hr |
| write     | 60/hr  | 150/hr  |
| payment   | 30/hr  | 60/hr   |
Anonymous (`anon`: 60/hr) and auth-endpoint (`auth`: 20/hr) unchanged.

#### Frontend Notes
- Skill catalogue API documented in §33 of FRONTEND_API_GUIDE.md
- Rate limits updated throughout docs
- No breaking changes; all existing endpoints unchanged

---

## [0.43.0] — 2026-03-04

### LLM Response Resilience — Coercion, Auto-Retry, Free Retries

Production analysis failures (12 total, 5 from schema validation) revealed that LLM
responses frequently contain fixable mistakes (wrong grade format, missing optional
fields, string scores). This release adds 5 layers of defence.

#### Added — `coerce_ai_response()` (P0) (`analyzer/services/ai_providers/base.py`)
- Best-effort fix-up that runs **before** strict validation.
- Inserts safe defaults for missing `job_metadata`, `ats_disclaimers`, `keyword_analysis`, `formatting_flags`, `sentence_suggestions`, `summary`, `quick_wins`.
- Coerces string scores (`"72"`) to int, clamps out-of-range scores to `[0, 100]`.
- Fills missing sub-fields in `section_feedback` entries (`ats_flags`, `feedback`, `score`).
- Auto-assigns `priority` to `quick_wins` entries missing it.
- Logs all applied fixes for audit trail.
- Returns list of fix descriptions for downstream tracking.

#### Added — Auto-Retry on Validation Failure (P1) (`analyzer/services/ai_providers/openrouter_provider.py`)
- Up to 1 automatic retry (2 total attempts) when schema validation fails after coercion.
- Retries use the same prompt — LLM non-determinism means the second response usually passes.
- Token usage is accumulated across retries for accurate cost tracking.

#### Added — `LLMValidationError` Exception (P2) (`analyzer/services/ai_providers/base.py`)
- Custom `ValueError` subclass that carries `raw_response` for debugging.
- `_step_llm_call` in `analyzer.py` now saves `raw_response` to `LLMResponse` record on failure.
- Previously, failed analyses had no raw response saved — making debugging impossible.

#### Changed — Free Retry for System Faults (P3) (`analyzer/views.py`)
- `RetryAnalysisView` now detects system-fault errors (prefixed with `"AI response"`, `"OpenRouter returned"`, etc.).
- System-fault retries skip credit deduction — user is not charged for LLM mistakes.
- Capped at `MAX_FREE_RETRIES = 2` per analysis to prevent abuse.
- Response includes `free_retry: true/false` so frontend can show appropriate messaging.

#### Added — `retry_count` Field (`analyzer/models.py`)
- New `PositiveSmallIntegerField` on `ResumeAnalysis` tracking user-initiated retries.
- Migration: `0036_add_retry_count_to_analysis`.

#### Added — Truncated Output Detection (P4) (`analyzer/services/ai_providers/openrouter_provider.py`)
- Checks `finish_reason == 'length'` from OpenRouter API response.
- Logs warning when output is truncated due to `max_tokens` limit.
- Truncated responses still go through JSON repair + coercion pipeline.

#### Added — Tests (`analyzer/tests/test_ai_schema.py`)
- 19 new tests: 15 coercion tests, 2 `LLMValidationError` tests, 2 full-pipeline tests.
- Total: **43 tests** (up from 24) covering validation, coercion, and error handling.

---

## [0.42.1] — 2026-03-04

### Fix — LLM Grade Validation Rejects `B+`/`A-` Modifiers

#### Fixed — Grade Normalization (`analyzer/services/ai_providers/base.py`)
- **Root cause**: LLM returned `"B+"` as `overall_grade`, but validation only accepted `{A, B, C, D, F}`, causing analysis to fail with `AI response "overall_grade" must be one of {'A', 'B', 'D', 'C', 'F'}, got "B+"`.
- **Prompt tightened**: Schema description changed from vague `"<letter grade A, B, C, D, or F …>"` to explicit `"<EXACTLY one of: A, B, C, D, F — no plus/minus modifiers>"`.
- **New rule added**: `overall_grade must be EXACTLY one of A, B, C, D, or F. Never use + or - modifiers (e.g. B+ or A- are NOT allowed)`.
- **Defence in depth**: Validation now strips `+`/`-` with `.rstrip('+-')` so if the LLM still slips, `B+` → `B` instead of a hard failure.

#### Updated — LLM Behaviour Docs (`docs/llm_behaviour.md`)
- Synced prompt template and schema with current code (added `job_metadata`, boundary markers, tightened grade constraint).

---

## [0.42.0] — 2026-03-04

### Admin Daily Digest — Automated Platform Metrics Email

#### Added — `compute_digest_metrics()` Service (`analyzer/services/admin_digest.py`)
- Aggregates ~40 metrics across 11 categories (users, revenue, credits, analyses, resumes, LLM usage, job alerts, feature usage, news feed, notifications, infrastructure) for the last 24 hours.
- All timestamps use IST for display.

#### Added — `send_admin_digest_task` Celery Task (`analyzer/tasks.py`)
- Periodic task scheduled twice daily: **9:00 AM IST** (3:30 UTC) + **11:00 PM IST** (17:30 UTC).
- Sends to all emails in `ADMIN_DIGEST_EMAILS` env var (comma-separated).
- Uses `admin-daily-digest` EmailTemplate from DB.
- Graceful per-recipient failure handling — one failure doesn't block others.

#### Added — `admin-daily-digest` EmailTemplate
- Full HTML email with 11 color-coded sections, metric cards, and tables.
- Plain-text fallback with all metrics.
- Added to `seed_email_templates` management command.

#### Added — Configuration
- `ADMIN_DIGEST_EMAILS` env var — comma-separated admin email addresses.
- Two Celery Beat entries: `admin-digest-morning` (9 AM IST), `admin-digest-night` (11 PM IST).

#### Added — Tests (`analyzer/tests/test_admin_digest.py`)
- 34 tests across 4 classes: metrics aggregation (20), Celery task (6), settings (2), schedule (6).

---

## [0.41.0] — 2026-03-04

### News Feed — Ingest & Serve Career/Tech News

#### Added — `NewsSnippet` Model (`analyzer/models.py`)
- New model with 20+ fields: `uuid` (crawler PK), `headline`, `summary` (LLM-generated), `source_url`, `source_name`, `image_url`, `published_at`, `category` (13 choices), `tags`, `sentiment`, `relevance_score`, `region`, `company_mentions`, `industry`, `is_flagged`, `flag_reason`, `is_approved`, `is_active`.
- Indexes on `category+published_at`, `region+published_at`, composite active/approved, `relevance_score`.
- Migration: `0035_add_news_snippet_model`.

#### Added — News Ingest API (Crawler Bot → i-Luffy)
- `POST /api/v1/ingest/news/` — single news snippet upsert (keyed on `uuid`, fallback `source_url`).
- `POST /api/v1/ingest/news/bulk/` — bulk upsert up to 200 snippets per request.
- `POST /api/v1/ingest/news/deactivate/` — deactivate expired/removed snippets by UUID list.
- All endpoints use `X-Crawler-Key` auth, no rate limiting, idempotent upserts.

#### Added — News Feed API (i-Luffy → Frontend)
- `GET /api/v1/feed/news/` — paginated news feed (page/page_size, max 50). Filters: `category`, `region`, `sentiment`, `search` (headline/summary/tags). Only active+approved+non-flagged snippets.
- `GET /api/v1/feed/news/<uuid:id>/` — single snippet detail. 404 for inactive/flagged.

#### Added — Admin Registration
- `NewsSnippetAdmin` with list display, filters, search across headline/summary/source.

#### Added — Tests (`analyzer/tests/test_news.py`)
- 26 tests across 4 test classes: single ingest (6), bulk ingest (5), deactivate (3), feed list+detail (12).

#### Documentation
- `FRONTEND_API_GUIDE.md` §30.11 + §30.12: full news feed endpoint docs with response shapes, field tables, category enum, TS types.
- §32 quick-reference: added news feed endpoint rows.

---

## [0.40.0] — 2026-03-03

### Feed Insights Rework — Salary, Counts & Documentation Gaps

#### Added — Currency Conversion Module (`analyzer/currency.py`)
- `_COUNTRY_CURRENCY`: maps 60+ country names → ISO 4217 currency codes.
- `_USD_RATES`: ~40 USD-to-local conversion rates, overridable via `SALARY_USD_RATES` env var (JSON).
- `get_currency_for_country(country)`: returns currency code, falls back to `"USD"`.
- `convert_usd(amount_usd, currency)`: converts and rounds to nearest int.

#### Changed — `FeedInsightsView` (`analyzer/views_feed.py`)
- **Dual job counts:** response now includes both `total_jobs_last_30d` (broadened) and `total_jobs_role_specific` (narrow role queryset).
- **Salary rework:** replaced `avg_salary_usd` with:
  - `salary_currency` — ISO 4217 code derived from user's country.
  - `avg_salary_role` — average salary scoped to role, converted to local currency.
  - `avg_salary_by_seniority` — `{ "senior": int, "mid": int, … }` per-seniority averages in local currency.
- **Aggregation scoping:** `top_companies`, `top_locations`, `employment_type_breakdown`, `remote_policy_breakdown`, `seniority_breakdown` now all use the narrow role-scoped queryset (`agg_qs`), not the broadened queryset.

#### Changed — `DashboardMarketInsightsView` (`analyzer/views_feed.py`)
- Added `salary_currency` and `avg_salary_role` to response.
- All aggregations (skills, salary) use narrow role-scoped queryset.

#### Added — Documentation: Notification Endpoints (`FRONTEND_API_GUIDE.md` §30.0)
- `GET /api/v1/notifications/` — paginated notification list with field table.
- `GET /api/v1/notifications/unread-count/` — unread badge count.
- `POST /api/v1/notifications/mark-read/` — mark one (`notification_id`) or all (`mark_all: true`).

#### Added — Documentation: Resume-Chat Submit (`FRONTEND_API_GUIDE.md` §29.2.1)
- `POST /api/v1/resume-chat/<id>/submit/` — full request body, response shape, field tables, error codes.

#### Fixed — Documentation: Plans/Subscribe Description (`FRONTEND_API_GUIDE.md` §32)
- Corrected `plans/subscribe` description: "Downgrade to free plan (402 if target plan is paid)".
- Added 3 notification endpoint rows to quick-reference table.

#### Changed — Documentation: §30.2 & §30.8 Response Shapes
- §30.2 response example and field table updated to reflect new salary/count fields.
- §30.8 market-insights response now includes `salary_currency` and `avg_salary_role`.
- TypeScript `InsightsResponse` interface updated.

---

## [0.39.0] — 2026-03-03

### Standardized Error Responses & Feed Skills Fix

#### Added — Custom DRF Exception Handler (`resume_ai/exception_handler.py`)
- All API error responses now return a standardized shape: `{"detail": "string", "errors": {...}}`.
- `detail` is always a human-readable string. `errors` (field-level dict) is only present on 400 validation errors.
- Extra keys like `balance`, `cost`, `limit`, `used` are preserved for enriched errors.
- Registered in `REST_FRAMEWORK['EXCEPTION_HANDLER']` in settings.

#### Changed — Views: `raise_exception=True`
- Converted all 18 views (accounts, payments, analyzer, chat) from manual `serializer.errors` returns to `serializer.is_valid(raise_exception=True)` — errors now flow through the custom handler.
- Fixed 5 Celery admin views using `'error'` key → `'detail'`.
- Fixed 2 chat views leaking raw Python exception strings to API clients → generic messages.

#### Added — Username Validation (`accounts/serializers.py`)
- Shared `_validate_username_common()` enforcing: min 3, max 30 chars, `^[a-zA-Z0-9_]+$`, reserved word blocklist.
- Applied to `RegisterSerializer`, `UpdateUserSerializer`, `GoogleCompleteSerializer`.

#### Added — Serializer Edge-Case Tests (`accounts/test_serializer_edge_cases.py`)
- 46 new tests across 3 test classes covering username, email, password, country code, mobile number validation, and standardized error shape.

#### Fixed — Feed Skills Scoping When Broadened
- **Bug:** When `_get_role_scoped_qs` auto-broadened (< 5 role-matched jobs), `top_skills` / trending-skills / skill-gap / market-insights were aggregated from ALL jobs — causing irrelevant skills (e.g. React, Node.js, CSS) to appear for Data Analyst roles.
- **Fix:** `_get_role_scoped_qs` now returns a 4th value (`role_qs`) — the narrow pre-broadened queryset. Skill aggregation in `FeedInsightsView`, `FeedTrendingSkillsView`, skill-gap radar, and `DashboardMarketInsightsView` now uses this narrow queryset. Job listing counts remain broadened.

#### Documentation
- `FRONTEND_API_GUIDE.md` §14 updated with standardized error shape, JavaScript error handler, username validation rules.
- `FRONTEND_API_GUIDE.md` §30.2/30.3/30.7/30.8 updated with skill-scoping clarification.

---

## [0.38.0] — 2026-03-05

### Role-Based Feed & Dashboard Scoping

#### Added — RoleFamily Model & LLM Task
- New `RoleFamily` model stores LLM-generated related job titles per unique title set (SHA-256 deduplicated, shared across users).
- New Celery task `generate_role_family_task` calls Claude 3.5 Haiku to produce 10–15 related titles. Auto-retries (2x) with exponential backoff.
- `post_save` signal on `JobSearchProfile` triggers role family generation when titles change.
- Migration: `0034_add_role_family_model.py`.

#### Added — Hybrid Two-Layer Role Scoping
- **Layer 1 — LLM Role Map:** Filters jobs by `title__icontains` against user titles + LLM-related titles.
- **Layer 2 — Embedding proximity:** Includes jobs within cosine distance ≤ 0.40 of user's resume embedding.
- **Auto-broadening:** Drops role filter if < 5 results, marks `broadened: true` in response.
- Applied to 4 endpoints: `feed/insights/`, `feed/trending-skills/`, `dashboard/skill-gap/`, `dashboard/market-insights/`.

#### Added — `?role=all` Query Param
- Pass `?role=all` on any of the 4 scoped endpoints to disable role scoping and see all roles.

#### Added — `role_filter` Response Object
- New `role_filter` object in insights and trending-skills responses: `source_titles`, `related_titles`, `method`, `scoped`, `broadened`.
- Cache keys now include `titles_hash` for role-differentiated caching.

#### Documentation
- `FRONTEND_API_GUIDE.md` §30.2, §30.3, §30.7, §30.8 updated with `?role` param, `role_filter` response, and hybrid scoping explanation.
- `ARCHITECTURE_FLOW.md` updated: `RoleFamily` in model list, `generate_role_family_task` in Celery table, signals description.

---

## [0.35.0] — 2026-03-04

### Architecture Simplification — 5-Phase Pipeline Refactor

#### Added — Resume Understanding at Upload (`analyzer/services/resume_understanding.py`)
- New `process_resume_upload()` performs a **single LLM call** at resume upload that produces both parsed resume data and a career profile in one shot.
- New Celery task `process_resume_upload_task` runs async after upload.
- New fields on `Resume` model: `parsed_content`, `career_profile`, `parsing_status`.
- `parsed_content` is copied to `ResumeAnalysis` at analysis time (no LLM call needed in pipeline).
- Migration: `0029_add_resume_understanding_fields.py`, `0030_backfill_resume_parsed_content.py`.

#### Added — Interview Question Bank (`analyzer/models.py`)
- New `InterviewQuestion` model: pre-seeded DB table of interview questions with category, difficulty, `why_asked`, `sample_answer`.
- Migration: `0031_add_interview_question_bank.py` (seeds 100+ questions across categories).

#### Changed — Analysis Pipeline Reduced from 5 Steps to 4
- **Removed Step 5 (`_step_resume_parse`)** from `ResumeAnalyzer.analyze()` — parsed content is now pre-computed at upload and copied into the analysis result.
- Pipeline steps: `extract_text → resolve_jd → llm_call → parse_result → done`.

#### Changed — Interview Prep Is Now Instant (No LLM, No Celery)
- `InterviewPrepService.generate()` queries the `InterviewQuestion` DB bank, selects relevant questions by matched skills/category, and returns immediately.
- Removed `generate_interview_prep_task` Celery task.
- No LLM call, no async polling — response is instant.

#### Removed — Bulk Analysis Endpoint
- Removed `BulkAnalyzeView` and its URL route `analyze/bulk/`.
- Frontend should use sequential single-analysis calls instead.

#### Removed — LLM Fallback in Job Matcher
- `EmbeddingMatcher` no longer falls back to an LLM call when embeddings are missing.
- Jobs without embeddings are silently skipped — pure vector similarity matching only.

#### Documentation
- `FRONTEND_API_GUIDE.md` updated: pipeline steps, `parsed_content` field, interview prep instant flow, bulk endpoint removed, changelog.
- `ARCHITECTURE_FLOW.md` updated: pipeline diagram (4 steps), file tree, external services, interview prep section, Celery tasks, URL listing.

---

## [0.34.1] — 2026-03-03

### Changed — Interview Prep, Cover Letter & Job Alerts Are Now Free

#### Interview Prep — Free
- Removed credit deduction from `InterviewPrepView.post()`.
- Removed `_refund_interview_prep_credits()` helper from `tasks.py`.

#### Cover Letter — Free
- Removed credit deduction from `CoverLetterView.post()`.
- Removed `_refund_cover_letter_credits()` helper from `tasks.py`.
- Response no longer includes `credits_used`/`balance`.

#### Job Alerts — Free Runs, Max 5 Active for Pro
- Removed credit deduction from `match_jobs_task` (no per-run cost).
- Removed credit refund logic on failed alert runs.
- **Re-activated `max_job_alerts`** on Plan model — Pro plans limited to **5 active alerts**.
- `JobAlertListCreateView.post()` now enforces `max_job_alerts` quota (returns 403 when exceeded).
- Free plan: no access (`job_notifications = false`, `max_job_alerts = 0`).
- Updated `seed_plans`: Pro/Pro-Yearly `max_job_alerts = 5`.

#### Credit Costs Updated
- `seed_credit_costs`: `job_alert_run = 0`, `interview_prep = 0`, `cover_letter = 0`.
- `_DEFAULT_COSTS` in `accounts/services.py` updated to match.

#### Documentation
- `FRONTEND_API_GUIDE.md` updated: all affected endpoints, error tables, route summary, plan tables, TypeScript types, and changelog references.

---

## [0.34.0] — 2026-03-03

### Features — Geography-Aware Feed & Analytics (India-First)

#### Added — Geo Fields on `UserProfile` (`accounts/models.py`)
- **`country`** CharField (default `"India"`) — User's country of residence, used as the base for geo-scoped feed and analytics.
- **`state`** CharField (blank) — State / province / region.
- **`city`** CharField (blank) — City of residence.
- Migration: `accounts/0019_add_geo_fields_to_userprofile.py`.

#### Added — `country` Field on `DiscoveredJob` (`analyzer/models.py`)
- **`country`** CharField (blank, indexed) — Normalised country for each job posting. Populated by the crawler bot going forward.
- Migration: `analyzer/0028_add_country_to_discoveredjob.py`.

#### Changed — Profile Serializers (`accounts/serializers.py`)
- `UserProfileSerializer`, `UserSerializer`, `UpdateUserSerializer` now include `country`, `state`, `city` as readable and writable fields.
- `PUT /api/v1/auth/me/` accepts and persists all three geo fields.

#### Changed — Feed Jobs View — India-First Geo Ordering (`analyzer/views_feed.py`)
- `FeedJobsView` annotates results with `geo_priority` (`0` = user's country, `1` = global) using Django `Case/When`. Local jobs appear first.
- New query parameters: `search`, `country`, `industry`, `skills`, `salary_min`.
- `_INDIA_KEYWORDS` heuristic set (~30 Indian city names) for backward-compatible location matching on legacy data without a `country` field.
- Response now includes top-level `country` field and per-job `country`.

#### Changed — Analytics Endpoints — Geo-Scoped (`analyzer/views_feed.py`)
- `FeedInsightsView`, `FeedTrendingSkillsView`, `DashboardSkillGapView`, `DashboardMarketInsightsView`, `FeedRecommendationsView` all accept `?country=` query param (default: user profile country, `"all"` for global).
- Cache keys include country for per-country caching.
- Responses include `country` field where applicable.

#### Changed — Ingest Serializer (`analyzer/serializers_ingest.py`)
- `DiscoveredJobIngestSerializer` now accepts optional `country` field from crawler bot payloads.

#### Changed — Feed Serializer (`analyzer/serializers_feed.py`)
- `FeedJobSerializer` now includes `country` in response fields.

#### Changed — Admin Panels
- `UserProfile` admin: `list_display`, `list_filter`, `search_fields` include geo fields.
- `DiscoveredJob` admin: `list_display`, `list_filter`, `search_fields`, fieldsets include `country`.

#### Documentation
- `FRONTEND_API_GUIDE.md` updated: profile endpoints, all feed/analytics endpoints, TypeScript types, and DiscoveredJob table reference reflect geo fields.

---

## [0.33.0] — 2026-03-03

### Features — Default Resume System

#### Added — `is_default` Field on `Resume` (`analyzer/models.py`)
- **`is_default` BooleanField** — Marks exactly one resume per user as the "default" powering all personalised surfaces (feed, dashboard analytics, skill extraction).
- Partial unique constraint `unique_default_resume_per_user` ensures at most one default per user at the database level.
- **`set_as_default()`** instance method — Clears all other defaults for the user, marks self, saves.
- **`get_default_for_user(cls, user)`** classmethod — Returns the default `Resume` or `None`.
- **Auto-default on first upload** — `get_or_create_from_upload()` automatically sets `is_default=True` when the user has no existing default.

#### Added — `SetDefaultResumeView` (`analyzer/views.py`)
- `POST /api/v1/resumes/<uuid:pk>/set-default/` — Sets a resume as the user's default. Validates ownership, calls `set_as_default()`, busts dashboard cache.

#### Changed — `ResumeDeleteView` Default Fallback
- When deleting the current default resume, the most recently uploaded remaining resume is auto-promoted to default.

#### Changed — Dashboard Analytics Scoped to Default Resume
- `DashboardStatsView` now builds `analytics_qs` scoped to the default resume for score trends, grade distributions, keyword match trends, and benchmark calculations. User-wide counts (total analyses, resumes, etc.) remain unscoped.
- Response includes `default_resume_id` field.

#### Changed — Feed Personalisation Scoped to Default Resume
- `_get_user_skills()` and `FeedJobsView._get_user_embedding()` in `views_feed.py` now prefer the default resume's `JobSearchProfile` for skill extraction and embedding similarity. Falls back to any available JSP when no default is set.

#### Changed — Serializers & URLs
- `ResumeSerializer` now includes `is_default` in response fields.
- New URL route `resumes/<uuid:pk>/set-default/` wired to `SetDefaultResumeView`.

#### Migrations
- `analyzer/0027_add_default_resume.py` — Adds `is_default` field and partial unique constraint.

#### Tests
- 15 new tests in `analyzer/tests/test_default_resume.py` across 4 test classes: model logic (auto-default, swap, idempotent, get_default, uniqueness constraint), API (set-default success/404/forbidden/unauth), list response (is_default flag), delete fallback (promotes next, last resume, non-default keeps original).

### Bug Fixes

- **Chat 500 fix** — `POST /api/v1/resume-chat/<id>/message/` returned `NameError: name 'ResumeChatTextMessageSerializer' is not defined`. Added missing imports for `ResumeChatTextMessageSerializer` and `process_text_message` in `views_chat.py`.
- **Premium template expiry** — Pro users with expired plans could still access premium templates. Added `plan_valid_until` expiry check to the `accessible` field and plan gating logic.
- **Credit cost seed** — Added `python manage.py seed_credit_costs` to `entrypoint.sh` so `interview_prep` and other credit cost rows are seeded on deployment.

### Chat Enhancements

- **Markdown in AI responses** — Updated `_TEXT_CHAT_SYSTEM_PROMPT` to instruct the LLM to use Markdown formatting (bold, bullets, headers) in conversational responses. Frontend should render the `content` field with a Markdown component.

### Documentation

- **FRONTEND_API_GUIDE.md** bumped to v0.33.0 with default resume concept section, `set-default` endpoint docs, updated TypeScript `Resume` interface (`is_default`, `days_since_upload`, `last_analyzed_at`), dashboard scoping docs, `default_resume_id` field, premium template expiry notes, chat markdown rendering note, and endpoint reference table updates.

---

## [0.29.0] — 2026-03-02

### ⚠ Breaking Changes
- **`credit_usage` data contract fixed** — Dashboard stats `credit_usage` items now use `{month, type, subtype, count, total}` format instead of `{month, type, total}`. The `type` field maps from raw `transaction_type` to `"debit"`/`"credit"`. New `subtype` field indicates the specific kind (`"analysis"`, `"topup"`, `"plan"`, `"refund"`, `"upgrade_bonus"`, `"admin"`). `total` is now the absolute sum of amounts (always positive).

### Features — Dashboard Stats Expansion & Activity Tracking

#### Added — `UserActivity` Model (`analyzer/models.py`)
- Tracks daily user actions with `user`, `date`, `action_count`, and `actions` (JSON breakdown by action type).
- Seven action constants: `ACTION_ANALYSIS`, `ACTION_RESUME_GEN`, `ACTION_INTERVIEW_PREP`, `ACTION_COVER_LETTER`, `ACTION_JOB_ALERT_RUN`, `ACTION_BUILDER_FINALIZE`, `ACTION_LOGIN`.
- `record(cls, user, action)` classmethod — thread-safe upsert using `F()` expressions.
- `get_streak(cls, user)` classmethod — returns `(streak_days, actions_this_month)` by walking backwards through consecutive dates.
- Unique constraint on `(user, date)`.

#### Changed — `DashboardStatsView` Expanded (~25 new fields)
- **Best/worst scores**: `best_ats_score`, `worst_ats_score` from `Max`/`Min` aggregates.
- **Keyword match trend**: `keyword_match_trend` array (parallel to `score_trend`) with `{jd_role, keyword_match_percent, created_at}`.
- **Resume counts**: `resume_count` (uploaded resumes).
- **Generation counts**: `generated_resumes_total/done`, `interview_preps_total/done`, `cover_letters_total/done`.
- **Chat builder**: `chat_sessions_active`, `chat_sessions_completed`.
- **Job alerts**: `job_alerts_count`, `active_job_alerts`, `total_job_matches`, `matches_applied`, `matches_relevant`, `matches_irrelevant`.
- **LLM usage**: `llm_calls`, `llm_tokens_used`, `llm_cost_usd` aggregated from `LLMResponse`.
- **Plan usage**: `plan_usage` object with `plan_name`, `analyses_this_month`, `analyses_limit`, `usage_percent`. `null` if no plan or unlimited.
- **Activity streak**: `activity_streak` object with `streak_days` and `actions_this_month`.

#### Changed — `UserActivity.record()` Wired into 8 Locations
- `AnalyzeResumeView.post` → `ACTION_ANALYSIS`
- `GenerateResumeView.post` → `ACTION_RESUME_GEN`
- `InterviewPrepView.post` → `ACTION_INTERVIEW_PREP`
- `CoverLetterView.post` → `ACTION_COVER_LETTER`
- `JobAlertManualRunView.post` → `ACTION_JOB_ALERT_RUN`
- `ResumeChatFinalizeView.post` → `ACTION_BUILDER_FINALIZE`
- `LoginView.post` → `ACTION_LOGIN`
- `GoogleLoginView.post` → `ACTION_LOGIN`

#### Migrations
- `analyzer/0023_add_user_activity_model` — Creates `UserActivity` table with unique `(user, date)` constraint.

---

## [0.28.0] — 2026-03-02

### Features — Company Intelligence & Enriched Job Crawl

#### Added — Company Models (`analyzer/models.py`)
- **`Company`** — Brand-level umbrella (UUID PK, slug, logo_url, website, industry, employee_size_range, headquarters, tech_stack JSON, is_active). Represents a single employer brand (e.g. "Stripe").
- **`CompanyEntity`** — Per-country legal entity (FK → Company, display_name, country ISO-3166, registration_id, is_indian_entity flag, is_active). Unique constraint on `(company, country, display_name)`. Handles multi-country employers (e.g. "Stripe Inc." US vs "Stripe India Pvt Ltd" IN).
- **`CompanyCareerPage`** — Career page URLs tied to an entity (FK → CompanyEntity, url, label, country, crawl_frequency choice `daily`/`weekly`/`monthly`, is_active, last_crawled_at). Supports multiple pages per entity (intern vs experienced, different departments).

#### Added — Enriched DiscoveredJob Fields (15 new columns)
- **`source_page_url`** (URL) — The search/career page URL we crawled (vs `url` which is the actual job posting link).
- **`company_entity`** (FK → CompanyEntity, nullable) — Links a discovered job to a known company entity.
- **`skills_required`** (JSONField) — LLM-extracted list of required skills, e.g. `["Python", "AWS", "Kubernetes"]`.
- **`skills_nice_to_have`** (JSONField) — LLM-extracted nice-to-have skills.
- **`experience_years_min`** / **`experience_years_max`** (PositiveSmallIntegerField, nullable) — Experience range.
- **`employment_type`** (CharField choices) — `full_time`, `part_time`, `contract`, `internship`, `freelance`, or blank.
- **`remote_policy`** (CharField choices) — `onsite`, `hybrid`, `remote`, or blank.
- **`seniority_level`** (CharField choices) — `intern`, `junior`, `mid`, `senior`, `lead`, `manager`, `director`, `executive`, or blank.
- **`industry`** (CharField) — Industry sector extracted by LLM.
- **`education_required`** (CharField) — Education requirement (e.g. `bachelor`, `master`, `none`).
- **`salary_min_usd`** / **`salary_max_usd`** (DecimalField, nullable) — LLM-normalised annual USD salary range.

#### Changed — LLM Job Extraction Prompt (`analyzer/services/job_sources/firecrawl_source.py`)
- Expanded from 7-field to 17-field schema per job listing. Same LLM call, ~$0.002 marginal cost per page.
- New extraction fields: `skills_required`, `skills_nice_to_have`, `experience_years_min`, `experience_years_max`, `employment_type`, `remote_policy`, `seniority_level`, `industry`, `education_required`, `salary_min_usd`, `salary_max_usd`.
- Added `_safe_int()` helper for robust integer parsing from LLM output.

#### Changed — `RawJobListing` Dataclass (`analyzer/services/job_sources/base.py`)
- Expanded from 10 to 21 fields to carry enriched data through the pipeline.

#### Changed — Crawl Tasks (`analyzer/tasks.py`)
- Both `crawl_jobs_daily_task` and `crawl_jobs_for_alert_task` updated to persist all enriched fields into `DiscoveredJob.objects.get_or_create()` defaults.

#### Changed — Serializers & Admin
- `DiscoveredJobSerializer` now exposes all 23 fields (10 original + 13 enriched).
- `CompanyAdmin` with `CompanyEntityInline` and `CompanyCareerPageInline`.
- `CompanyEntityAdmin` with `CompanyCareerPageInline` and `career_page_count` column.
- `CompanyCareerPageAdmin` with autocomplete and field filters.
- `DiscoveredJobAdmin` updated with enriched field display, expanded fieldsets, and new filters (`employment_type`, `remote_policy`, `seniority_level`).

#### Migrations
- `analyzer/0022_add_company_models_enrich_discovered_job` — Creates Company, CompanyEntity, CompanyCareerPage tables and adds 15 columns to DiscoveredJob.

---

## [0.27.0] — 2026-03-01

### Features — Resume Data Extraction (Parsed Content)

#### Added — Resume Parser Service (`analyzer/services/resume_parser.py`)
- **`parse_resume_text(resume_text)`** — LLM-based extraction of structured personal data (contact, summary, experience, education, skills, certifications, projects) from raw resume text. Lightweight prompt focused on faithful extraction (no rewriting). Uses same JSON schema as `GeneratedResume.resume_content` for consistency. Low temperature (0.1) for deterministic output.

#### Added — `parsed_content` Field on `ResumeAnalysis`
- **`parsed_content` JSONField** — Stores structured resume data extracted during analysis pipeline. Nullable (null until extraction completes or if extraction fails). Cleared on soft-delete.

#### Added — Pipeline Step `resume_parse`
- **`STEP_RESUME_PARSE`** — New pipeline step after `parse_result`. Calls `parse_resume_text()` to extract structured data from `resume_text`. **Non-fatal**: if extraction fails, the analysis still completes successfully with `parsed_content = null`.
- Pipeline order: `pending` → `pdf_extract` → `jd_scrape` → `llm_call` → `parse_result` → `resume_parse` → `done`.

#### Changed — Chat Builder Pre-fill (`_prefill_from_resume`)
- Now falls back to `ResumeAnalysis.parsed_content` when no `GeneratedResume` exists. Priority: `GeneratedResume.resume_content` → `ResumeAnalysis.parsed_content` → `UserProfile` data. This means users who upload + analyze a resume can now use it as a base in the chat builder without needing to run the full resume generation flow first.

#### Changed — Serializers & Admin
- `ResumeAnalysisDetailSerializer` now includes `parsed_content` in the response.
- `ResumeAnalysisAdmin.readonly_fields` includes `parsed_content`.

#### Migrations
- `analyzer/0021_add_parsed_content_to_analysis` — Adds `parsed_content` JSONField to `ResumeAnalysis` and `resume_parse` to `pipeline_step` choices.

#### Tests
- 24 new tests across 5 test classes: `parse_resume_text()` (success, code fences, empty text, no API key, schema validation), `_step_resume_parse` pipeline integration (populate, skip-if-parsed, skip-if-no-text, non-fatal failure, step ordering), model (nullable, stores JSON, soft-delete clears, step choice valid), chat builder fallback (uses parsed, prefers generated, falls back to any analysis, falls to profile, ensures all keys), serializer (includes parsed_content, null case).

---

## [0.26.0] — 2026-03-01

### Features — Conversational Resume Builder

#### Added — Resume Chat Models
- **`ResumeChat` model** — UUID PK, 11-step wizard (`start` → `contact` → `target_role` → `experience_input` → `experience_review` → `education` → `skills` → `certifications` → `projects` → `review` → `done`). Sources: `scratch`, `profile`, `previous`. Status: `active`, `completed`, `abandoned`. Progressive `resume_data` JSONField follows `GeneratedResume.resume_content` schema. Navigation: `advance_step()`, `go_back()`, `step_number`, `total_steps`.
- **`ResumeChatMessage` model** — UUID PK. Roles: `user`, `assistant`, `system`. `ui_spec` JSONField for frontend rendering instructions. `extracted_data` for partial resume updates. Linked to `LLMResponse` for cost tracking.

#### Added — Service Layer (`analyzer/services/resume_chat_service.py`)
- **`start_session(user, source, base_resume_id)`** — Creates session, pre-fills from profile or previous resume.
- **`process_step(chat, action, payload)`** — Dispatches to per-step handlers, records messages, advances wizard.
- **`finalize_resume(chat, template, format)`** — Creates `GeneratedResume` record from `resume_data`.
- **10 UI spec types**: `editable_card`, `buttons`, `single_select`, `multi_select_chips`, `text_input`, `textarea`, `form_group`, `card_list`, `preview`, `template_picker`.
- **Pre-fill sources**: `_prefill_from_profile()` uses `User` + `UserProfile` + `JobSearchProfile`; `_prefill_from_resume()` clones `GeneratedResume.resume_content`.
- **LLM calls**: `_llm_structure_experience()` (free-text → structured JSON), `_llm_polish_resume()` (summary + ATS optimization). Only 1-2 calls per session.

#### Added — API Endpoints
- **`POST /api/v1/resume-chat/start/`** — Start new session (scratch/profile/previous). Max 5 active sessions per user.
- **`GET /api/v1/resume-chat/`** — List sessions (optional `?status=` filter). Returns up to 20, newest first.
- **`GET /api/v1/resume-chat/<uuid>/`** — Session detail with all messages and UI specs.
- **`POST /api/v1/resume-chat/<uuid>/submit/`** — Submit step action (`continue`, `back`, `update_card`, `submit`, `skip`, etc.). Returns new messages + progress.
- **`POST /api/v1/resume-chat/<uuid>/finalize/`** — Generate PDF/DOCX. Deducts 2 credits. Returns `GeneratedResume` UUID for polling. Premium template gating applied. Auto-refund on failure.
- **`DELETE /api/v1/resume-chat/<uuid>/`** — Delete session and all messages.
- **`GET /api/v1/resume-chat/resumes/`** — List user's resumes available as base for `source=previous`.

#### Added — Celery Task
- **`render_builder_resume_task`** — Renders `resume_content` to PDF/DOCX via template registry. Retries on transient errors. Refunds credits on failure.

#### Added — Credit Cost
- **`resume_builder = 2`** credits in `_DEFAULT_COSTS` fallback and `seed_credit_costs` management command.

#### Added — Admin
- **`ResumeChatAdmin`** — List display: ID, user, source, step, status, timestamps. Filters: status, source, step.
- **`ResumeChatMessageAdmin`** — List display: ID, chat, role, step, timestamp. Filters: role, step.

#### Migrations
- `analyzer/0019_add_resume_chat_models` — Creates `ResumeChat` and `ResumeChatMessage` tables with indexes.
- `analyzer/0020_make_generated_resume_analysis_nullable` — Makes `GeneratedResume.analysis` nullable for builder-created resumes.

#### Tests
- 36 new tests across 10 test classes: model CRUD, step navigation, service (start/process/finalize), API (start/list/detail/submit/finalize/delete/resumes), Celery task (render/failure/refund), credit deduction, session limits.

---

## [0.25.1] — 2026-02-28

### Email Template Branding

- **Logo**: All 7 email templates now display the i-Luffy logo (`https://iluffy.in/logo.png`) in the header, linked to `https://iluffy.in`.
- **Footer links**: Added `https://iluffy.in` landing page link, plus Privacy, Terms, and Data Usage links (`iluffy.in/privacy`, `iluffy.in/terms`, `iluffy.in/data-usage`) to all email footers (HTML + plain text).
- **Domain separation**: Landing page links → `iluffy.in`; in-app links (dashboard, manage preferences, etc.) → `app.iluffy.in` via `FRONTEND_URL` env var.

---

## [0.25.0] — 2026-02-28

### Features — Resume Template Marketplace

#### Added — Resume Template Model & API
- **`ResumeTemplate` model** — UUID PK, `name`, `slug` (unique), `description`, `category` (professional/creative/academic/executive), `preview_image` (ImageField), `is_premium` (bool), `is_active` (bool), `sort_order` (int). Managed via Django Admin with inline editing.
- **`GET /api/v1/templates/`** — List active templates. Returns `accessible` flag based on user's plan. Auth required.
- **`premium_templates` boolean on `Plan` model** — Gates access to premium templates. Default: `false`.
- **Premium template gating** in `POST /api/v1/analyses/<id>/generate-resume/` — Returns 403 with `is_premium` and `template` slug when user lacks access.
- **DB-validated template slugs** — Template parameter now validated against active templates in DB (previously hardcoded). Invalid slugs return 400 with list of available options.

#### Added — 5 Resume Templates
- **`ats_classic`** (free) — Clean ATS-friendly layout with clear section headings (existing, unchanged).
- **`modern`** (premium) — Contemporary design with teal (#0d7377) color accents and dot-separated contact info.
- **`executive`** (premium) — Formal serif layout with dark charcoal (#1b2631) tones. Uppercase name, "EXECUTIVE SUMMARY", "PROFESSIONAL EXPERIENCE" headings.
- **`creative`** (premium) — Vibrant purple (#6c3483) theme with colored section backgrounds, emoji contact icons, and arrow bullets.
- **`minimal`** (premium) — Generous whitespace, muted grey section titles, no borders or dividers.

#### Added — Infrastructure
- **Template registry** (`analyzer/services/template_registry.py`) — Central slug-to-renderer mapping with lazy loading. Supports `get_renderer(slug, format)` and `get_available_slugs()`.
- **`seed_templates` management command** — `python manage.py seed_templates` creates 5 default templates (idempotent, updates on re-run).
- **`ResumeTemplateAdmin`** — Django Admin with list_display, list_filter, list_editable (is_premium, is_active, sort_order), prepopulated slug.
- **`tasks.py` updated** — Uses template registry instead of hardcoded renderer imports.

#### Migrations
- `analyzer/0018_add_resume_template_model` — Creates ResumeTemplate table.
- `accounts/0018_add_premium_templates_to_plan` — Adds `premium_templates` boolean to Plan.

#### Tests
- 26 new tests across 7 test classes: model CRUD, registry, renderer output (full/empty/minimal/special-chars), API listing, plan gating (free blocked, pro allowed, inactive rejected), seed command, Plan field.

---

## [0.24.0] — 2026-02-28

### Features — Email Verification, Bulk Analysis, Interview Prep, Cover Letter, Rate Limit Headers

#### ⚠ Breaking Changes
- **API versioning** — All endpoints moved from `/api/v1/` to `/api/v1/`. The old `/api/v1/` prefix returns 404. Frontend must update `API_URL` config (e.g. `http://localhost:8000/api/v1/v1`). DRF `URLPathVersioning` with `DEFAULT_VERSION = 'v1'`, `ALLOWED_VERSIONS = ['v1']`.
- **Registration email flow** — Registration no longer sends welcome email immediately. Sends verification email instead. Welcome email sent only after `POST /api/v1/auth/verify-email/`.

#### Added — Email Verification
- **`EmailVerificationToken` model** — Token-based email verification with 24h expiry.
- **`POST /api/v1/auth/verify-email/`** — Verify email with token. Activates account and sends welcome email.
- **`POST /api/v1/auth/resend-verification/`** — Resend verification email (rate-limited).
- **`is_email_verified` field** — Added to register, login, and `GET /api/v1/auth/me/` responses.
- **`email-verification` email template** — Seeded via `seed_email_templates`.

#### Added — Bulk Analysis
- **`POST /api/v1/analyze/bulk/`** — Analyze one resume against up to 10 job descriptions in a single call. Returns array of analysis IDs. Each deducts 1 credit. Atomic credit deduction.

#### Added — Interview Prep Generation
- **`InterviewPrep` model** — AI-generated interview questions (behavioral, technical, situational, role-specific, gap-based) with difficulty levels and sample answers.
- **`POST /api/v1/analyses/<id>/interview-prep/`** — Trigger generation (1 credit). Returns 202.
- **`GET /api/v1/analyses/<id>/interview-prep/`** — Poll status/results.
- **`GET /api/v1/interview-preps/`** — List all user's interview preps (paginated).
- **Celery task** — `generate_interview_prep_task` with retry and credit refund on failure.

#### Added — Cover Letter Generation
- **`CoverLetter` model** — AI-generated cover letter with tone selection (`professional`, `conversational`, `enthusiastic`). Fields: `content` (plain text), `content_html`.
- **`POST /api/v1/analyses/<id>/cover-letter/`** — Trigger generation (1 credit). Returns 202.
- **`GET /api/v1/analyses/<id>/cover-letter/`** — Poll status/results.
- **`GET /api/v1/cover-letters/`** — List all user's cover letters (paginated).
- **Celery task** — `generate_cover_letter_task` with retry and credit refund on failure.

#### Added — Resume Version History
- **`ResumeVersion` model** — Tracks resume evolution via `previous_resume` FK chain.
- **`GET /api/v1/resumes/<uuid>/versions/`** — Version history with `version_number`, `best_ats_score`, `best_grade`. Auto-linked when re-uploading same filename.

#### Added — Rate Limit Headers
- **`RateLimitHeadersMiddleware`** — All responses now include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers. Frontend can show proactive warnings before users hit 429.
- **`HeaderAwareAnonThrottle` / `HeaderAwareUserThrottle`** — Custom throttle classes that expose rate limit metadata.

#### Added — New Credit Costs
- `interview_prep = 1` credit
- `cover_letter = 1` credit

### Infrastructure & Observability

#### Added
- **Structured JSON logging** — Production logs now emit JSON via `python-json-logger` (`JsonFormatter`). Fields: `timestamp`, `logger`, `level`, `message`, `service: resume-ai`. Local dev keeps human-readable `simple` formatter. New dependency: `python-json-logger==3.3.0`.
- **Prometheus metrics endpoint** — `GET /metrics` via `django-prometheus==2.3.1`. Built-in HTTP request/response metrics + custom app metrics in `resume_ai/metrics.py`:
  - `resume_ai_analysis_duration_seconds` — histogram by status (done/failed)
  - `resume_ai_analyses_total` — counter by status (queued/done/failed)
  - `resume_ai_llm_tokens_total` — counter by provider/operation/token_type
  - `resume_ai_llm_requests_total` — counter by provider/operation/status
  - `resume_ai_credit_operations_total` — counter by operation type
  - `resume_ai_payment_failures_total` — counter by reason
  - `resume_ai_celery_task_duration_seconds` — histogram by task/status
  - `resume_ai_active_analyses` — gauge of in-flight analyses
- **Flower monitoring dashboard** — Celery monitoring via Flower (`flower==2.0.1`). Runs as separate Railway service (`SERVICE_TYPE=flower`). Basic auth via `FLOWER_USER`/`FLOWER_PASSWORD` env vars. Persistent task history in `/tmp/flower.db`.
- **Celery monitoring API endpoints** (admin-only, `IsAdminUser`):
  - `GET /api/v1/admin/celery/workers/` — active workers, stats, pool info
  - `GET /api/v1/admin/celery/tasks/active/` — currently executing tasks
  - `GET /api/v1/admin/celery/tasks/<task_id>/` — task status lookup by ID
  - `GET /api/v1/admin/celery/queues/` — Redis queue lengths

#### Changed
- **Gunicorn timeout** — Reduced from 120s to 110s (Procfile + entrypoint.sh). Ensures Gunicorn responds before Railway's proxy timeout kills the connection.
- **Entrypoint** — Added `flower` service type. Valid `SERVICE_TYPE` values: `web`, `worker`, `beat`, `flower`.

#### Dependencies Added
- `python-json-logger==3.3.0`
- `django-prometheus==2.3.1`
- `flower==2.0.1`

---

## [0.23.0] — 2026-02-28

### Code Quality & Test Coverage Sweep

#### Added
- **PDF magic-byte validation** — `PDFExtractor._validate_pdf_magic()` checks `%PDF` magic bytes before processing. Non-PDF files (DOCX, HTML, images) are rejected immediately with a clear error, preventing wasted CPU on invalid uploads.
- **DOCX renderer sanitisation** — Added `_safe()` helper to `resume_docx_renderer.py`. Strips null bytes and ASCII control characters from all user-supplied text before writing to DOCX. Consistent with PDF renderer's `_safe()` pattern.
- **41 new tests** in `analyzer/tests/test_code_quality.py`:
  - `PDFMagicByteTests` (10) — valid/invalid magic bytes across file types and input modes (path, FieldFile, BytesIO).
  - `DOCXSafeTests` (8) — null byte stripping, control char removal, tab/newline preservation, non-string handling, full DOCX render with special characters.
  - `AnalysisStatusViewTests` (4) — DB fallback, Redis cache hit, 404, user isolation.
  - `AnalysisPDFExportViewTests` (4) — incomplete analysis, 404, user isolation, on-the-fly generation fallback.
  - `RetryAnalysisViewTests` (6) — success, already-done, already-processing, insufficient credits, 404, user isolation.
  - `ResumeManagementTests` (8) — list, search, ordering, delete, blocked delete (active analysis), 404, user isolation.
  - `AccountDeletionCascadeTests` (1) — wallet + transaction cleanup on account deletion.
- **Total tests: 443** (up from 402).

#### Changed
- **Inline imports consolidated** — 9 inline `from accounts.services import ...` calls in `analyzer/views.py` replaced with a single top-level import. Celery tasks (`tasks.py`) kept inline per Celery best practice.

#### Backlog Audit
- **10 TODO items** marked as already done (were implemented but unchecked): email required on registration, duplicate email blocking, country code validation, mobile number min length, payment notes filtering, preferences schema validation, Firecrawl error sanitisation, PDF try/finally, except cleanup, prompt template caching.
- **2 TODO items** marked N/A: job tracking feature flag (endpoint removed), prompt template optimisation (accepted design).

---

## [0.22.0] — 2026-02-28

### Plans, Pricing & Contact Form

#### Added
- **`original_price` field** on Plan model — stores pre-discount price for strikethrough display on pricing page.
- **3 default plans seeded** via `seed_plans`: Free (₹0), Pro Monthly (₹399, was ₹599), Pro Yearly (₹3,999, was ₹7,188).
- **Job alert quota removed** — unlimited alerts when `job_notifications = true`. `max_job_alerts` field kept but deprecated (no longer enforced).
- **`ContactSubmission` model** — landing-page contact form (name, email, subject, message). Read-only in Django Admin.
- **`POST /api/v1/auth/contact/`** — public endpoint for contact form submissions (no auth, anon-throttled).
- **Auto-sync plans to Razorpay** — `post_save` signal on Plan automatically creates a Razorpay plan whenever a paid plan is saved without a `razorpay_plan_id`. Skips free plans, already-synced plans, and test environments.
- **Admin feedback on new plan creation** — `PlanAdmin.save_model` shows success/failure message for Razorpay sync on new paid plans.

#### Fixed
- **PostgreSQL `IntegrityError`** on Plan creation via Admin — migration 0014 sets server-side `DEFAULT ''` on `razorpay_plan_id` column.

#### Migrations
- `accounts/0014_fix_razorpay_plan_id_server_default`
- `accounts/0015_add_original_price_to_plan`
- `accounts/0016_add_contact_submission`

#### Tests
- **402 tests passing** (no regressions).

---

## [0.21.0] — 2026-02-27

### Frontend–Backend Gap Fixes (28 items)

Systematic audit of 32 frontend-reported gaps. 4 already existed, 28 implemented across P0/P1/P2 priorities. P3 items documented as backlog TODOs.

#### P0 — Critical Fixes
- **`first_name` / `last_name` writable on `PUT /api/v1/auth/me/`** — Both fields now accepted by `UpdateUserSerializer` and persisted on the `User` model.
- **`keyword_match_percent` in `score_trend`** — Each trend entry now includes `keyword_match_percent` extracted from the `scores` JSONField.
- **Aggregated `top_missing_keywords`** in dashboard stats — Top 10 missing keywords across the user's last 20 analyses, computed via `Counter`.
- **`credit_usage` history (monthly)** in dashboard stats — Wallet transactions grouped by month and type (`debit`/`credit`), returned as a list of `{month, type, total}` objects.

#### P1 — Core Feature Gaps
- **`DELETE /api/v1/generated-resumes/<uuid:pk>/`** — Delete a generated resume (file removed from R2, record deleted). Ownership-checked.
- **Server-side search/filter/sort on analyses** — `AnalysisListView` now supports `?search=` (role/company/industry), `?status=`, `?score_min=`, `?score_max=`, `?ordering=` (created_at, ats_score).
- **Server-side search/filter/sort on resumes** — `ResumeListView` now supports `?search=` (filename), `?ordering=` (uploaded_at, original_filename, file_size).
- **Payment history pagination** — `PaymentHistoryView` now uses DRF `PageNumberPagination` (page_size=20). Response format changed from `{count, payments}` to standard `{count, next, previous, results}`.
- **`total_matches`** on `JobAlertSerializer` — Each job alert now includes the total count of associated matches.
- **`POST /api/v1/resumes/bulk-delete/`** — Bulk-delete up to 50 resumes. Skips resumes with active (processing/pending) analyses; returns `{deleted, skipped, errors}`.
- **`weekly_job_matches`** in dashboard stats — Count of job matches created in the last 7 days.

#### P2 — UX Improvements
- **Social links CRUD** — Added `website_url`, `github_url`, `linkedin_url` (URLFields) to `UserProfile`. Readable via `GET /api/v1/auth/me/`, writable via `PUT /api/v1/auth/me/`.
- **Resume staleness indicators** — `ResumeSerializer` now includes `days_since_upload` (integer) and `last_analyzed_at` (datetime or null).
- **`GET /api/v1/shared/<uuid:token>/summary/`** — Lightweight public endpoint returning `{ats_score, overall_grade, jd_role, jd_company}` for social card previews. No auth required.
- **`GET /api/v1/analyses/compare/?ids=<uuid>,<uuid>`** — Side-by-side comparison of 2–5 analyses. Returns list of `{id, jd_role, jd_company, ats_score, overall_grade, created_at, scores}`. Ownership-checked.
- **`GET /api/v1/auth/wallet/transactions/export/`** — CSV download of all wallet transactions (columns: date, type, amount, description, balance_after).
- **`POST /api/v1/auth/avatar/`** — Upload avatar image (JPEG/PNG/WebP, max 2 MB). Validates with Pillow. Stores in R2, updates `avatar_url` on profile.
- **`DELETE /api/v1/auth/avatar/`** — Remove avatar (deletes file from R2, clears `avatar_url`).
- **`industry_benchmark_percentile`** in dashboard stats — User's ATS score percentile rank vs all platform users. `null` if no analyses exist.

#### Migration
- `accounts/0013_add_social_links_to_userprofile` — Adds `website_url`, `github_url`, `linkedin_url` to `UserProfile`.

#### Tests
- **42 new tests** in `analyzer/tests/test_gap_fixes.py` covering all P0/P1/P2 features.
- **Total tests: 402** (up from 360).

#### Breaking Changes
- **Payment history response format** — `GET /api/v1/auth/payments/history/` now returns `{count, next, previous, results}` instead of `{count, payments}`. Parameter `?limit=` replaced by `?page=`.

#### P3 — Documented as Backlog (not implemented)
- Activity streak (#10)
- Skill gap analysis (#9)
- Professional profile (#3) — consider reusing `JobSearchProfile`
- Weekly market insight (#14) — derive from `DiscoveredJob` data
- Application tracker (#8) — consider extending `JobMatch`
- Push notifications (#28) — defer until mobile app ships

---

## [0.20.0] — 2026-02-27

### Dynamic Razorpay Plan Sync

#### Added
- **`razorpay_plan_id` field on Plan model** — Stores the current Razorpay plan ID. Auto-managed by the sync system; read-only in admin.
- **`sync_razorpay_plan()` service function** — Creates a new immutable Razorpay Plan via API when price or billing cycle changes. Old plans are preserved in Razorpay for audit and existing subscriber billing.
- **`_get_razorpay_plan_id()` rewritten** — 3-tier priority: (1) model field, (2) env var fallback with auto-backfill, (3) placeholder in dev/test or `ValueError` in production.
- **PlanAdmin overhaul:**
  - `save_model()` — Auto-creates new Razorpay plan when price or billing_cycle changes on a paid plan. Shows success/error message.
  - **"Duplicate selected plans"** admin action — Copies plan with `(Copy N)` suffix, deactivated, no `razorpay_plan_id`.
  - **"Sync with Razorpay"** admin action — Manual sync for selected plans.
  - **"Activate / Deactivate"** admin actions — Bulk toggle `is_active`.
  - **Delete disabled** — `has_delete_permission() → False`. Plans are deactivated, never deleted (audit trail).
  - `razorpay_plan_id` shown as read-only in a dedicated "Razorpay" fieldset.
- **`sync_razorpay_plans` management command** — Syncs all active paid plans missing a `razorpay_plan_id`. Supports `--force` (recreate all) and `--dry-run` (preview).
- **18 new tests** in `accounts/test_razorpay_sync.py`:
  - `sync_razorpay_plan()` — create, skip, force, free plan rejection, API error, yearly period.
  - `_get_razorpay_plan_id()` — model priority, test placeholder, production error.
  - `PlanAdmin` — delete denied, save_model auto-sync, no-sync on unchanged price, duplicate action, duplicate counter.
  - Management command — sync, skip synced, force resync, dry run.
- **Migration:** `0012_add_razorpay_plan_id_to_plan`.
- **Total tests: 360** (up from 342).

#### Design Notes
- **Existing subscribers are grandfathered** — `RazorpaySubscription` stores per-subscription `razorpay_plan_id`. Price changes only affect NEW subscriptions. Existing subs continue billing at their original rate.
- **Razorpay plans are immutable** — Once created via API, a plan's amount/period cannot be changed. The sync system creates a new plan for every pricing change.

---

## [0.19.0] — 2026-02-27

### Backend Backlog Sweep

#### Added — New Endpoints
- **`POST /api/v1/auth/logout-all/`** — Invalidate all JWT sessions at once (bulk blacklist outstanding tokens).
- **`POST /api/v1/analyses/<id>/cancel/`** — Cancel a stuck/processing analysis. Revokes Celery task, marks as failed, refunds credits.
- **`POST /api/v1/analyses/bulk-delete/`** — Soft-delete up to 50 analyses in a single request.
- **`GET /api/v1/analyses/<id>/export-json/`** — Download complete analysis data as a JSON file attachment.
- **`GET /api/v1/account/export/`** — GDPR-compliant data export: profile, analyses, resumes, wallet, consent logs, notifications.

#### Added — Plan Quota Enforcement
- **Monthly analysis quota** — `AnalyzeResumeView` now checks `plan.analyses_per_month` and returns 403 with `limit`/`used` when exceeded.
- **Max resumes stored** — Blocks new uploads when `plan.max_resumes_stored` is reached (403).
- **Per-plan resume size limit** — Validates file size against `plan.max_resume_size_mb` (400).
- **PDF export feature flag** — `plan.pdf_export = false` blocks PDF downloads (403). Free-tier (no plan) is allowed.
- **Share analysis feature flag** — `plan.share_analysis = false` blocks share link generation (403). Free-tier allowed.

#### Added — Dashboard Enhancements
- **`grade_distribution`** — Count of analyses per overall grade (A/B/C/D/F) in dashboard stats.
- **`top_industries`** — Top 5 industries analyzed, with count.
- **Per-ATS score trends** — `score_trend` now includes `generic_ats`, `workday_ats`, `greenhouse_ats` from the `scores` JSONField.
- **`ai_response_time_seconds`** — New field on `ResumeAnalysisDetailSerializer` showing LLM response duration.

#### Added — Notifications
- **Analysis complete email** — Sends `analysis-complete` template when processing finishes (respects `feature_updates_email` pref).
- **Weekly digest task** — Celery beat task every Monday 9 AM UTC. Summarises past week activity (respects `newsletters_email` pref).
- **`analysis-complete` and `weekly-digest` email templates** — Added to `seed_email_templates` management command.

#### Added — Other
- **Duplicate resume warning** — `AnalyzeResumeView` response includes `duplicate_resume_warning` if the same resume was previously analyzed.
- **`raw_id_fields`** on 5 admin models for FK performance.
- **`list_per_page = 50`** on `DiscoveredJobAdmin`.

#### Added — Test Coverage
- **54 new tests** across `accounts/test_new_endpoints.py` and `analyzer/tests/test_new_endpoints.py`.
  - Forgot/reset password flow, notification preferences, wallet, plans, logout-all.
  - Cancel, bulk-delete, export-json, GDPR export, dashboard stats (with enhanced fields).
  - Plan quota enforcement (monthly quota, file size, feature flags).

#### Changed
- **`runtime.txt`** updated from `python-3.12.1` to `python-3.12`.
- **FRONTEND_API_GUIDE.md** updated with all new endpoints, error codes, and field changes.

---

## [0.18.0] — 2026-02-27

### Scalability & Performance

#### Added
- **`tenacity` retry decorator for all LLM calls** — Exponential backoff (2s → 30s, 3 attempts) on `RateLimitError` (429), `APITimeoutError`, `APIConnectionError`, and 5xx status errors. Applied to resume analysis, resume generation, job matching, and profile extraction.
- **PDF page limit** — New `MAX_PDF_PAGES` setting (default 50). Oversized PDFs are rejected with a clear error before any processing begins.
- **Token estimation before LLM calls** — `estimate_tokens()` and `check_prompt_length()` utilities auto-truncate prompts exceeding the model's safe input limit (~100k tokens), preventing wasted API calls.
- **Dashboard stats caching** — `GET /api/v1/dashboard/stats/` responses are now cached per-user in Redis with a 5-minute TTL. Subsequent requests within the window skip all 5 aggregate queries.
- **Pagination on 3 more endpoints:**
  - `GET /api/v1/generated-resumes/` — Now returns paginated envelope (was flat array).
  - `GET /api/v1/job-alerts/` — Now returns paginated envelope (was flat array).
  - `GET /api/v1/job-alerts/<id>/matches/` — Switched from Django `Paginator` to DRF `PageNumberPagination` (consistent `{count, next, previous, results}` envelope).
- **Celery task retry backoff** — `run_analysis_task` now uses `retry_backoff=True` with `retry_backoff_max=120` for smarter retry spacing.
- **Migration race prevention** — `entrypoint.sh` now uses `flock -w 120` to serialize concurrent migrations across Railway replicas. Inline migrate removed from `Procfile` web command.
- **Celery memory leak prevention** — `--max-tasks-per-child=50` (configurable via `CELERY_MAX_TASKS_PER_CHILD` env var) restarts workers after 50 tasks to reclaim leaked memory.

#### Changed
- **OpenAI client is now LRU-cached** — All modules (`openrouter_provider`, `resume_generator`, `job_matcher`, `job_search_profile`, `embedding_service`) share a cached `OpenAI()` client keyed by `(api_key, base_url)` instead of creating a new instance per call. Enables HTTP connection pooling.
- **Token blacklisting uses `bulk_create`** — Account deletion (`DELETE /api/v1/auth/profile/`) and password change (`POST /api/v1/auth/change-password/`) now blacklist all outstanding tokens in a single `bulk_create(ignore_conflicts=True)` instead of looping `get_or_create`.
- **PDF report styles cached at module level** — `_build_styles()` result cached globally instead of recreating ~20 `ParagraphStyle` objects per report.
- **Job source factory instances cached** — `get_job_sources()` now returns cached provider instances instead of re-instantiating on every call.

#### Breaking Changes (Frontend)
- **`GET /api/v1/generated-resumes/`** — Response changed from flat array `[...]` to paginated envelope `{count, next, previous, results}`.
- **`GET /api/v1/job-alerts/`** — Response changed from flat array `[...]` to paginated envelope `{count, next, previous, results}`.
- **`GET /api/v1/job-alerts/<id>/matches/`** — Response shape changed from `{count, num_pages, page, results}` to standard DRF pagination `{count, next, previous, results}`.

---

## [0.16.3] — 2026-02-27

### Added
- **Google OAuth login** — Two new endpoints for Google Sign-In:
  - `POST /api/v1/auth/google/` — Verifies Google ID token. Existing users get JWT tokens immediately; new users receive a signed `temp_token` for registration completion.
  - `POST /api/v1/auth/google/complete/` — Completes registration for new Google users with username, password, and consent checkboxes.
- **Google profile data** — New Google users automatically get:
  - `first_name` / `last_name` from Google's `given_name` / `family_name`.
  - `avatar_url` from Google profile picture.
  - `google_sub` (Google account unique ID) stored on profile.
  - `auth_provider` set to `"google"` (vs `"email"` for regular registrations).
- **UserProfile fields:** `auth_provider`, `avatar_url`, `google_sub` (new model fields).
- **UserSerializer** now exposes `first_name`, `last_name`, `auth_provider`, `avatar_url` in all user-facing responses.
- **Stateless temp tokens** — HMAC-SHA256 signed, base64-encoded tokens (10-min TTL) for the two-step registration flow. No DB/cache storage required.
- **Case-insensitive email lookup** — Google login and registration race-condition guard use `email__iexact`.
- **`google-auth==2.38.0`** — New dependency for verifying Google ID tokens.
- **Settings:** `GOOGLE_OAUTH2_CLIENT_ID` (env var), `GOOGLE_OAUTH2_TEMP_TOKEN_TTL` (default 600s).
- **18 new tests** — `GoogleLoginViewTests` (7) + `GoogleCompleteViewTests` (11) covering token verification, profile data storage, consent logging, expired tokens, race conditions.
- **FRONTEND_API_GUIDE.md** — Full Google OAuth section with flow diagram, TypeScript types, integration example.
- **Migration:** `0011_add_google_profile_fields`.

---

## [0.16.2] — 2026-02-27

### Added
- **Registration consent checkboxes** — `POST /api/v1/auth/register/` now requires:
  - `agree_to_terms` (boolean, **mandatory**) — Terms of Service & Privacy Policy.
  - `agree_to_data_usage` (boolean, **mandatory**) — AI data processing & Data Usage Policy.
  - `marketing_opt_in` (boolean, optional, default `false`) — Marketing emails & newsletters.
- **`ConsentLog` model** — Immutable audit trail for consent actions. Stores `consent_type`, `agreed`, `version`, `ip_address`, `user_agent`, and `created_at`. Three entries created per registration, never updated or deleted (GDPR-ready).
- **`UserProfile` consent flags** — Quick-access fields: `agreed_to_terms`, `agreed_to_data_usage`, `marketing_opt_in`. Existing users grandfathered with `agreed_to_terms=True`, `agreed_to_data_usage=True`.
- **Newsletter sync** — `marketing_opt_in=true` during registration automatically sets `NotificationPreference.newsletters_email=true`.
- **`ConsentLogAdmin`** — Read-only Django admin for consent audit logs (no add/change/delete).
- **5 new registration tests** — Missing terms/data-usage validation, consent log creation, newsletter sync, response fields.
- **Total tests: 269** (up from 264), all passing.
- **Migration:** `0010_add_consent_log_and_profile_flags`.

### Changed
- **User response** — `agreed_to_terms`, `agreed_to_data_usage`, `marketing_opt_in` now included in all user-facing responses (register, login, GET/PUT /me/).
- **FRONTEND_API_GUIDE.md** — Section 2 updated with new request fields, field table, error examples, consent audit notes, and updated TypeScript `User` interface.

---

## [0.16.1] — 2026-02-27

### Fixed
- **Migration `0016` fails on deploy** — `AddField` for `discoveredjob.embedding` and `jobsearchprofile.embedding` crashed with `DuplicateColumn` because those columns were already added via raw SQL in migration `0014`. Wrapped in `SeparateDatabaseAndState` (state-only, no DB changes).
- **PDF renderer `Bullet` style collision** — `resume_pdf_renderer.py` `_build_styles()` tried to add a `'Bullet'` `ParagraphStyle` that already exists in ReportLab's `getSampleStyleSheet()`. Renamed to `'ResumeBullet'`.

### Added
- **Phase 10 test suite** — 81 new tests in `test_resume_generation.py` covering:
  - `build_rewrite_prompt()` — all analysis fields included, empty field fallbacks, boundary sanitisation (15 tests)
  - `validate_resume_output()` — schema validation, optional field defaults, all error cases (22 tests)
  - `GenerateResumeView` — 202 success, 402 insufficient credits, 400 for non-done analysis, 404 isolation, invalid template/format, credit deduction (14 tests)
  - `GeneratedResumeStatusView` — polling all statuses, file_url presence, 404 cases (8 tests)
  - `GeneratedResumeDownloadView` — 302 redirect, 404 cases (4 tests)
  - `GeneratedResumeListView` — list, isolation, ordering, auth (5 tests)
  - PDF/DOCX rendering integration — valid output bytes, minimal/full content, special characters, multi-page (10 tests)
- **Total tests: 264** (up from 183), all passing.

---

## [0.16.0] — 2026-02-27

### Phase 12: Firecrawl + pgvector Job Alerts Redesign

### Added
- **pgvector embeddings** — Resume and job embeddings computed via `text-embedding-3-small` (1536 dims). Stored on `JobSearchProfile.embedding` and `DiscoveredJob.embedding` with HNSW index for fast cosine similarity.
- **`embedding_service.py`** — `compute_embedding()`, `compute_resume_embedding()`, `compute_job_embedding()` via OpenRouter embeddings API.
- **`embedding_matcher.py`** — pgvector `CosineDistance` SQL matching. Falls back to LLM matcher if pgvector unavailable. Threshold: 60% similarity.
- **Firecrawl job crawler** — `firecrawl_source.py` scrapes LinkedIn + Indeed job board pages, extracts structured listings via single LLM call per page.
- **`crawl_jobs_daily_task`** — Daily crawl at 2 AM IST (20:30 UTC). Gathers queries from all active profiles, crawls, saves, embeds, chains matching.
- **`crawl_jobs_for_alert_task`** — Single-alert manual crawl (used by `POST /api/v1/job-alerts/<id>/run/`). Includes credit deduction, crawling, embedding, matching, and notification in one task.
- **`match_all_alerts_task`** — Runs after daily crawl. For each active alert: embedding match → JobMatch → SentAlert dedup → Notification → email digest.
- **`compute_resume_embedding_task`** — Triggered after profile extraction. Stores embedding on `JobSearchProfile`.
- **`SentAlert` model** — Dedup log preventing resending same job to same user per channel.
- **`Notification` model** — In-app notification store for bell/badge. Types: `job_match`, `analysis_done`, `resume_generated`, `system`.
- **Notification API endpoints:** `GET /api/v1/notifications/`, `GET /api/v1/notifications/unread-count/`, `POST /api/v1/notifications/mark-read/`.
- **Settings:** `EMBEDDING_MODEL`, `JOB_MATCH_THRESHOLD`, `MAX_CRAWL_JOBS_PER_RUN`, `JOB_CRAWL_SOURCES`.
- **Migrations:** `0014_pgvector_embeddings`, `0015_sentalert_notification`.

### Removed
- **`serpapi_source.py`** — SerpAPI job source deleted (replaced by Firecrawl).
- **`adzuna_source.py`** — Adzuna job source deleted (replaced by Firecrawl).
- **`discover_jobs_task`** — Old periodic task removed (replaced by `crawl_jobs_daily_task`).
- **`discover_jobs_for_alert_task`** — Old manual run task removed (replaced by `crawl_jobs_for_alert_task`).
- **SerpAPI/Adzuna fallbacks from `factory.py`** — Only Firecrawl source remains.
- **`SOURCE_SERPAPI` / `SOURCE_ADZUNA`** — Removed from `DiscoveredJob.SOURCE_CHOICES`.

### Changed
- **Manual run endpoint** — `POST /api/v1/job-alerts/<id>/run/` now uses `crawl_jobs_for_alert_task` (Firecrawl + embedding matching) instead of `discover_jobs_for_alert_task`.
- **Celery Beat schedule** — Replaced `discover-jobs` (6h interval) with `crawl-jobs-daily` (crontab 20:30 UTC).
- **Cost reduction** — ~$55-80/month (SerpAPI + Adzuna + LLM scoring) → ~$5-16/month (Firecrawl + embeddings).

---

## [0.13.1] — 2026-02-27

### Payment Linkage Audit — Security & Correctness Fixes

### Fixed
- **PlanSubscribeView security** — Blocked direct upgrade to paid plans without payment. Returns `402 Payment Required` directing to `/api/v1/auth/payments/subscribe/`. Only free-plan downgrades allowed.
- **WalletTopUpView security** — Deprecated free credit grants. Returns `402 Payment Required` directing to `/api/v1/auth/payments/topup/`.
- **Re-subscribe after cancellation** — Old cancelled/expired `RazorpaySubscription` records are now deleted before creating a new one (prevents `IntegrityError` from OneToOneField constraint).
- **`razorpay_payment_id` unique constraint** — Added `default=None` to prevent empty-string collisions when multiple pending payments exist.
- **Account deletion** — Now cancels active Razorpay subscription before deleting user (prevents continued billing).
- **Race conditions** — Added `select_for_update()` to idempotency checks in `_activate_subscription` and `_fulfill_topup`.
- **Webhook: `subscription.activated`** — Logs warning when `payment_id` missing from payload instead of silently skipping.
- **Webhook: status validation** — `_handle_subscription_status_change` now validates status against `STATUS_CHOICES` before saving.
- **Production guard** — `_get_razorpay_plan_id` raises `ValueError` in production when plan ID not configured (instead of using placeholder).
- **Webhook: `_fulfill_topup`** — Fetches real amount from Razorpay API when payment record not found (instead of `amount=0`).
- **Dead imports** — Removed unused `PaymentHistorySerializer` / `SubscriptionStatusSerializer` imports from `views_payments.py`.
- **`max_job_alerts`** — Added to `PlanSerializer.fields` and `PlanAdmin` fieldsets.
- **Migration** — `0007_fix_razorpay_payment_id_default`.

### Changed
- `POST /api/v1/auth/wallet/topup/` — Now returns `402` (deprecated; use `/api/v1/auth/payments/topup/`).
- `POST /api/v1/auth/plans/subscribe/` — Now returns `402` for paid plans (use `/api/v1/auth/payments/subscribe/`).

---

## [0.13.0] — 2026-02-26

### Phase 13: Razorpay Payment Gateway Integration

### Added
- **Razorpay SDK** (`razorpay==2.0.0`) — Official Python SDK for Razorpay API.
- **`RazorpayPayment` model** — Tracks every payment attempt (subscription & top-up). Stores `razorpay_order_id`, `razorpay_payment_id` (unique), `razorpay_signature`, `razorpay_subscription_id`, amount in paise, status lifecycle (created → captured/failed/refunded), `credits_granted` flag for idempotency, `webhook_verified` flag.
- **`RazorpaySubscription` model** — OneToOne per user. Tracks active Razorpay subscription with `razorpay_subscription_id`, `razorpay_plan_id`, status (created/authenticated/active/pending/halted/cancelled/completed/expired), `current_start`/`current_end` billing cycle, `short_url`.
- **`accounts/razorpay_service.py`** — Complete payment service layer:
  - `create_subscription(user, plan_slug)` — Creates Razorpay subscription via Subscriptions API for Pro plan auto-renewal. Validates no duplicate active subscription.
  - `verify_subscription_payment()` — HMAC-SHA256 signature verification + plan upgrade + bonus credit provisioning.
  - `cancel_subscription(user)` — Calls Razorpay cancel API (at cycle end) + schedules downgrade to Free.
  - `get_subscription_status(user)` — Returns current subscription state.
  - `create_topup_order(user, quantity)` — Creates Razorpay order via Orders API for one-time credit top-up packs.
  - `verify_topup_payment()` — Signature verification + wallet credit addition.
  - `verify_webhook_signature()` — HMAC-SHA256 webhook body verification.
  - `handle_webhook_event()` — Dispatches 7 Razorpay event types: `payment.captured`, `payment.failed`, `subscription.activated`, `subscription.charged`, `subscription.cancelled`, `subscription.completed`, `subscription.halted`.
  - Full **idempotency** — duplicate payment_id checks prevent double-provisioning of credits/plan upgrades.
- **8 REST API endpoints** (under `/api/v1/auth/payments/`):
  - `POST /payments/subscribe/` — Create subscription (returns checkout params).
  - `POST /payments/subscribe/verify/` — Verify subscription payment.
  - `POST /payments/subscribe/cancel/` — Cancel subscription (at cycle end).
  - `GET  /payments/subscribe/status/` — Current subscription status.
  - `POST /payments/topup/` — Create top-up order (returns checkout params).
  - `POST /payments/topup/verify/` — Verify top-up payment.
  - `POST /payments/webhook/` — Razorpay webhook (no JWT auth, signature-verified).
  - `GET  /payments/history/` — Paginated payment history.
- **6 serializers** — `CreateSubscriptionSerializer`, `VerifySubscriptionSerializer`, `CreateTopUpOrderSerializer`, `VerifyTopUpSerializer`, `PaymentHistorySerializer`, `SubscriptionStatusSerializer`.
- **2 admin classes** — `RazorpayPaymentAdmin` (read-only, no add/delete) and `RazorpaySubscriptionAdmin` with full filtering/search.
- **Razorpay settings** — `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_CURRENCY` (placeholder defaults for dev).
- **36 tests** — Comprehensive test suite covering:
  - Model creation & unique constraints
  - Subscription flow (create, verify, cancel, status, duplicate rejection)
  - Top-up flow (create order, verify, free plan rejection, default quantity)
  - Webhook handling (signature verification, payment.captured, payment.failed, subscription.cancelled)
  - Idempotency (double-verify for both subscriptions and top-ups)
  - Payment history (filtering, isolation, limit param)
  - Authentication enforcement on all endpoints
- **FRONTEND_API_GUIDE.md § 22** — Full integration guide with TypeScript types, checkout code samples, and step-by-step recipes.

---

## [0.12.0] — 2026-02-26

### Phase 12: Smart Job Alerts (Job Discovery & Matching Pipeline)

### Added
- **JobSearchProfile model** — OneToOne with `Resume`. LLM-extracted profile containing `titles`, `skills`, `seniority`, `industries`, `locations`, `experience_years`, and `raw_extraction`. Populated asynchronously when a job alert is created.
- **JobAlert model** — UUID PK, FK to User + Resume. Supports `daily` / `weekly` frequency. Stores JSON `preferences` (excluded_companies, location_filter, date_filter). Auto-computes `next_run_at` based on frequency. Soft-delete via `is_active = False`.
- **DiscoveredJob model** — Canonical job listing from external sources. Unique on `(source, external_id)`. Stores title, company, location, salary_range, description_snippet, posted_at, and raw_data JSON.
- **JobMatch model** — Links DiscoveredJob to JobAlert with `relevance_score` (0–100), `match_reason`, and `user_feedback` (pending/relevant/irrelevant/applied/dismissed). Unique on `(job_alert, discovered_job)`.
- **JobAlertRun model** — Audit record per alert execution. Tracks `jobs_discovered`, `jobs_matched`, `notification_sent`, `credits_used`, `error_message`, and `duration_seconds`.
- **`max_job_alerts` field on Plan** — Quota for job alerts per plan (Free=0, Pro=3).
- **Job source provider pattern** — Abstract `BaseJobSource` with `RawJobListing` dataclass; `SerpAPIJobSource` (Google Jobs via SerpAPI) and `AdzunaJobSource` (Adzuna free API) implementations with graceful degradation when API keys are missing.
- **`job_search_profile.py` service** — LLM-powered extraction of job search criteria from resume text. Validates and normalizes seniority, caps list lengths, handles fallbacks.
- **`job_matcher.py` service** — Batch LLM scoring (≤15 jobs/batch) of discovered jobs against resume profile. Returns relevance scores + match reasons. Threshold of 60 to filter weak matches.
- **4 Celery tasks:**
  - `extract_job_search_profile_task(resume_id)` — Async profile extraction with retry (max 2).
  - `discover_jobs_task()` — Periodic (every 6 hours). Finds due alerts, fetches from all configured sources, deduplicates, respects excluded_companies, chains matcher.
  - `match_jobs_task(job_alert_id, discovered_job_ids)` — Deducts 1 credit, runs LLM scoring, creates JobMatch records, creates JobAlertRun audit, refunds on failure.
  - `send_job_alert_notification_task(job_alert_id, run_id)` — Sends email digest with top 10 matches via `job-alert-digest` email template.
- **5 REST API endpoints:**
  - `GET/POST /api/v1/job-alerts/` — List/create alerts (plan-gated, quota-checked).
  - `GET/PUT/DELETE /api/v1/job-alerts/<uuid:id>/` — Detail/update/deactivate.
  - `GET /api/v1/job-alerts/<uuid:id>/matches/` — Paginated matches with `?feedback=` filter.
  - `POST /api/v1/job-alerts/<uuid:id>/matches/<uuid:match_id>/feedback/` — Submit user feedback.
  - `POST /api/v1/job-alerts/<uuid:id>/run/` — Trigger manual discovery run (202 Accepted).
- **8 serializers** — `JobSearchProfileSerializer`, `DiscoveredJobSerializer`, `JobMatchSerializer`, `JobMatchFeedbackSerializer`, `JobAlertRunSerializer`, `JobAlertSerializer` (nested), `JobAlertCreateSerializer`, `JobAlertUpdateSerializer`.
- **5 admin classes** — Full Django admin for all new models with filters, search, and readonly fields.
- **Seed data:**
  - `job_alert_run` credit cost (1 credit) in `seed_credit_costs`.
  - `max_job_alerts` in `seed_plans` (Free=0, Pro=3).
  - `job-alert-digest` email template in `seed_email_templates`.
- **Celery Beat schedule** — `discover-jobs` task runs every 6 hours.
- **25 tests** — Comprehensive test suite covering CRUD, plan gating, quota, match listing/filtering, feedback, manual run, LLM extraction, job source providers (SerpAPI + Adzuna), and matcher service.
- **FRONTEND_API_GUIDE.md Section 21** — Full documentation with endpoints, request/response schemas, TypeScript types, and integration recipes.

---

## [0.11.0] — 2026-02-26

### Phase 11: AI Resume Generation

### Added
- **GeneratedResume model** — UUID PK, FK to `ResumeAnalysis`, stores template/format/status/resume_content JSON, file (R2), LLM response reference, `credits_deducted` flag for idempotent refunds. Indexed on `(analysis, -created_at)` and `(user, -created_at)`.
- **`resume_generator.py` service** — LLM-powered resume rewrite using analysis findings as improvement spec. Extracts missing keywords with recommended placements, sentence-level rewrites for weak sections (<70 score), quick wins, and formatting guidance. Strict "no fabrication" prompt ensures only real candidate data is used.
- **`resume_pdf_renderer.py`** — ReportLab-based ATS-optimized PDF renderer. Single-column A4 layout, Helvetica fonts, clean section dividers, KeepTogether for page-break control. Renders contact, summary, experience, education, skills (grouped), certifications, and projects.
- **`resume_docx_renderer.py`** — python-docx based ATS-optimized DOCX renderer. Calibri font, narrow margins, parallel structure to PDF. Compatible with MS Word, Google Docs, and ATS parsers.
- **`generate_improved_resume_task` Celery task** — Async pipeline: LLM rewrite → render PDF/DOCX → upload to R2 → mark done. On failure: marks failed + auto-refunds credits via `_refund_generation_credits()`.
- **Resume generation endpoints:**
  - `POST /api/v1/analyses/<id>/generate-resume/` — Trigger generation (1 credit). Validates analysis is done. Returns 202 with `{id, status, template, format, credits_used, balance}`. Returns 402 on insufficient credits.
  - `GET /api/v1/analyses/<id>/generated-resume/` — Poll latest generation status.
  - `GET /api/v1/analyses/<id>/generated-resume/download/` — 302 redirect to signed R2 URL.
  - `GET /api/v1/generated-resumes/` — List all user's generated resumes (paginated).
- **`GeneratedResumeSerializer` / `GeneratedResumeCreateSerializer`** — Read-only serializer with `file_url` computed field; create serializer validates template slug and format choice.
- **`GeneratedResumeAdmin`** — Django admin with list display, filters, search, and read-only computed fields.
- **`resume_generation` credit cost** — Seeded at 1 credit via `seed_credit_costs`. Added to `_DEFAULT_COSTS` fallback.
- **`python-docx==1.1.2`** — New dependency for DOCX rendering.

---

## [0.10.0] — 2026-02-26

### Phase 10: Plans & Wallet (Credits System)

### Added
- **Wallet model** — Per-user credit wallet (`OneToOneField(User)`) with a `PositiveIntegerField` balance. Created automatically on user registration via signal.
- **WalletTransaction model** — Append-only audit log for all credit movements. Types: `plan_credit`, `topup`, `analysis_debit`, `refund`, `admin_adjustment`, `upgrade_bonus`. Stores `amount`, `balance_after`, `description`, and optional `reference_id`.
- **CreditCost model** — Admin-manageable per-action credit costs (e.g., `resume_analysis = 1`). Seeded via `python manage.py seed_credit_costs`.
- **Plan credit fields** — `credits_per_month`, `max_credits_balance`, `topup_credits_per_pack`, `topup_price`, `job_notifications` added to `Plan` model.
- **UserProfile billing fields** — `plan_valid_until` (DateTimeField) and `pending_plan` (FK to Plan) for billing cycle tracking and scheduled downgrades.
- **`credits_deducted` field on ResumeAnalysis** — Boolean flag for idempotent deduction/refund. Prevents double-debit on Celery redelivery and double-refund on failure.
- **Credit deduction on analysis submit** — `POST /api/v1/analyze/` and `POST /api/v1/analyses/<id>/retry/` now deduct 1 credit upfront. Returns **HTTP 402** with `{detail, balance, cost}` on insufficient credits. On task failure, credits are automatically refunded.
- **`accounts/services.py`** — New service layer with all credit/wallet business logic:
  - `deduct_credits()` / `refund_credits()` — Atomic with `select_for_update()` for race safety
  - `topup_credits()` — Multi-pack top-up (Pro only, blocked during pending downgrade)
  - `subscribe_plan()` — Handles upgrades (immediate bonus credits) and downgrades (scheduled at billing cycle end)
  - `check_balance()` / `can_use_feature()` — Query helpers
  - `grant_monthly_credits_for_user()` — Respects `max_credits_balance` cap
  - `process_expired_plans()` — Celery Beat hook for scheduled downgrades
  - `InsufficientCreditsError` — Custom exception with balance/cost info
- **Wallet endpoints:**
  - `GET /api/v1/auth/wallet/` — Balance, plan credits info, top-up availability
  - `GET /api/v1/auth/wallet/transactions/` — Paginated transaction history
  - `POST /api/v1/auth/wallet/topup/` — Buy credit packs (`{quantity: N}`). Pro users only. Multi-pack supported.
- **Plan endpoints:**
  - `GET /api/v1/auth/plans/` — List active plans (public, no auth required)
  - `POST /api/v1/auth/plans/subscribe/` — Switch plan. Upgrades apply immediately with bonus credits. Downgrades scheduled until billing cycle ends.
- **`seed_credit_costs` management command** — Seeds `resume_analysis = 1 credit`. Idempotent.
- **Updated `seed_plans` command** — Now includes `credits_per_month`, `max_credits_balance`, `topup_credits_per_pack`, `topup_price`, `job_notifications` for both Free and Pro plans.
- **Admin panels** — `WalletAdmin` (read-only), `WalletTransactionAdmin` (fully read-only, no add/change/delete), `CreditCostAdmin` for managing action costs.
- **Stale analysis refund** — `cleanup_stale_analyses` task now refunds credits for any stale analysis that had `credits_deducted=True`.

### Changed
- **Analysis submit responses** now include `credits_used` and `balance` fields.
- **User serializer** now includes `wallet` (balance + updated_at), `plan_valid_until`, and `pending_plan` in all user-facing responses (register, login, GET/PUT /me/).
- **Plan serializer** now includes all new credit/wallet fields.
- **Test fixtures** — Three test classes updated with `_ensure_free_plan()` and `_give_credits()` helpers to work with the new credit requirement.

---

## [0.9.1] — 2026-02-25

### Bug Fixes & Security Hardening (Audit Sweep)

### Changed
- **PDF export: WeasyPrint → ReportLab** — Replaced WeasyPrint (C-library dependency) with ReportLab 4.4.0 (pure Python). Eliminates native `libpango`, `libcairo` linking failures on Railway Nixpacks. PDF report visuals fully rebuilt with Platypus flowables, score bars, keyword pills, and section feedback.
- **Share URLs now absolute** — `share_url` in API responses changed from relative (`/api/v1/shared/<uuid>/`) to absolute (`https://host/api/v1/shared/<uuid>/`) using `request.build_absolute_uri()`. Affects `POST /api/v1/analyses/<id>/share/`, list serializer, and detail serializer.
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
- **`PUT /api/v1/auth/me/`** — Update username and/or email (partial update supported). Validates uniqueness of both fields.
- **`POST /api/v1/auth/change-password/`** — Change password with `current_password` + `new_password`. Validates current password and runs Django password validators on the new one.
- **`DELETE /api/v1/auth/me/`** — Permanently delete account. Blacklists all tokens, soft-deletes analyses (clears heavy data), cascade-deletes user + resumes + related objects.
- **`file_url` field on `ResumeSerializer`** — `GET /api/v1/resumes/` now returns the download URL for each resume, so the frontend ResumesPage can link directly.
- **`Job` model** — Tracked job postings linked to user and optionally a resume. Fields: `id` (UUID), `user`, `resume` (FK, nullable), `job_url`, `title`, `company`, `description`, `relevance` (pending/relevant/irrelevant), `source`, `created_at`, `updated_at`. Migration `0008_add_job_model`.
- **Job endpoints:**
  - `GET /api/v1/jobs/` — List user's tracked jobs, filterable by `?relevance=relevant|irrelevant|pending`.
  - `POST /api/v1/jobs/` — Create a tracked job (optionally linking a `resume_id`).
  - `GET /api/v1/jobs/<uuid>/` — Retrieve a single job.
  - `DELETE /api/v1/jobs/<uuid>/` — Delete a tracked job.
  - `POST /api/v1/jobs/<uuid>/relevant/` — Mark job as relevant.
  - `POST /api/v1/jobs/<uuid>/irrelevant/` — Mark job as irrelevant.
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
- **`resume_id` support in `POST /api/v1/analyze/`** — submit an existing Resume UUID instead of re-uploading the PDF. Send `resume_id` (UUID) as JSON or form field; the analysis reuses the stored file. Exactly one of `resume_file` or `resume_id` is required.
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
  - `POST /api/v1/analyses/<id>/share/` — generate a UUID share token (idempotent; returns existing token if already shared).
  - `DELETE /api/v1/analyses/<id>/share/` — revoke the share token (link stops working immediately).
  - `GET /api/v1/shared/<token>/` — public read-only view returning ATS score, breakdown, keyword gaps, section suggestions, rewritten bullets, and assessment. Excludes all sensitive data (resume file, user info, celery task ID, raw JD text).
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
- **`GET /api/v1/resumes/`** — paginated list of user's deduplicated resumes with `active_analysis_count`.
- **`DELETE /api/v1/resumes/<uuid:id>/`** — delete resume from R2 storage (blocked if active analyses reference it, returns 409).
- **`GET /api/v1/dashboard/stats/`** — user-level analytics: total/active/deleted counts, average ATS score, score trend (last 10), top 5 roles, analyses per month (last 6 months). Uses `all_objects` to include soft-deleted rows.
- **`post_delete` signal** on `Resume` — automatically deletes file from R2 when Resume row is hard-deleted.
- **Admin enhancements** — `Resume`, `ScrapeResult`, `LLMResponse` registered in admin. `ResumeAnalysis` admin shows soft-deleted rows with `is_deleted` column.
- **DB indexes** — `(user, deleted_at)` and `(user, status, -created_at)` on `ResumeAnalysis`; `(user, -uploaded_at)` on `Resume`; unique constraint `(user, file_hash)` on `Resume`.
- **Data migration** `0006_populate_resume_from_existing` — creates `Resume` rows from existing `resume_file` values, computes SHA-256 hashes, deduplicates, links analyses.
- **27 new tests** in `test_phase7.py` covering: Resume model, dedup, soft-delete, orphan cleanup, API endpoints, dashboard stats, user isolation.

### Changed
- **`DELETE /api/v1/analyses/<id>/delete/`** — now performs soft-delete instead of hard-delete (⚠️ breaking behavior change, same 204 response).
- **`POST /api/v1/analyze/`** — now creates a `Resume` row (deduplicated) and links it to the analysis via `resume` FK.
- **`FRONTEND_API_GUIDE.md`** — updated with 3 new endpoints, soft-delete documentation, new sections 9-10, updated ToC and quick reference table.

---

## [0.6.0] — 2026-02-22

### Phase 6: Performance & Security Optimizations

**Commit:** `563e34f` — 15 files changed, 1,002 insertions, 134 deletions

### Added
- **Pagination** on `GET /api/v1/analyses/` — `PageNumberPagination`, PAGE_SIZE=20. Response is now a `{ count, next, previous, results }` envelope (⚠️ breaking change).
- **Idempotency guard** on `POST /api/v1/analyze/` — Redis lock prevents duplicate submissions within 30 seconds. Returns `409 Conflict` on double-submit.
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
- `openrouter_provider.py` — OpenRouter AI provider using OpenAI Python SDK pointed at `https://openrouter.ai/api/v1/v1`.
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
