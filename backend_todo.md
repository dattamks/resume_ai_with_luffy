# Backend TODO — i-Luffy

> Backend-only task tracker. Frontend tasks tracked separately.

### Priority Legend

| Tag | Meaning | Count |
|-----|---------|-------|
| 🔴 IMMEDIATE | Next sprint — implement now | 0 (all done) |
| 🟡 P2 | Important — implement soon | 0 (all done) |
| 🔵 P3 | Important — plan for later | 1 |
| ⚪ DEFERRED | Backlog — revisit in future | 10 |

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
- [x] Verify rate limiting works with Redis-backed cache *(v0.8.1 — TESTING flag + LocMemCache)*
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
- [x] Unit tests for prompt builder (verify all analysis fields included)
- [x] Unit tests for JSON schema validation
- [x] API endpoint tests (202, 402, 400 for non-done analysis, polling)
- [x] Integration test for PDF render from sample structured JSON

### Documentation

- [x] FRONTEND_API_GUIDE.md — Section 20 with full endpoints, TypeScript types, integration recipe
- [x] CHANGELOG.md — v0.11.0 entry

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
- [ ] **⚪ DEFERRED** — Frontend shows tabs: "My Jobs" vs "Discovered Jobs" *(frontend task)*

### Tests

- [x] Unit tests for search profile extraction prompt
- [x] Unit tests for job source providers (mock API responses)
- [x] Unit tests for LLM batch matching
- [x] API endpoint tests (CRUD, plan gating, credit deduction)
- [x] Integration test for full pipeline (discover → match → notify)

### Dependencies

- [x] Add `google-search-results` (SerpAPI) or use raw `requests` *(used raw requests — no extra dependency)*
- [x] ~~Env vars: `SERPAPI_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`~~ *(removed in Phase 12 — Firecrawl replaced all)*

### Documentation

- [x] FRONTEND_API_GUIDE.md — new section with endpoints, example flows, TypeScript types *(shipped v0.12.0)*
- [x] CHANGELOG.md — v0.12.0 entry *(shipped)*
- [x] Seed `job_alert_digest` email template *(active in DB)*

---

## Phase 12 — Firecrawl + pgvector Job Alerts Redesign 🔥

> **Goal:** Replace SerpAPI/Adzuna with Firecrawl-based daily crawling. Replace per-match LLM scoring with pgvector embedding similarity. Add dedup log + in-app notifications. Zero new API keys — reuse existing `FIRECRAWL_API_KEY`.
>
> **Status:** ✅ Complete
>
> **Why:** Current Phase 11 depends on SerpAPI ($50/mo) + Adzuna API keys. Each match run burns an LLM call per 15-job batch. New approach: crawl once daily via Firecrawl (~$5-15/mo), compute embeddings once (~$0.10/day), match all users via fast SQL cosine similarity.

### Phase A — pgvector Foundation

- [x] **Install `pgvector`** — added `pgvector==0.4.2`, `numpy==2.4.2` to `requirements.txt`
- [x] **Enable pgvector extension** — migration `0014_pgvector_embeddings.py`: `CREATE EXTENSION IF NOT EXISTS vector;`
- [x] **Add `JobSearchProfile.embedding`** — `VectorField(dimensions=1536, null=True)` (conditional on PostgreSQL)
- [x] **Add `DiscoveredJob.embedding`** — `VectorField(dimensions=1536, null=True)` (conditional on PostgreSQL)
- [x] **Add HNSW index** on `DiscoveredJob.embedding` — `discoveredjob_embedding_hnsw_idx`
- [x] **Add `DiscoveredJob.source` choice** — `firecrawl` added to `SOURCE_CHOICES`
- [x] **Embedding service** — `analyzer/services/embedding_service.py`:
  - `compute_embedding(text) → list[float]` via OpenRouter/OpenAI embeddings API (`text-embedding-3-small`, 1536 dims)
  - `compute_resume_embedding(resume) → list[float]` — extracts text, truncates 8K tokens
  - `compute_job_embedding(job) → list[float]` — `title + company + description_snippet`
- [x] **`compute_resume_embedding_task(resume_id)`** — Celery task, triggered after resume upload + profile extraction
- [x] **Settings** — `EMBEDDING_MODEL`, `JOB_MATCH_THRESHOLD = 0.60`, `MAX_CRAWL_JOBS_PER_RUN = 200`

### Phase B — Firecrawl Job Crawler

- [x] **`analyzer/services/job_sources/firecrawl_source.py`** — new source replacing SerpAPI + Adzuna:
  - Configurable job board URLs in `settings.JOB_CRAWL_SOURCES` (LinkedIn, Indeed)
  - Uses `FirecrawlApp.scrape()` to scrape search result pages → markdown
  - Single LLM call per page to extract structured listings (title, company, location, url, snippet)
  - Returns `RawJobListing` objects (existing dataclass in `base.py`)
- [x] **Delete `serpapi_source.py`** — removed in Phase F
- [x] **Delete `adzuna_source.py`** — removed in Phase F
- [x] **Rewrite `factory.py`** — Firecrawl primary, SerpAPI/Adzuna legacy fallback only if Firecrawl not configured
- [x] **Settings** — `JOB_CRAWL_SOURCES` list of `{name, url_template}` dicts

### Phase C — Global Daily Crawl Task

- [x] **New task: `crawl_jobs_daily_task`** — replaces `discover_jobs_task`:
  - Runs once daily at 2 AM IST (20:30 UTC) via Celery Beat
  - Gathers all unique search queries from all active `JobSearchProfile`s (deduplicated titles)
  - Calls Firecrawl source for each query+location combo
  - Deduplicates via `(source, external_id)` unique constraint (existing)
  - Computes embedding for each new `DiscoveredJob` immediately
  - Chains `match_all_alerts_task` when done
  - Caps at `MAX_CRAWL_JOBS_PER_RUN` to control costs
- [x] **Update Celery Beat schedule** — replaced `discover-jobs` (6h) with `crawl-jobs-daily` (crontab 20:30 UTC)
- [x] **Remove old `discover_jobs_task`** and `discover_jobs_for_alert_task` — removed in Phase F

### Phase D — Embedding-Based Matching

- [x] **New `embedding_matcher.py`** — pgvector cosine similarity (keeps `job_matcher.py` as fallback):
  - `match_jobs_for_alert(alert, since_dt) → list[dict]`
  - Django ORM via `CosineDistance` from `pgvector.django`
  - Threshold from `settings.JOB_MATCH_THRESHOLD` (default 0.60)
  - `score = int(similarity * 100)` for compatibility with existing `JobMatch.relevance_score`
  - Falls back to LLM matching if pgvector/embeddings not available
- [x] **New task: `match_all_alerts_task`** — runs after daily crawl:
  - For each active `JobAlert` with a resume that has an embedding
  - Find new `DiscoveredJob` records since `alert.last_run_at`
  - Run embedding similarity query (fast SQL, no LLM cost)
  - Create `JobMatch` + `SentAlert` + `Notification` records
  - Chain email notification task if matches found
- [x] **Update manual run endpoint** — `POST /api/job-alerts/<id>/run/` uses `crawl_jobs_for_alert_task` (Phase F)

### Phase E — Dedup Log & In-App Notifications

- [x] **`SentAlert` model** — dedup log, prevents resending same job to same user:
  - FK to `User` + `DiscoveredJob`, `sent_at`, `channel` (email/in_app)
  - Unique constraint: `(user, discovered_job, channel)`
  - Migration: `0015_sentalert_notification.py`
- [x] **`Notification` model** — in-app notification store:
  - FK to `User`, `title`, `body`, `link`, `is_read`, `notification_type` (job_match, analysis_done, resume_generated, system), `metadata` (JSONField), `created_at`
- [x] **Notification API endpoints:**
  - `GET /api/notifications/` — paginated list (newest first)
  - `POST /api/notifications/mark-read/` — mark one or all as read
  - `GET /api/notifications/unread-count/` — for badge icon
- [x] **Notification serializers** — `NotificationSerializer`, `NotificationMarkReadSerializer`
- [x] **Admin** — `SentAlertAdmin`, `NotificationAdmin`

