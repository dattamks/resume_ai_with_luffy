# Changelog

All notable changes to the Resume AI backend are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.16.3] — 2026-02-27

### Added
- **Google OAuth login** — Two new endpoints for Google Sign-In:
  - `POST /api/auth/google/` — Verifies Google ID token. Existing users get JWT tokens immediately; new users receive a signed `temp_token` for registration completion.
  - `POST /api/auth/google/complete/` — Completes registration for new Google users with username, password, and consent checkboxes.
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
- **Registration consent checkboxes** — `POST /api/auth/register/` now requires:
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
- **`crawl_jobs_for_alert_task`** — Single-alert manual crawl (used by `POST /api/job-alerts/<id>/run/`). Includes credit deduction, crawling, embedding, matching, and notification in one task.
- **`match_all_alerts_task`** — Runs after daily crawl. For each active alert: embedding match → JobMatch → SentAlert dedup → Notification → email digest.
- **`compute_resume_embedding_task`** — Triggered after profile extraction. Stores embedding on `JobSearchProfile`.
- **`SentAlert` model** — Dedup log preventing resending same job to same user per channel.
- **`Notification` model** — In-app notification store for bell/badge. Types: `job_match`, `analysis_done`, `resume_generated`, `system`.
- **Notification API endpoints:** `GET /api/notifications/`, `GET /api/notifications/unread-count/`, `POST /api/notifications/mark-read/`.
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
- **Manual run endpoint** — `POST /api/job-alerts/<id>/run/` now uses `crawl_jobs_for_alert_task` (Firecrawl + embedding matching) instead of `discover_jobs_for_alert_task`.
- **Celery Beat schedule** — Replaced `discover-jobs` (6h interval) with `crawl-jobs-daily` (crontab 20:30 UTC).
- **Cost reduction** — ~$55-80/month (SerpAPI + Adzuna + LLM scoring) → ~$5-16/month (Firecrawl + embeddings).

---

## [0.13.1] — 2026-02-27

### Payment Linkage Audit — Security & Correctness Fixes

### Fixed
- **PlanSubscribeView security** — Blocked direct upgrade to paid plans without payment. Returns `402 Payment Required` directing to `/api/auth/payments/subscribe/`. Only free-plan downgrades allowed.
- **WalletTopUpView security** — Deprecated free credit grants. Returns `402 Payment Required` directing to `/api/auth/payments/topup/`.
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
- `POST /api/auth/wallet/topup/` — Now returns `402` (deprecated; use `/api/auth/payments/topup/`).
- `POST /api/auth/plans/subscribe/` — Now returns `402` for paid plans (use `/api/auth/payments/subscribe/`).

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
- **8 REST API endpoints** (under `/api/auth/payments/`):
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
  - `GET/POST /api/job-alerts/` — List/create alerts (plan-gated, quota-checked).
  - `GET/PUT/DELETE /api/job-alerts/<uuid:id>/` — Detail/update/deactivate.
  - `GET /api/job-alerts/<uuid:id>/matches/` — Paginated matches with `?feedback=` filter.
  - `POST /api/job-alerts/<uuid:id>/matches/<uuid:match_id>/feedback/` — Submit user feedback.
  - `POST /api/job-alerts/<uuid:id>/run/` — Trigger manual discovery run (202 Accepted).
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
  - `POST /api/analyses/<id>/generate-resume/` — Trigger generation (1 credit). Validates analysis is done. Returns 202 with `{id, status, template, format, credits_used, balance}`. Returns 402 on insufficient credits.
  - `GET /api/analyses/<id>/generated-resume/` — Poll latest generation status.
  - `GET /api/analyses/<id>/generated-resume/download/` — 302 redirect to signed R2 URL.
  - `GET /api/generated-resumes/` — List all user's generated resumes (paginated).
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
- **Credit deduction on analysis submit** — `POST /api/analyze/` and `POST /api/analyses/<id>/retry/` now deduct 1 credit upfront. Returns **HTTP 402** with `{detail, balance, cost}` on insufficient credits. On task failure, credits are automatically refunded.
- **`accounts/services.py`** — New service layer with all credit/wallet business logic:
  - `deduct_credits()` / `refund_credits()` — Atomic with `select_for_update()` for race safety
  - `topup_credits()` — Multi-pack top-up (Pro only, blocked during pending downgrade)
  - `subscribe_plan()` — Handles upgrades (immediate bonus credits) and downgrades (scheduled at billing cycle end)
  - `check_balance()` / `can_use_feature()` — Query helpers
  - `grant_monthly_credits_for_user()` — Respects `max_credits_balance` cap
  - `process_expired_plans()` — Celery Beat hook for scheduled downgrades
  - `InsufficientCreditsError` — Custom exception with balance/cost info
- **Wallet endpoints:**
  - `GET /api/auth/wallet/` — Balance, plan credits info, top-up availability
  - `GET /api/auth/wallet/transactions/` — Paginated transaction history
  - `POST /api/auth/wallet/topup/` — Buy credit packs (`{quantity: N}`). Pro users only. Multi-pack supported.
- **Plan endpoints:**
  - `GET /api/auth/plans/` — List active plans (public, no auth required)
  - `POST /api/auth/plans/subscribe/` — Switch plan. Upgrades apply immediately with bonus credits. Downgrades scheduled until billing cycle ends.
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
