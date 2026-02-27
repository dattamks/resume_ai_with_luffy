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
- [ ] **Webhook IP allowlisting missing** — Only HMAC verification. If secret leaks, any IP can send fake events. **Fix:** Add middleware/decorator to check against Razorpay's published IP ranges.

### P3 — Low Security

- [x] **Razorpay secrets have plaintext defaults** — `settings.py` L300-302: `'rzp_test_placeholder'`. **Fix:** Added `warnings.warn()` in production when placeholder credentials detected.
- [x] **`CORS_ALLOW_CREDENTIALS = True` unnecessary** — Auth is JWT-based. **Fix:** Removed — JWT uses Authorization header, not cookies.
- [x] **`SECURE_BROWSER_XSS_FILTER` deprecated** — Django 4.1+: `X-XSS-Protection` header can introduce vulnerabilities. **Fix:** Removed from production security settings with explanatory comment.
- [ ] **No CSP or Permissions-Policy headers** — **Fix:** Add `django-csp` middleware or set via reverse proxy.
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

- [ ] **OpenAI client instantiated per call** — `factory.py`, `resume_generator.py`, `job_matcher.py`, `job_search_profile.py` each create a new `OpenAI()` client per invocation. Wastes TCP connections, misses connection pooling. **Fix:** Module-level singleton or LRU-cached factory keyed by `(base_url, api_key)`.
- [ ] **No LLM retry logic** — `openrouter_provider.py` L38-47: No retry on transient failures (429, 502/503, timeouts). Single flaky response wastes credits. `tasks.py` `autoretry_for` only covers `ConnectionError/OSError/TimeoutError`, not `openai.RateLimitError`. **Fix:** Add `tenacity` retry with exponential backoff on 429/5xx, or add `openai.RateLimitError`, `openai.APITimeoutError` to `autoretry_for`.
- [ ] **No page limit on PDF extraction** — `pdf_extractor.py` L37-47: Malicious 10,000-page PDF → unbounded CPU/memory. **Fix:** Add `MAX_PDF_PAGES = 50` setting; raise `ValueError` if page count exceeds.
- [ ] **No input length / token estimation before LLM calls** — 200-page resume → massive prompt exceeding context window, wasting API cost. **Fix:** Pre-flight token estimation via `tiktoken`; truncate with notice if over threshold.

### P2 — Medium

- [ ] **`DashboardStatsView` no caching** — Runs 5 aggregate queries per request with no caching. **Fix:** Add `@method_decorator(cache_page(300))` or manual cache with 5-min TTL.
- [ ] **No pagination on `JobListCreateView`, `GeneratedResumeListView`, `JobAlertListCreateView`** — Returns all records unbounded. **Fix:** Add DRF pagination class to each.
- [ ] **`JobAlertMatchListView` uses manual pagination** — Django `Paginator` instead of DRF's pagination classes. Inconsistent response format. **Fix:** Switch to `PageNumberPagination`.
- [ ] **Token blacklisting iterates one-by-one** — `MeView.delete()` loops `OutstandingToken` with individual `get_or_create`. **Fix:** `BlacklistedToken.objects.bulk_create([...], ignore_conflicts=True)`.
- [ ] **Prompt template resent every request (~2,200 chars)** — Full JSON schema embedded in every LLM prompt. **Fix:** Use function-calling / structured output mode if supported by model; otherwise, explore system prompt caching.
- [ ] **Migrations run on every web container start** — `entrypoint.sh` + `Procfile` both run `migrate --noinput`. Concurrent replicas → migration race. **Fix:** Run migrations as a separate Railway deploy hook or one-shot service.
- [ ] **No `--max-tasks-per-child` for Celery workers** — AI/PDF processing leaks memory over time. **Fix:** Add `--max-tasks-per-child=50` to Celery worker command.
- [ ] **Adzuna source always page 1** — `adzuna_source.py` L48: Hardcoded `/search/1` with 20-result cap. **Fix:** Add pagination support or document the limitation.
- [ ] **`unbounded listings` in discover_jobs_task** — `all_listings.extend(listings)` with no limit. Job source returning thousands of results overwhelms the matcher. **Fix:** Cap `all_listings` at a configurable max (e.g., 200).

### P3 — Low

- [ ] **Style objects recreated in `pdf_report.py`** — `_build_styles()` creates ~20 `ParagraphStyle` objects on every call. **Fix:** Cache at module level.
- [ ] **Adzuna style iteration** — `resume_docx_renderer.py` L42-56: Iterates all styles into a list just to check set membership. **Fix:** Use `set()` or `try/except KeyError`.
- [ ] **SerpAPI `num` parameter ignored** — SerpAPI Google Jobs engine doesn't support `num`. Result count is Google-determined. **Fix:** Remove `num` param, document behavior.
- [ ] **Job source factory creates instances every call** — `get_job_sources()` instantiates fresh objects each time. **Fix:** Cache instances by source type.

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