### Phase F — Cleanup & Documentation

- [x] **Remove `serpapi_source.py`** — Deleted
- [x] **Remove `adzuna_source.py`** — Deleted
- [x] **Remove old `discover_jobs_task` / `discover_jobs_for_alert_task`** — Deleted from tasks.py
- [x] **Remove SerpAPI/Adzuna fallbacks from `factory.py`** — Only Firecrawl remains
- [x] **Remove `SOURCE_SERPAPI` / `SOURCE_ADZUNA` from models** — Only `SOURCE_FIRECRAWL` in choices
- [x] **Update manual run endpoint** — Uses new `crawl_jobs_for_alert_task`
- [x] **Update tests** — Replaced SerpAPI/Adzuna tests with Firecrawl test, updated all discover_ references
- [x] **Seed `job-alert-digest` email template** — Already exists and active in DB
- [x] **FRONTEND_API_GUIDE.md** — Notifications section 23 + v0.16.0 changelog
- [x] **CHANGELOG.md** — v0.16.0 entry
- [x] **`backend_todo.md`** — All Phase 12 items checked off

### Architecture

```
Daily at 2 AM IST:
  ┌──────────────────────────────────────────────────┐
  │           crawl_jobs_daily_task                   │
  │  1. Collect unique queries from all profiles      │
  │  2. Firecrawl → scrape job board pages            │
  │  3. LLM → extract structured listings (1 per page)│
  │  4. Save DiscoveredJob + compute embedding        │
  └────────────────┬─────────────────────────────────┘
                   │
                   ▼
  ┌──────────────────────────────────────────────────┐
  │           match_all_alerts_task                   │
  │  For each active alert:                           │
  │  1. pgvector cosine similarity (fast SQL)         │
  │  2. Create JobMatch (similarity ≥ 0.60)           │
  │  3. Check SentAlert for dedup                     │
  │  4. Create Notification (in-app)                  │
  │  5. Send email digest if enabled                  │
  └──────────────────────────────────────────────────┘

On resume upload:
  Resume → extract_text → compute_embedding → store on JobSearchProfile
```

### Cost Comparison

| Before (SerpAPI + Adzuna + LLM scoring) | After (Firecrawl + embeddings) |
|---|---|
| SerpAPI: ~$50/month | Firecrawl: ~$5-15/month |
| LLM scoring: ~$2-5/day per-match | Embeddings: ~$0.10/day |
| **~$55-80/month** | **~$5-16/month** |

### Dependencies

- [x] `pgvector==0.4.2` + `numpy==2.4.2` in `requirements.txt`
- [x] PostgreSQL `vector` extension enabled (v0.8.2 on Railway PostgreSQL 18)

### Execution Order

| # | Sub-phase | Effort | Depends On |
|---|---|---|---|
| A | pgvector + embeddings | 1 day | — |
| B | Firecrawl job crawler | 1-2 days | A |
| C | Daily crawl task | 1 day | B |
| D | Embedding matching | 1 day | A, C |
| E | SentAlert + Notifications | 0.5 day | D |
| F | Cleanup + docs | 0.5 day | All |
| | **Total** | **~5-6 days** | |

---

## Backlog — Security Fixes

> Items from the Feb 27, 2026 deep audit. Ordered by priority (P0 = critical, P3 = low).

### P0 — Critical Security

- [x] **Prompt injection in LLM calls** — Raw resume text and JD are interpolated into prompts via `.format()` with zero sanitization in `ai_providers/base.py` L203-207, `resume_generator.py` L201-214, `job_search_profile.py`. Attacker can craft resume text to manipulate grades. **Fix:** Delimit user content with random nonce boundaries; move user content to a separate message role; strip/escape known injection patterns.
- [x] **Add throttling to ALL payment endpoints** — None of the 8 views in `views_payments.py` have `throttle_classes`. Allows Razorpay API abuse via proxy. **Fix:** Add `UserRateThrottle` (or custom payment throttle) to `CreateSubscriptionView`, `VerifySubscriptionView`, `CancelSubscriptionView`, `SubscriptionStatusView`, `CreateTopUpOrderView`, `VerifyTopUpView`, `PaymentHistoryView`.
- [x] **Account deletion requires no password** — `MeView.DELETE` only needs a JWT. Stolen token → permanent data + account loss. **Fix:** Require `password` field in DELETE body, verify with `check_password()`.
- [x] **Retry endpoint has no idempotency guard** — `RetryAnalysisView` lacks `cache.add()` lock present in `AnalyzeResumeView`. Rapid-fire retries → double credit deduction. **Fix:** Added `select_for_update()` + `transaction.atomic()` to prevent concurrent retry race conditions.
- [x] **Broken import in `job_search_profile.py` L186** — `from .pdf_extractor import extract_text_from_pdf` doesn't exist (`PDFExtractor` is a class). Crashes at runtime on the fallback path. **Fix:** Changed to `from .pdf_extractor import PDFExtractor` and instantiate properly.

### P1 — High Security

- [x] **XSS in PDF report** — `pdf_report.py` passes user data (`analysis.summary`, keywords, sentence suggestions) directly to ReportLab `Paragraph()` without XML escaping. `resume_pdf_renderer.py` correctly uses `_safe()` but the report generator doesn't. **Fix:** Added `_safe()` XML escaping to all user-controlled data in `pdf_report.py`.
- [x] **Server-side template injection in email** — `email_utils.py` L82-83 uses `Template(template.html_body).render()` with DB-stored templates. If admin templates contain `{% load %}` or `{% include %}`, arbitrary template tags execute. **Fix:** Created sandboxed `Engine(builtins=[], libraries={})` — only variable substitution allowed.
- [x] **PII in log output** — Resume text fragments (`raw[:500]`) logged on JSON parse failures in `openrouter_provider.py` L65/L70, `job_matcher.py`, `resume_generator.py` L349. Contains names, contacts, addresses. GDPR violation. **Fix:** Replaced with `(raw length=%d)` — no user content in logs.
- [x] **Password change doesn't invalidate sessions** — `ChangePasswordView` leaves all existing JWTs valid. Compromised session persists. **Fix:** Added blacklisting of all `OutstandingToken` for the user after password change.
- [x] **`deduct_credits` already uses `@transaction.atomic`** — Verified: `deduct_credits()` at L75 is decorated with `@transaction.atomic` and uses `select_for_update()`. No change needed.
- [x] **Razorpay webhook double-grant race** — `_handle_subscription_charged` checks idempotency without `select_for_update()` at L741-743. Two concurrent webhook deliveries can pass `.exists()` simultaneously. **Fix:** Moved idempotency check inside `transaction.atomic()` with `select_for_update()`.
- [x] **Webhook has no replay protection** — Signature verified but no duplicate event ID check. Retries can cause double-processing. **Fix:** Added `WebhookEvent` model with unique `event_id`; webhook view checks `get_or_create` before dispatching to handler.
- [x] **Unhandled `Wallet.DoesNotExist` in `deduct_credits()`** — Unlike `refund_credits`, `deduct_credits` doesn't catch missing wallet. **Fix:** Changed to `get_or_create()` to auto-create wallet if missing.

### P2 — Medium Security

- [x] **SSRF bypass via DNS rebinding** — `jd_fetcher.py` validates URLs against private IPs at validation time, but Firecrawl uses its own DNS resolution later. **Fix:** Documented as accepted risk (Firecrawl is a hosted service). Existing SSRF protection already comprehensive.
- [x] **Health check leaks DB error details** — `views_health.py` L26 returns `str(exc)` with raw error messages (hostnames, ports) to unauthenticated callers. **Fix:** Returns generic `"Database connection failed."`, logs full error server-side.
- [x] **Email enumeration via forgot-password** — Already returns same 200 response regardless of email existence. No change needed.
- [ ] **⚪ DEFERRED — Webhook IP allowlisting missing** — Only HMAC verification. If secret leaks, any IP can send fake events. **Fix:** Add middleware/decorator to check against Razorpay's published IP ranges. *(deferred — infra/reverse-proxy task)*

### P3 — Low Security

- [x] **Razorpay secrets have plaintext defaults** — `settings.py` L300-302: `'rzp_test_placeholder'`. **Fix:** Added `warnings.warn()` in production when placeholder credentials detected.
- [x] **`CORS_ALLOW_CREDENTIALS = True` unnecessary** — Auth is JWT-based. **Fix:** Removed — JWT uses Authorization header, not cookies.
- [x] **`SECURE_BROWSER_XSS_FILTER` deprecated** — Django 4.1+: `X-XSS-Protection` header can introduce vulnerabilities. **Fix:** Removed from production security settings with explanatory comment.
- [ ] **⚪ DEFERRED — No CSP or Permissions-Policy headers** — **Fix:** Add `django-csp` middleware or set via reverse proxy. *(deferred — frontend/reverse-proxy task)*
- [x] **`celery_task_id` and `resume_file` path exposed in API** — `ResumeAnalysisDetailSerializer` leaks these (excluded from `SharedAnalysisSerializer` confirming they're sensitive). **Fix:** Removed `celery_task_id` from API response.
- [x] **`JobCreateSerializer` has no URL validation / SSRF prevention** — `job_url` field has no scheme validation. **Fix:** Added URL scheme validation (http/https only).

---

## Backlog — Edge Case Fixes

### P0 — Critical

- [x] **LLM empty `choices` / `None` content crash** — `openrouter_provider.py` L52: `response.choices[0].message.content.strip()` raises `IndexError` if content moderation returns empty `choices`, or `AttributeError` if `content` is `None` (refusal). **Fix:** Guard with `if not response.choices or not response.choices[0].message.content:` and raise `ValueError`.
- [x] **`json_repair` corrupts valid JSON** — L29: regex `r'"\s*\n\s*"' → '",\n"'` aggressively inserts commas between key:value pairs. L32-52: brace counting doesn't account for braces inside strings. **Fix:** Replaced with `json-repair` PyPI library.

### P1 — High

- [x] **`avg_ats` falsy-zero bug** — `DashboardStatsView`: `round(avg_ats, 1) if avg_ats else None` returns `None` when avg is exactly `0`. **Fix:** `if avg_ats is not None`.
- [x] **Retry-refund-retry race in tasks.py** — L100-107: On `Exception`, credits refunded then task retried. Retry runs for free since credits aren't re-deducted. **Fix:** Only refund on final retry attempt; skip refund when `will_retry=True`.
- [x] **`overall_grade` not normalized after validation** — `base.py` L116-120: Grade is uppercased/stripped for validation but the raw value is kept in `data`. **Fix:** Normalize `data['overall_grade'] = grade` after validation.
- [x] **Lock never released on success path** — `AnalyzeResumeView`: `cache.add(lock_key, 1, 30)` TTL = 30s, but lock is never deleted on success. **Note:** Lock is released at task start via `cache.delete()` — verified already handled.
- [x] **Concurrent subscription creation race** — `razorpay_service.py` L63-75: Check for existing subscription has no lock. **Fix:** Wrapped in `transaction.atomic()` with `select_for_update()`.
- [x] **Old `RazorpaySubscription` hard-deleted** — L77-85: Deleting old subscriptions to satisfy `OneToOneField` loses payment audit trail. **Fix:** Changed `OneToOneField` to `ForeignKey`; old subscriptions preserved.
- [x] **`MeView.delete()` soft-deletes then cascades** — Updates analyses (soft-delete) then `user.delete()` cascades and hard-deletes them anyway — wasted I/O. **Fix:** Removed redundant analysis `update()` call.

### P2 — Medium

- [x] **`quick_wins` must be exactly 3** — `base.py` L148-155: Rejects analyses with ≠3 quick wins from LLM. **Fix:** Accept ≥1, truncate to 3 if more.
- [x] **`max_tokens=4096` too low for analysis schema** — `openrouter_provider.py` L33: Response schema with 10 sentence suggestions routinely exceeds 4K tokens. **Fix:** Default raised to 8192, configurable via `AI_MAX_TOKENS` setting.
- [x] **SerpAPI `posted_at` returns "2 days ago" not ISO-8601** — `serpapi_source.py` L92. **Fix:** Added `_parse_relative_date()` to convert "X days ago" to ISO-8601.
- [x] **Adzuna hardcoded `£` currency** — L72-75: Salary shows `£` regardless of country. **Fix:** Added `_COUNTRY_CURRENCY` map keyed by country code.
- [x] **`DiscoveredJob` with empty `external_id`** — If source returns `None`, `external_id` becomes string `'None'`, all collide. **Fix:** Skip jobs with empty `external_id` in `discover_jobs_task`.
- [x] **Payment `limit` allows 0 or negative** — `PaymentHistoryView` L241: `min(int(limit), 100)` has no floor. **Fix:** `max(1, min(int(limit), 100))`.
- [x] **Account delete returns 204 with body** — RFC 7231: 204 should have no body. **Fix:** Changed to `Response(status=204)`.
- [x] **`ChangePasswordView` uses `datetime.now()` instead of `timezone.now()`** — L164: Produces naive datetime. **Fix:** Replaced with `timezone.now()`.
- [x] **`sentence_suggestions` not validated** — `base.py`: No check for `original`/`suggested`/`reason` keys in entries. **Fix:** Added sub-field validation with key + type checks.
- [x] **`section_feedback` value types not validated** — `base.py` L138-145: `score` could be a string, `feedback` could be wrong type. **Fix:** Added type checks for `score` (numeric, clamped 0-100) and `feedback` (list).
- [x] **`discover_jobs_task` lock releases before processing** — `tasks.py` L432-443: `select_for_update(skip_locked=True)` only locks inside `transaction.atomic()`. **Fix:** Claim alerts by bumping `next_run_at` inside the initial transaction.
- [x] **`check_balance()` has no `select_for_update()`** — `services.py` L56-64: Read is stale by the time `deduct_credits()` runs. **Fix:** Documented as advisory; uses `get_or_create` for consistency. Authoritative check happens inside `deduct_credits()` with `select_for_update()`.

### P3 — Low

- [x] **`AnalysisDeleteView` uses `ReadOnlyThrottle`** — Write operation using read throttle. **Fix:** Changed to `WriteThrottle` (scope='write', 60/hr).
- [x] **`AnalysisShareView` uses `ReadOnlyThrottle`** — Same issue. **Fix:** Changed to `WriteThrottle`.
- [x] **Plan `display_order` ties cause wrong upgrade/downgrade** — `services.py` L277-280: Same `display_order` → falls to downgrade branch. **Fix:** Added `price` tiebreaker: `(new_order, new_price) > (current_order, current_price)`.
- [x] **`signals.py` deletes file without shared-file check** — Unconditionally deletes physical file. **Fix:** Added `Resume.objects.filter(file=...).exclude(pk=...).exists()` guard.
- [x] **`ResumeAnalysis.resume_file` / `report_pdf` not cleaned up on delete** — Signal only handles `Resume` model. **Fix:** Added `post_delete` signal for `ResumeAnalysis` to clean up `report_pdf`.
- [x] **`stale cleanup` refund + update not atomic** — `tasks.py` L178-196: Queryset can change between refund loop and `.update()`. **Fix:** Wrapped in `transaction.atomic()` with `select_for_update()`.

---

## Backlog — Scalability & Performance

### P1 — High

- [x] **OpenAI client instantiated per call** — `factory.py`, `resume_generator.py`, `job_matcher.py`, `job_search_profile.py` each create a new `OpenAI()` client per invocation. **Fix:** Added `@functools.lru_cache(maxsize=4)` `_get_openai_client(api_key, base_url)` in `factory.py`; all modules now share cached clients.
- [x] **No LLM retry logic** — No retry on transient failures (429, 502/503, timeouts). **Fix:** Added `tenacity` retry decorator (`llm_retry`) with exponential backoff on `RateLimitError`, `APITimeoutError`, `APIConnectionError`, and 5xx status errors. Applied to `openrouter_provider.py`, `resume_generator.py`, `job_matcher.py`, `job_search_profile.py`. Also added `retry_backoff=True` to Celery `run_analysis_task`.
- [x] **No page limit on PDF extraction** — Malicious huge PDF → unbounded CPU/memory. **Fix:** Added `MAX_PDF_PAGES` setting (default 50) in `settings.py`; `pdf_extractor.py` raises `ValueError` if page count exceeds limit.
- [x] **No input length / token estimation before LLM calls** — 200-page resume → massive prompt exceeding context window. **Fix:** Added `estimate_tokens()` and `check_prompt_length()` utilities in `base.py`; `_build_prompt()` auto-truncates oversized prompts. `resume_generator.py` also checks prompt length before LLM call.

### P2 — Medium

- [x] **`DashboardStatsView` no caching** — Runs 5 aggregate queries per request with no caching. **Fix:** Added per-user Redis cache with 5-min TTL (`cache_key = f'dashboard_stats:{user.id}'`).
- [x] **No pagination on `GeneratedResumeListView`, `JobAlertListCreateView`** — Returns all records unbounded. **Fix:** Added DRF `PageNumberPagination` (20 per page) to both views.
- [x] **`JobAlertMatchListView` uses manual pagination** — Django `Paginator` instead of DRF's pagination classes. **Fix:** Switched to DRF `PageNumberPagination` with consistent envelope format.
- [x] **Token blacklisting iterates one-by-one** — `MeView.delete()` and `ChangePasswordView.post()` loop with individual `get_or_create`. **Fix:** Replaced with `BlacklistedToken.objects.bulk_create([...], ignore_conflicts=True)`.
- [x] ~~**Prompt template resent every request**~~ — Accepted design: structured output mode requires model support not yet available on OpenRouter; system prompt caching would add complexity for minimal savings
- [x] **Migrations run on every web container start** — `entrypoint.sh` + `Procfile` both run `migrate --noinput`. Concurrent replicas → migration race. **Fix:** Removed inline migrate from `Procfile` web command; `entrypoint.sh` now uses `flock -w 120 /tmp/migrate.lock` to serialize migrations.
- [x] **No `--max-tasks-per-child` for Celery workers** — AI/PDF processing leaks memory over time. **Fix:** Added `--max-tasks-per-child=50` to both `Procfile` and `entrypoint.sh` (configurable via `CELERY_MAX_TASKS_PER_CHILD` env var).
- ~~[ ] **Adzuna source always page 1** — Removed in Phase 12 (Firecrawl replaced all external job sources).~~
- [x] **`unbounded listings` in discover_jobs_task** — capped via `MAX_CRAWL_JOBS_PER_RUN = 200` *(v0.16.0)*

### P3 — Low

- [x] **Style objects recreated in `pdf_report.py`** — `_build_styles()` creates ~20 `ParagraphStyle` objects on every call. **Fix:** Added `_CACHED_STYLES` module-level cache; styles built once and reused.
- ~~[ ] **Adzuna style iteration** — Removed in Phase 12 (Adzuna source deleted).~~
- ~~[ ] **SerpAPI `num` parameter ignored** — Removed in Phase 12 (SerpAPI source deleted).~~
- [x] **Job source factory creates instances every call** — `get_job_sources()` instantiates fresh objects each time. **Fix:** Added `_cached_sources` module-level cache in `job_sources/factory.py`.

---

## Backlog — Quick Wins (Backend Enhancements)

### Notification & Email

- [x] **Respect notification preferences** — emails now check `feature_updates_email` / `newsletters_email` prefs *(v0.19.0)*
- [x] **Analysis completion email** — `analysis-complete` template, fires on task completion *(v0.19.0)*
- [x] **Weekly email digest** — Celery Beat task every Monday 9 AM UTC *(v0.19.0)*

### Analysis Pipeline

- [x] **Duplicate resume warning** — API response includes `duplicate_resume_warning` when hash matches *(v0.19.0)*
- [x] **Cancel stuck analysis** — `POST /api/analyses/<id>/cancel/` revokes Celery task, refunds credits *(v0.19.0)*
- [x] **Bulk delete analyses** — `POST /api/analyses/bulk-delete/` soft-deletes up to 50 *(v0.19.0)*

### Dashboard & Analytics

- [x] **Grade distribution** — `grade_distribution` in `/dashboard/stats/` *(v0.19.0)*
- [x] **Industry breakdown** — `top_industries` stat (top 5) *(v0.19.0)*
- [x] **Per-ATS score trends** — `score_trend` includes `generic_ats`, `workday_ats`, `greenhouse_ats` *(v0.19.0)*
- [x] **Show AI response time** — `ai_response_time_seconds` on detail serializer *(v0.19.0)*

### Data & Compliance

- [x] **Account data export (GDPR)** — `GET /api/account/export/` downloads all user data *(v0.19.0)*
- [x] **Export analysis as JSON** — `GET /api/analyses/<id>/export-json/` *(v0.19.0)*

### Jobs Feature

- [ ] **⚪ DEFERRED — Job match scoring** — when user creates a Job, auto-compare JD to their best resume via lightweight LLM prompt
- [ ] **⚪ DEFERRED — Scheduled re-analysis** — Celery Beat task to rerun analysis weekly with same resume + JD (track improvement over time)

### Infrastructure

- [x] Verify rate limiting works with Redis-backed cache — `TESTING` flag + `LocMemCache` isolation *(v0.8.1)*

### Code Quality

- [x] **Consolidate inline imports** — Moved `from accounts.services import ...` to top-level in `analyzer/views.py` (9 inline → 1 top-level). `tasks.py` kept inline per Celery best practice.
- [x] **Standardize error response format** — Custom DRF exception handler (`resume_ai/exception_handler.py`) ensures all errors return `{detail, errors}`. All views now use `raise_exception=True`. Celery views fixed `'error'`→`'detail'`. Chat views no longer leak exception strings to clients.
- [x] **`except (ValueError, Exception)` cleanup** — No longer present in codebase *(already cleaned up)*
- [x] **PDF file validation** — Added `_validate_pdf_magic()` checking `%PDF` magic bytes before processing *(v0.23.0)*
- [x] **DOCX renderer lacks input sanitization** — Added `_safe()` to strip control chars/null bytes from all user data *(v0.23.0)*
- [x] **Error message leaks from Firecrawl** — `str(exc)` stored in DB only; user-facing error is generic `'Failed to fetch job description…'` *(already in code)*
- [x] **No `try/finally` on PDF extraction** — `pdf_extractor.py` uses `try/finally` for `file_field.open()`/`.close()` *(already in code)*
- [x] **`JobAlertCreateSerializer` preferences not schema-validated** — `validate_preferences` now validates allowed keys + type checks *(already in code)*

### Serializer Validation Gaps

- [x] **Email not required on registration** — `RegisterSerializer` now has `email = serializers.EmailField(required=True)` + `validate_email` rejects empty *(already in code)*
- [x] **Duplicate emails not blocked on registration** — `RegisterSerializer.validate_email()` checks `User.objects.filter(email__iexact=value).exists()` *(already in code)*
- [x] **Country code not validated** — `UpdateUserSerializer.validate_country_code()` uses regex `^\+\d{1,4}$` *(already in code)*
- [x] **Mobile number no min length** — `validate_mobile_number()` enforces `len(value) < 7` *(already in code)*
- [x] **Payment `notes` JSON exposed to client** — `PaymentHistorySerializer` does not include `notes` field *(already in code)*

---

## Backlog — Test Coverage

> Missing tests identified in audit. Priority is relative to feature risk.

### P1 — High (Missing tests for user-facing flows)

- [x] **Forgot/reset password flow** — covered in `test_new_endpoints.py` *(v0.19.0)*
- [x] **Notification preferences** — covered in `test_new_endpoints.py` *(v0.19.0)*
- [x] **Wallet endpoints** — covered in `test_new_endpoints.py` *(v0.19.0)*
- [x] **Plan listing & subscribe** — covered in `test_new_endpoints.py` *(v0.19.0)*

### P2 — Medium

- [x] **PDF export** — Tests for `AnalysisPDFExportView` *(v0.23.0)*
- [x] **Analysis status polling** — Tests for `AnalysisStatusView` *(v0.23.0)*
- [x] **Dashboard stats** — covered in `test_new_endpoints.py` *(v0.19.0)*
- [x] **Resume generation pipeline** — 81 tests in `test_resume_generation.py` *(v0.16.1)*
- [x] **Analysis retry** — Tests for `RetryAnalysisView` *(v0.23.0)*
- [x] **Resume management** — Tests for `ResumeListView`, `ResumeDeleteView` *(v0.23.0)*

### P3 — Low

- [x] **Account deletion cascade** — Tests verify wallet + transaction cleanup *(v0.23.0)*
- [x] **Serializer edge cases** — 46 tests in `test_serializer_edge_cases.py`: username (min 3, max 30, reserved words, invalid chars), email (blank, duplicate case-insensitive), password (weak, numeric, mismatch), country code/mobile format, standardized error shape.

---

## Backlog — Feature Opportunities

> New feature ideas from audit analysis. Requires product discussion before implementation.

### High Value

- [ ] **⚪ DEFERRED — AI provider fallback / multi-provider** — If OpenRouter is down, analyses fail completely. Add fallback to direct Anthropic or OpenAI API. Requires: provider config model, priority/health tracking, circuit breaker pattern.
- [x] **🔴 IMMEDIATE — Token usage tracking & cost dashboard** — Track `prompt_tokens`/`completion_tokens` per analysis from `response.usage`. Store on `LLMResponse` model. Surface admin cost dashboard. Alert on budget thresholds. *(implemented — fields on LLMResponse, OpenRouter provider captures usage, cost estimation in analyzer service)*
- [ ] **⚪ DEFERRED — Streaming LLM responses** — Use SSE/WebSocket to stream partial analysis results to frontend instead of waiting 60-120s. Requires: Django Channels or SSE endpoint, frontend streaming client.
- [x] **🔴 IMMEDIATE — Email verification on registration** — Set `user.is_active = False` until email link clicked. Requires: verification token model, send/verify/resend endpoints, new email template, auth flow changes. *(implemented — EmailVerificationToken model, verify-email + resend-verification endpoints, email template seeded)*
- [x] **"Logout all devices"** — `POST /api/auth/logout-all/` blacklists all outstanding tokens *(v0.19.0)*

### Medium Value

- [x] **🔴 IMMEDIATE — Resume version history** — When user re-uploads modified resume, link to previous versions. Show improvement timeline (ATS score v1→v2→v3). *(implemented — ResumeVersion model, version chain via previous_resume FK, version history endpoint)*
- [x] **🔴 IMMEDIATE — Bulk analysis / batch mode** — Analyze one resume against multiple JDs at once (e.g., 5 postings). Compare results side-by-side. *(implemented — POST /api/analyze/bulk/ with up to 10 JDs, atomic credit deduction)*
- [x] **🔴 IMMEDIATE — Interview prep generation** — Leverage analysis gap data to generate likely interview questions customized to resume + JD. *(implemented — InterviewPrep model, LLM service, Celery task, CRUD endpoints)*
- [x] **🔴 IMMEDIATE — Cover letter generation** — Extend resume generation pipeline to produce a tailored cover letter from the analysis. *(implemented — CoverLetter model with tone choices, LLM service, Celery task, CRUD endpoints)*
- [x] **Webhook event replay/audit log** — `WebhookEvent` model with unique `event_id` stores all received events *(v0.13.1)*
- [x] **🔴 IMMEDIATE — Rate limit feedback in API responses** — Include `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers so frontend can show proactive warnings. *(implemented — HeaderAware throttle classes + RateLimitHeadersMiddleware)*

### Lower Value

- [ ] **⚪ DEFERRED — Hiring trends analytics** — Aggregate anonymized data across users to show trending skills, most-demanded roles, salary ranges by industry.
- [ ] **⚪ DEFERRED — Admin analytics dashboard** — System-wide metrics: active users, analyses/day, LLM token costs, error rates.
- [x] **🔵 P3 — Resume template marketplace** — 5 templates (ats_classic free + 4 premium), ResumeTemplate model, `premium_templates` plan flag, DB-validated slugs, dedicated PDF/DOCX renderers, admin, seed command. *(v0.25.0)*
- [ ] **🔵 P3 — LinkedIn resume import** — Import LinkedIn profile data directly instead of uploading PDF.

---

## Backlog — Deployment & Infrastructure

- [x] **P1: Update `runtime.txt`** — changed to `python-3.12` *(v0.19.0)*
- [x] **P2: Separate migrations from web start** — Fixed: Removed inline migrate from Procfile web command; entrypoint.sh uses `flock` to serialize concurrent migrations.
- [x] **P2: Health check: verify Redis + Celery** — Already implemented: `views_health.py` checks DB, Redis (set/get), and Celery (inspect.ping) *(already in code)*
- [x] **🟡 P2 — Add Sentry or error tracking** — Deferred Sentry; implemented Prometheus metrics with error counters + structured JSON logging for observability. *(v0.24.0)*
- [x] **🟡 P2 — Structured logging (JSON format)** — `python-json-logger` JSON formatter in production. Local dev keeps human-readable format. *(v0.24.0)*
- [x] **🟡 P2 — Emit custom metrics** — `django-prometheus` with custom metrics: analysis duration, LLM tokens, credit operations, payment failures, Celery task stats. `/metrics` endpoint exposed. *(v0.24.0)*
- [x] **🟡 P2 — Gunicorn timeout alignment** — Reduced from 120s to 110s in Procfile and entrypoint.sh. *(v0.24.0)*
- [x] **P3: Add `--max-tasks-per-child=50`** — Added to Procfile and entrypoint.sh (configurable via `CELERY_MAX_TASKS_PER_CHILD`).
- [x] **🟡 P2 — Celery task monitoring** — Flower as separate Railway service + admin-only Django endpoints. *(v0.24.0)*
- [x] **🟡 P2 — API versioning** — URL-based `/api/v1/`. Hard cut, no backward compat. DRF `URLPathVersioning`. *(v0.24.0)*

---

## Backlog — Admin Improvements

- [x] **P2: Add `raw_id_fields`** — added on 5 admin models *(v0.19.0)*
- [x] **P3: `DiscoveredJobAdmin` needs `list_per_page`** — set to 50 *(v0.19.0)*
- [ ] **⚪ DEFERRED — Admin dashboard enhancements** — Better admin views for Plan, UserProfile.

---

## Audit Backlog — Plan Quota Enforcement

> Existing from prior audit. Still relevant.

- [x] **Monthly analysis quota** — checks `plan.analyses_per_month`, returns 403 *(v0.19.0)*
- [x] **Per-plan resume size limit** — validates against `plan.max_resume_size_mb` *(v0.19.0)*
- [x] **PDF export feature flag** — `plan.pdf_export` check in `ExportPDFView` *(v0.19.0)*
- [x] **Share analysis feature flag** — `plan.share_analysis` check in `AnalysisShareView` *(v0.19.0)*
- [x] ~~**Job tracking feature flag**~~ — N/A: standalone `/api/jobs/` endpoints removed; job tracking handled via `DiscoveredJob`/`JobMatch` pipeline
- [x] **Max resumes stored** — blocks uploads at `plan.max_resumes_stored` limit *(v0.19.0)*

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

---

## Feed Page (Home) — Backend Tasks

> API endpoints & models needed to power the in-app feed/home page.

- [x] 🔵 **Personalized Job Opportunities** — `GET /api/v1/feed/jobs/` endpoint returning top matching `DiscoveredJob` records ranked by `JobSearchProfile` embedding similarity; paginated, filterable by remote/location/seniority *(v0.35.0 — `FeedJobsView` in `views_feed.py`)*
- [x] 🔵 **Career Insights & Market Intelligence** — `GET /api/v1/feed/insights/` endpoint aggregating trending skills, top hiring companies, avg salary by role/location from `DiscoveredJob` data; cache daily *(v0.35.0 — `FeedInsightsView` in `views_feed.py`)*
- [x] 🔵 **Trending vs Your Profile** — `GET /api/v1/feed/trending-skills/` endpoint comparing user's `JobSearchProfile.skills` against trending skills from recent `DiscoveredJob.skills_required`; returns matches, gaps, and growth % *(v0.35.0 — `FeedTrendingSkillsView` in `views_feed.py`)*
- [x] 🔵 **Job Alert & Interview Prep Hub** — `GET /api/v1/feed/hub/` composite endpoint returning active `JobAlert` summary + pending `InterviewPrep` + recent `CoverLetter` in one call *(v0.35.0 — `FeedHubView` in `views_feed.py`)*
- [x] 🔵 **Active Job Alerts Summary** — included in hub endpoint; per-alert stats: match count this week, last run status, health indicator (0 matches = suggest broadening) *(v0.35.0)*
- [x] 🔵 **Upcoming Interview Preps** — included in hub endpoint; list `InterviewPrep` with status=done linked to recent `JobMatch` entries with feedback=applied *(v0.35.0)*
- [ ] 🔵 **Applied Jobs Tracker** — new `JobApplication` model (FK to `DiscoveredJob` + User, status enum: applied/interviewing/offered/rejected/withdrawn, notes, applied_at); `GET/POST /api/v1/applications/`
- [x] 🔵 **Personalized Recommendations** — `GET /api/v1/feed/recommendations/` endpoint; AI-suggested next actions based on resume gaps, missing trending skills, unused features (no interview prep yet, etc.) *(v0.35.0 — `FeedRecommendationsView` in `views_feed.py`)*
- [ ] ⚪ **Referral & Connections** — `ReferralCode` model (user, code, uses, max_uses, bonus_credits); `GET/POST /api/v1/referrals/`; credit reward on referred user's first analysis
- [x] ⚪ **Onboarding / Empty States** — `GET /api/v1/feed/onboarding/` endpoint returning user completion checklist (has_resume, has_analysis, has_alert, has_interview_prep, has_cover_letter) + suggested next step *(v0.35.0 — `FeedOnboardingView` in `views_feed.py`)*

---

## ✅ Feed Insights Rework — Role-Accurate Market Snapshot

> **Goal:** Make `GET /api/v1/feed/insights/` return data that is meaningful for the user's specific role, not polluted by unrelated roles when auto-broadened. Also fix the salary representation to be useful (country currency, role-level, seniority-level).
>
> **Status:** ✅ Done (v0.40.0)

### 1. Dual job counts

- [x] 🔴 **Add `total_jobs_role_specific`** — count from narrow `role_qs` (role-matched jobs only). Keep existing `total_jobs_last_30d` as the overall market size. Frontend can show "47 Data Analyst jobs out of 1,523 total".

### 2. Salary rework

- [x] 🔴 **Replace `avg_salary_usd` with role-scoped, local-currency salary** — current field averages across ALL roles and ALL seniority levels in USD, which is meaningless.
  - **`avg_salary_role`** — average `salary_min_usd` from narrow `role_qs` only, converted to user's country currency.
  - **`avg_salary_by_seniority`** — breakdown by seniority level from narrow `role_qs`: `{"junior": X, "mid": Y, "senior": Z}`, in local currency.
  - **`salary_currency`** — ISO 4217 code (e.g. `"INR"`, `"USD"`, `"EUR"`) derived from user's profile country.
  - **Currency conversion** — maintain a simple `COUNTRY_TO_CURRENCY` and `USD_EXCHANGE_RATES` mapping (hardcoded or from env). Convert at response time. Rates don't need to be real-time for salary estimates.
  - **Remove `avg_salary_usd`** — deprecated; replaced by the above fields.

### 3. Role-scope all aggregations (not just skills)

- [x] 🔴 **Use narrow `role_qs` for all aggregations when broadened** — currently only `top_skills` uses the role-scoped queryset. Fix:
  - `top_companies` — use `role_qs` so it shows companies hiring for the user's role
  - `top_locations` — use `role_qs` so it shows where the user's role is in demand
  - `employment_type_breakdown` — use `role_qs` (e.g. Data Analyst may be mostly full-time)
  - `remote_policy_breakdown` — use `role_qs`
  - `seniority_breakdown` — use `role_qs`
  - Same pattern: `skills_qs = role_qs if (role_qs is not None and role_qs.exists()) else qs`

### 4. Documentation

- [x] 🟡 **Update FRONTEND_API_GUIDE.md §30.2** — document new response shape: `total_jobs_role_specific`, `avg_salary_role`, `avg_salary_by_seniority`, `salary_currency`. Remove `avg_salary_usd`. Update example JSON and field table.
- [x] 🟡 **Update CHANGELOG.md** — entry for the insights rework.

---

## ✅ Admin Daily Digest — Automated Platform Metrics Email

> Twice-daily email (9 AM + 11 PM IST) with ~40 metrics across 11 categories to admin recipients.
> **Status:** ✅ Done (v0.42.0)

### Service
- [x] `compute_digest_metrics()` — aggregates users, revenue, credits, analyses, resumes, LLM, job alerts, features, news, notifications, infra for last 24h.

### Celery Task
- [x] `send_admin_digest_task` — sends to `ADMIN_DIGEST_EMAILS` env var recipients.
- [x] Celery Beat: `admin-digest-morning` (9 AM IST), `admin-digest-night` (11 PM IST).

### Email Template
- [x] `admin-daily-digest` — HTML + plaintext, 11 color-coded sections.
- [x] Added to `seed_email_templates` command.

### Configuration
- [x] `ADMIN_DIGEST_EMAILS` env var — comma-separated emails.

### Tests
- [x] 34 tests in `analyzer/tests/test_admin_digest.py` (4 classes).

---

## ✅ News Feed — Ingest & Serve Career/Tech News

> Crawler bot pushes news snippets to i-Luffy; frontend consumes a paginated, filtered news feed.
> **Status:** ✅ Done (v0.41.0)

### Model
- [x] `NewsSnippet` — 20+ fields, UUID PK, 13 category choices, 3 sentiment, 10 flag-reason, 4 composite indexes. Migration `0035`.

### Ingest API (Crawler → i-Luffy)
- [x] `POST /api/v1/ingest/news/` — single upsert by `uuid` (fallback `source_url`).
- [x] `POST /api/v1/ingest/news/bulk/` — bulk upsert ≤200 per request.
- [x] `POST /api/v1/ingest/news/deactivate/` — deactivate by UUID list.
- [x] All use `X-Crawler-Key` auth, no rate limit.

### Feed API (i-Luffy → Frontend)
- [x] `GET /api/v1/feed/news/` — paginated list, filters: `category`, `region`, `sentiment`, `search`.
- [x] `GET /api/v1/feed/news/<uuid:id>/` — single snippet detail.

### Admin
- [x] `NewsSnippetAdmin` — list, filters, search.

### Tests
- [x] 26 tests in `analyzer/tests/test_news.py` (4 classes: single ingest, bulk, deactivate, feed).

### Documentation
- [x] `FRONTEND_API_GUIDE.md` §30.11 + §30.12, TS types, §32 rows.
- [x] `CHANGELOG.md` v0.41.0 entry.

---

## ✅ Documentation Gaps — Guide Fixes

> Gaps reported by frontend team after reading FRONTEND_API_GUIDE.md.
> **Status:** ✅ Done (v0.40.0)

- [x] 🔴 **Document notification feed endpoints** — `GET /api/v1/notifications/`, `GET /api/v1/notifications/unread-count/`, `POST /api/v1/notifications/mark-read/` are live in the backend (`analyzer/views.py` — `NotificationListView`, `NotificationUnreadCountView`, `NotificationMarkReadView`) but completely missing from the guide. Add new section with request/response shapes + add to §32 quick-reference table.
- [x] 🟡 **Document `/resume-chat/<id>/submit/` endpoint** — listed in §32 quick-reference table but §29 has no subsection documenting the request body (`{"action": "continue", "payload": {...}}`), response shape (`messages`, `current_step`, `step_number`, `total_steps`, `status`), or error codes. Add §29.X with full docs.
- [x] 🟡 **Clarify `plans/subscribe` vs `payments/subscribe` in §32** — both are correctly documented but the §32 quick-reference description for `plans/subscribe/` says "Switch plan (upgrade/downgrade)" which is misleading — it only handles free-tier downgrades (returns 402 for paid plans). Fix description to "Downgrade to free plan (402 if target plan is paid)".

---

## 🔴 Architecture Simplification — Reduce LLM Calls & Moving Parts

> **Goal:** Cut LLM prompts from 6 to 2, move resume understanding to upload time, make interview prep DB-based, remove redundant endpoints. Every user action should produce value with minimal latency.
>
> **Principle:** LLM only when generating new text. Understanding & matching = upload-time parse + DB. Analytics = DB aggregations over existing data.
>
> **Status:** Not started

### Current State (6 LLM prompts, value delayed)

```
Upload resume     → 0 LLM calls, 0 value (user must manually trigger everything)
Analysis          → 2 LLM calls (analysis + resume parse)
Interview prep    → 1 LLM call per request
Cover letter      → 1 LLM call per request
Resume rewrite    → 1 LLM call per request
Job search profile→ 1 LLM call (only on alert creation)
```

### Target State (2 LLM prompts, instant value on upload)

```
Upload resume     → 1 LLM call (merged parse + profile) + 1 embedding call → instant profile, feed, skill gaps
Analysis          → 1 LLM call (resume vs JD only — parse already done)
Interview prep    → 0 LLM calls (DB question bank)
Cover letter      → 1 LLM call (keep — too personalized for templates)
Resume rewrite    → 1 LLM call (keep — needs rewriting intelligence)
Job search profile→ 0 LLM calls (already extracted at upload)
```

---

### Phase A — Merge Resume Understanding into Upload Time

> **What:** Combine resume structured parsing + job search profile extraction into 1 LLM call triggered automatically on resume upload.
>
> **Why:** Currently these are 2 separate LLM calls (resume_parser.py + job_search_profile.py) that ask essentially the same question — "who is this person?" — in different formats. Job search profile extraction only runs when a JobAlert is created, meaning the job feed and skill gaps are empty until then.

#### Backend Changes

- [x] **New merged prompt** — Combine `RESUME_PARSE_PROMPT_TEMPLATE` (from `resume_parser.py`) and `_PROMPT_TEMPLATE` (from `job_search_profile.py`) into a single prompt that returns both structured resume data AND career profile in one JSON response. New file: `analyzer/services/resume_understanding.py` *(v0.35.0)*
- [x] **New Celery task: `process_resume_upload_task(resume_id)`** — Runs automatically on upload. Pipeline: extract PDF text → call merged LLM prompt → save parsed_content + career profile → compute embedding. Chains: `compute_resume_embedding_task` *(v0.35.0)*
- [x] **Move `parsed_content` to Resume model** — Currently lives on `ResumeAnalysis` (per-analysis). Should be per-resume since it describes the resume itself, not the resume-vs-JD comparison. Add `Resume.parsed_content` (JSONField, null=True) and `Resume.processing_status` (pending/processing/done/failed) *(v0.35.0)*
- [x] **Trigger on upload** — In `AnalyzeResumeView.post()`, after resume save, dispatch `process_resume_upload_task.delay(resume.id)` if resume is new (not a duplicate hash). Also trigger from any future standalone upload endpoint. *(v0.35.0)*
- [x] **Update `extract_job_search_profile_task`** — Remove LLM call. Instead, read from `Resume.parsed_content` career profile fields and save to `JobSearchProfile`. Becomes a pure DB copy. *(v0.35.0)*
- [x] **Update `compute_resume_embedding_task`** — No change, but now chains from `process_resume_upload_task` instead of `extract_job_search_profile_task` *(v0.35.0)*
- [x] **Deprecate standalone `resume_parser.py`** — Functionality merged into `resume_understanding.py` *(deleted in v0.36.0)*
- [x] **Deprecate standalone `job_search_profile.py` LLM call** — Profile data comes from upload-time parse *(deleted in v0.36.0)*

#### Endpoints Impacted

| Endpoint | Change | Frontend Impact |
|---|---|---|
| `POST /api/v1/analyze/` | Dispatches `process_resume_upload_task` for new resumes (transparent) | **None** |
| `GET /api/v1/resumes/` | Response gains: `parsed_content`, `career_profile`, `processing_status` | **Add:** Show parsed name/skills on resume card, "Processing…" spinner |
| `GET /api/v1/feed/jobs/` | Works immediately after upload (embedding ready sooner) | **None** — faster |
| `GET /api/v1/feed/trending-skills/` | User skills available immediately | **None** — faster |
| `GET /api/v1/dashboard/skill-gap/` | Same | **None** — faster |

---

### Phase B — Remove Resume Parse Step from Analysis Pipeline

> **What:** Drop Step 5 (`STEP_RESUME_PARSE`) from the analysis pipeline. Resume parsing is already done at upload time (Phase A).
>
> **Why:** Currently every analysis re-parses the resume (1 extra LLM call per analysis). Since parsed_content now lives on the Resume model, this is redundant.

#### Backend Changes

- [x] **Remove `STEP_RESUME_PARSE` from `analyzer.py`** — Delete `_step_resume_parse` method. Remove from `_STEPS` list. Pipeline goes from 5 steps → 4 steps. *(v0.35.0)*
- [x] **Update `_step_parse_result`** — If analysis needs `parsed_content`, read from `analysis.resume.parsed_content` instead of running a separate LLM call *(v0.35.0)*
- [x] **Keep backward compat** — `ResumeAnalysis.parsed_content` can remain as a denormalized copy (populated from `Resume.parsed_content` during `_step_parse_result`) or become a read-through property *(v0.35.0)*

#### Endpoints Impacted

| Endpoint | Change | Frontend Impact |
|---|---|---|
| `GET /api/v1/analyses/<id>/` | `parsed_content` still present (sourced from Resume now) | **None** |
| `GET /api/v1/analyses/<id>/status/` | One fewer pipeline step in progress | **Minor:** Update progress bar if it shows step names |

---

### Phase C — Interview Prep: LLM → DB Question Bank

> **What:** Replace LLM-generated interview questions with a curated question bank stored in DB, filtered by role/skill/gap data from analysis results.
>
> **Why:** Interview questions are predictable and categorizable. An LLM call per request is expensive and slow for something that can be pre-curated and personalized via DB filtering.

#### Backend Changes

- [x] **New model: `InterviewQuestion`** — Fields: `category` (behavioral/technical/situational/role_specific/gap_based), `question` (TextField), `why_asked` (TextField), `sample_answer_template` (TextField with `{role}`, `{company}`, `{skill}` placeholders), `difficulty` (easy/medium/hard), `tags` (JSONField — skill/keyword tags), `roles` (JSONField — applicable role patterns), `is_active` (bool), `created_at` *(v0.35.0 — migration 0031)*
- [x] **Seed data: management command `load_interview_questions`** — Populate 100-200 curated questions covering all categories. Tagged by common roles (software engineer, data analyst, product manager, etc.) and skills (Python, SQL, leadership, etc.) *(v0.35.0)*
- [x] **Rewrite `interview_prep.py` service** — Replace LLM call with DB query: filter `InterviewQuestion` by `analysis.jd_role` (match against `roles` JSON), `analysis.keyword_analysis.missing_keywords` (match against `tags`), section scores < 70 (gap_based category). Return 10-15 questions. Fill `sample_answer_template` placeholders with analysis data. *(v0.35.0 — `generate_interview_prep_from_db()`)*
- [x] **Simplify `generate_interview_prep_task`** — No longer async LLM call. Becomes synchronous DB lookup. Can run inline in the view (no Celery needed). *(v0.35.0)*
- [x] **Update `InterviewPrepView`** — Return 200 with results immediately instead of 202 + polling *(v0.35.0)*
- [x] **Remove `InterviewPrepStatusView`** — No longer needed (no async processing) *(v0.35.0)*

#### Endpoints Impacted

| Endpoint | Change | Frontend Impact |
|---|---|---|
| `POST /api/v1/analyses/<id>/interview-prep/` | Returns 200 with results immediately (was 202 + poll) | **Simplify:** Remove polling logic, use instant response |
| `GET /api/v1/interview-preps/` | Same response shape | **None** |
| ~~`GET /api/v1/analyses/<id>/interview-prep/` (status)~~ | **Can be removed** — no async processing | **Remove:** Status polling code |

---

### Phase D — Remove Bulk Analysis Endpoint

> **What:** Remove `POST /api/v1/analyze/bulk/`. Frontend can loop `POST /api/v1/analyze/` if needed.
>
> **Why:** It's just a server-side loop over the same logic. Adds maintenance burden with no real benefit. Frontend looping gives better UX (individual progress tracking per analysis).

#### Backend Changes

- [x] **Remove `BulkAnalyzeView`** from `analyzer/views.py` *(v0.35.0)*
- [x] **Remove URL** `path('analyze/bulk/', ...)` from `analyzer/urls.py` *(v0.35.0)*

#### Endpoints Impacted

| Endpoint | Change | Frontend Impact |
|---|---|---|
| ~~`POST /api/v1/analyze/bulk/`~~ | **Deleted** | **Replace:** Loop individual `POST /api/v1/analyze/` calls if needed |

---

### Phase E — Remove LLM Fallback in Job Matching

> **What:** Remove the LLM-based job matching fallback in `embedding_matcher.py`. Keep embedding-only matching.
>
> **Why:** Production uses PostgreSQL + pgvector. The LLM fallback (`job_matcher.py`) was for SQLite dev environments. It adds a full LLM call per 15-job batch — expensive and unnecessary.

#### Backend Changes

- [x] **Remove `_fallback_llm_matching()`** from `embedding_matcher.py` *(v0.35.0)*
- [x] **Deprecate / remove `job_matcher.py`** — No longer called from anywhere *(deleted in v0.36.0)*
- [x] **Ensure dev environments use PostgreSQL** — Document Docker-based local PostgreSQL setup as required *(v0.36.0 — README.md updated)*

#### Endpoints Impacted

| Endpoint | Change | Frontend Impact |
|---|---|---|
| None — internal only | No API surface change | **None** |

---

### Execution Order & Effort

| Phase | What | Files Touched | Endpoints Affected | Effort |
|---|---|---|---|---|
| **A** | Merge resume understanding into upload | 7 files | 2 endpoints gain fields | 2 days |
| **B** | Remove Step 5 from analysis pipeline | 2 files | 1 endpoint (status steps) | 0.5 day |
| **C** | Interview prep → DB question bank | 5 files + seed data | 3 endpoints simplified | 2 days |
| **D** | Remove bulk analysis endpoint | 2 files | 1 endpoint removed | 0.5 hour |
| **E** | Remove LLM job-matching fallback | 2 files | 0 | 0.5 hour |
| | **Total** | | | **~5 days** |

Each phase is independently deployable. Recommended order: **A → B → C → D → E**

### Net Result

| Metric | Before | After |
|---|---|---|
| LLM prompts to maintain | 6 | 2 (upload-time + analysis) |
| LLM calls on upload | 0 | 1 (merged) |
| LLM calls per analysis | 2 | 1 |
| Interview prep LLM calls | 1 per request | 0 (DB) |
| Time to first value | Minutes (manual trigger) | Seconds (upload = value) |
| Pipeline steps per analysis | 5 | 4 |
| Endpoints removed | 0 | 2 (bulk analysis, interview prep status) |

---

## Edge Cases & Migration Notes (per Phase)

### Phase A Edge Cases

1. **`_get_resume_text()` dependency loop** — Both `job_search_profile.py` and `embedding_service.py` get resume text from the latest completed analysis (`resume.analyses.filter(status='done')`). At upload time no analysis exists yet. **Fix:** `process_resume_upload_task` extracts PDF text directly via `PDFExtractor`, not `_get_resume_text()`.

2. **`parsed_content` lives on `ResumeAnalysis`, not `Resume`** — Moving it to `Resume` requires:
   - Django migration: add `Resume.parsed_content` (JSONField, nullable) + `Resume.processing_status`
   - Data migration: backfill existing `Resume.parsed_content` from latest analysis's `parsed_content`
   - Keep `ResumeAnalysis.parsed_content` column temporarily for backward compat

3. **`soft_delete()` clears `parsed_content`** — `ResumeAnalysis.soft_delete()` sets `parsed_content = None`. Once it lives on `Resume`, soft-deleting an analysis must NOT clear the resume's parsed data.

4. **`_prefill_from_resume()` fallback chain** — `resume_chat_service.py` queries `ResumeAnalysis.parsed_content` in two places. After migration, these must query `Resume.parsed_content` instead.

5. **`ResumeSerializer` doesn't include `parsed_content`** — Need to add `parsed_content`, `processing_status` fields.

6. **Duplicate resume (same hash) skips upload** — `get_or_create_from_upload()` returns `(existing, False)` for duplicates. Must NOT re-trigger `process_resume_upload_task`.

7. **Race condition: analysis starts before upload processing finishes** — If user uploads and immediately runs analysis, the analysis pipeline's step 5 might run before `process_resume_upload_task` completes. Falls back gracefully — analysis runs its own parse if `Resume.parsed_content` is null.

8. **`extract_job_search_profile_task` triggered on JobAlert creation** — After Phase A, becomes a DB copy. The mock patches in CRUD tests still work.

### Phase B Edge Cases

1. **Pipeline crash recovery** — If analysis was interrupted at step `resume_parse`, removing it from `_STEPS` means pipeline can't find it on resume. **Fix:** Treat `pipeline_step == 'resume_parse'` as equivalent to `STEP_DONE`.

2. **Existing analyses with `pipeline_step = 'resume_parse'`** — Data migration: change all `pipeline_step='resume_parse'` to `'done'`.

3. **`STEP_CHOICES` on model** — Keep the choice value in model for DB compatibility, but remove from pipeline `_STEPS`.

4. **`ResumeAnalysisDetailSerializer`** — Add fallback: `analysis.parsed_content or analysis.resume.parsed_content`.

### Phase C Edge Cases

1. **`InterviewPrep.llm_response` FK** — Already `null=True`, no migration needed.
2. **`InterviewPrepView` returns 202 → 200** — Must coordinate frontend change. During transition, could support both.
3. **`build_interview_prep_prompt()` uses analysis fields** — DB replacement must use same fields for filtering.

### Phase D Edge Cases

1. **No test coverage to remove** — `BulkAnalyzeView` has no dedicated tests. Clean removal.

### Phase E Edge Cases

1. **`_fallback_llm_matching()` called in 3 places** — Replace all with `return []` + warning log.
2. **Dev/test environments using SQLite** — Tests must mock embedding matching or use PostgreSQL.
3. **`job_matcher.py` still imported** — Delete import and file.

---

## Obsolete Tests Inventory

### Fully Obsolete (remove)

| Test Class | File | Lines | Phase |
|---|---|---|---|
| `StepResumeParsePipelineTests` (5 tests) | `test_resume_parser.py` | 275–349 | B |
| `ParsedContentModelTests.test_pipeline_step_resume_parse_exists` | `test_resume_parser.py` | 387–393 | B |
| `JobSearchProfileExtractionTest` (1 test) | `test_job_alerts.py` | 323–366 | A |
| `JobMatcherServiceTest` (1 test) | `test_job_alerts.py` | 419–462 | E |

### Need Rewriting

| Test | File | What Changes |
|---|---|---|
| `ParsedContentModelTests` (3 remaining) | `test_resume_parser.py` | Assert on `Resume.parsed_content` |
| `test_soft_delete_clears_parsed_content` | `test_resume_parser.py` | Soft-delete should NOT clear `Resume.parsed_content` |
| `ChatBuilderParsedContentFallbackTests` (5 tests) | `test_resume_parser.py` | Read from `Resume.parsed_content` |
| `ParsedContentSerializerTests` (2 tests) | `test_resume_parser.py` | Serializer sources from Resume |
| CRUD tests with `@patch('...extract_job_search_profile_task')` | `test_job_alerts.py` | Task is now DB copy |

### New Tests Needed

| What to Test | Phase |
|---|---|
| `process_resume_upload_task` — happy path, duplicate skip, PDF failure | A |
| `Resume.parsed_content` field, `Resume.processing_status` transitions | A |
| Merged prompt returns structured resume + career profile | A |
| Pipeline runs with 4 steps (no `resume_parse`) | B |
| `InterviewQuestion` model, seed data, filtering | C |
| `InterviewPrepView` returns 200 with instant results | C |
| Embedding matcher returns `[]` when no embedding (no fallback) | E |