### Code Quality

- [ ] **Consolidate inline imports** — Multiple views have repeated inline `from accounts.services import ...`. Move to top-level imports.
- [ ] **Standardize error response format** — Some views use `raise_exception=True`, others return `serializer.errors` manually. Pick one pattern.
- [ ] **`except (ValueError, Exception)` cleanup** — Redundant catches in `job_matcher.py`, `accounts/views.py`. Replace with just `except Exception`.
- [ ] **PDF file validation** — `pdf_extractor.py` has no validation that uploaded file is actually a PDF. Add magic-byte check before `pdfplumber.open()`.
- [ ] **DOCX renderer lacks input sanitization** — Unlike PDF renderer which uses `_safe()`, DOCX renderer passes raw user data. XML-escape special characters.
- [ ] **Error message leaks from Firecrawl** — `jd_fetcher.py` L90-93: `str(exc)` could expose API keys or internal URLs. Sanitize before raising to user.
- [ ] **No `try/finally` on PDF extraction** — `pdf_extractor.py` L35-37: `file_field` not closed if `pdfplumber.open()` raises. Use `try/finally`.
- [ ] **`JobAlertCreateSerializer` preferences not schema-validated** — `validate_preferences` only checks `isinstance(dict)`. Arbitrary JSON payloads stored. Add allowed-key validation.

### Serializer Validation Gaps

- [ ] **Email not required on registration** — `RegisterSerializer` allows `email=""`. User can never reset password. **Fix:** Add `email = serializers.EmailField(required=True)`.
- [ ] **Duplicate emails not blocked on registration** — Two users can register with same email. `UpdateUserSerializer` blocks duplicates on update (inconsistent). **Fix:** Add uniqueness check in `RegisterSerializer.validate_email()`.
- [ ] **Country code not validated** — `UpdateUserSerializer` accepts any `+XXXX` (e.g., `+ZZZZ`). **Fix:** Validate against real ITU codes or use a library.
- [ ] **Mobile number no min length** — Single digit `"1"` passes validation. **Fix:** Add `min_length=7` or similar.
- [ ] **Payment `notes` JSON exposed to client** — `PaymentHistorySerializer` L263 exposes internal metadata. **Fix:** Exclude or filter `notes` field.

---

## Backlog — Test Coverage

> Missing tests identified in audit. Priority is relative to feature risk.

### P1 — High (Missing tests for user-facing flows)

- [ ] **Forgot/reset password flow** — No tests for `ForgotPasswordView` or `ResetPasswordView` despite having serializers and views
- [ ] **Notification preferences** — No tests for GET/PUT notification preferences
- [ ] **Wallet endpoints** — No tests for `WalletView`, `WalletTransactionListView`, `WalletTopUpView` (Razorpay tests exist but don't cover wallet views directly)
- [ ] **Plan listing & subscribe** — No tests for `PlanListView`, `PlanSubscribeView`

### P2 — Medium

- [ ] **PDF export** — No tests for `AnalysisPDFExportView`
- [ ] **Analysis status polling** — No tests for `AnalysisStatusView`
- [ ] **Dashboard stats** — No tests for `DashboardStatsView` (including the `avg_ats` zero bug)
- [ ] **Resume generation pipeline** — No tests for `GenerateResumeView`, `GeneratedResumeStatusView`, `GeneratedResumeDownloadView`, `GeneratedResumeListView` (4 endpoints)
- [ ] **Analysis retry** — No tests for `RetryAnalysisView`
- [ ] **Resume management** — No tests for `ResumeListView`, `ResumeDeleteView`

### P3 — Low

- [ ] **Account deletion cascade** — `test_profile.py` tests deletion but doesn't verify wallet/transaction cleanup
- [ ] **Serializer edge cases** — No tests for `RegisterSerializer` with blank email, duplicate email, invalid country code/mobile number

---

## Backlog — Feature Opportunities

> New feature ideas from audit analysis. Requires product discussion before implementation.

### High Value

- [ ] **AI provider fallback / multi-provider** — If OpenRouter is down, analyses fail completely. Add fallback to direct Anthropic or OpenAI API. Requires: provider config model, priority/health tracking, circuit breaker pattern.
- [ ] **Token usage tracking & cost dashboard** — Track `prompt_tokens`/`completion_tokens` per analysis from `response.usage`. Store on `LLMResponse` model. Surface admin cost dashboard. Alert on budget thresholds.
- [ ] **Streaming LLM responses** — Use SSE/WebSocket to stream partial analysis results to frontend instead of waiting 60-120s. Requires: Django Channels or SSE endpoint, frontend streaming client.
- [ ] **Email verification on registration** — Set `user.is_active = False` until email link clicked. Requires: verification token model, send/verify/resend endpoints, new email template, auth flow changes.
- [ ] **"Logout all devices"** — One-click invalidation of all JWT sessions. **Fix:** New endpoint that blacklists all `OutstandingToken` for the user.

### Medium Value

- [ ] **Resume version history** — When user re-uploads modified resume, link to previous versions. Show improvement timeline (ATS score v1→v2→v3).
- [ ] **Bulk analysis / batch mode** — Analyze one resume against multiple JDs at once (e.g., 5 postings). Compare results side-by-side.
- [ ] **Interview prep generation** — Leverage analysis gap data to generate likely interview questions customized to resume + JD.
- [ ] **Cover letter generation** — Extend resume generation pipeline to produce a tailored cover letter from the analysis.
- [ ] **Webhook event replay/audit log** — Store all received webhook events as raw JSON for debugging and reconciliation. Currently webhooks are processed but not logged as events.
- [ ] **Rate limit feedback in API responses** — Include `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers so frontend can show proactive warnings.

### Lower Value

- [ ] **Hiring trends analytics** — Aggregate anonymized data across users to show trending skills, most-demanded roles, salary ranges by industry.
- [ ] **Admin analytics dashboard** — System-wide metrics: active users, analyses/day, LLM token costs, error rates.
- [ ] **Resume template marketplace** — Multiple resume templates beyond `ats_classic`. Premium templates behind higher plans.
- [ ] **LinkedIn resume import** — Import LinkedIn profile data directly instead of uploading PDF.

---

## Backlog — Deployment & Infrastructure

- [ ] **P1: Update `runtime.txt`** — `python-3.12.1` is outdated with known security fixes. Change to `python-3.12` for latest patch auto-pick.
- [ ] **P2: Separate migrations from web start** — Run as Railway deploy hook or one-shot service, not on every container start (`entrypoint.sh` + `Procfile` both run `migrate --noinput`).
- [ ] **P2: Health check: verify Redis + Celery** — Current check only tests DB. App reports healthy when analysis submissions silently fail.
- [ ] **P2: Add Sentry or error tracking** — Bare `except` blocks swallow errors with only `logger.exception()`. No alerting.
- [ ] **P2: Structured logging (JSON format)** — For better log aggregation and search in Railway/Datadog.
- [ ] **P2: Emit custom metrics** — Prometheus/StatsD for: analysis duration, LLM token usage, credit operations, payment failures.
- [ ] **P3: Gunicorn timeout alignment** — `--timeout 120` matches Railway's proxy timeout; reduce to `--timeout 110` so Gunicorn responds before proxy kills the connection.
- [ ] **P3: Add `--max-tasks-per-child=50`** — Celery worker memory leak prevention.
- [ ] **P3: Celery task monitoring** — Flower or custom task status dashboard.
- [ ] **P3: API versioning** — URL-based or header-based API versioning for future-proofing.

---

## Backlog — Admin Improvements

- [ ] **P2: Add `raw_id_fields`** — Missing on `ResumeAdmin` (user), `JobAdmin` (user, resume), `GeneratedResumeAdmin` (user, analysis), `ResumeAnalysisAdmin` (user, resume), `JobAlertAdmin` (user, resume), `JobMatchAdmin` (job_alert, discovered_job). Dropdown loads all records on large datasets.
- [ ] **P3: `DiscoveredJobAdmin` needs `list_per_page`** — Many discovered jobs → slow admin pages.
- [ ] **P3: Admin dashboard enhancements** — Better admin views for Plan, UserProfile.

---

## Audit Backlog — Plan Quota Enforcement

> Existing from prior audit. Still relevant.

- [ ] **Monthly analysis quota** — Check `plan.analyses_per_month` in `AnalyzeResumeView.post()` before creating analysis
- [ ] **Per-plan resume size limit** — Use `plan.max_resume_size_mb` instead of global `settings.MAX_RESUME_SIZE_MB` in `ResumeAnalysisCreateSerializer`
- [ ] **PDF export feature flag** — Check `plan.pdf_export` in `ExportPDFView`
- [ ] **Share analysis feature flag** — Check `plan.share_analysis` in `AnalysisShareView`
- [ ] **Job tracking feature flag** — Check `plan.job_tracking` in `JobCreateView`
- [ ] **Max resumes stored** — Check `plan.max_resumes_stored` before accepting new uploads

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
