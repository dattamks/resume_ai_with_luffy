# i-Luffy — Admin Usage Guide

> **Last updated:** 2026-03-01 &nbsp;|&nbsp; **Platform version:** v0.27.0
> Complete operational guide for administrators managing the i-Luffy Resume AI platform.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Accessing the Admin Panel](#2-accessing-the-admin-panel)
3. [Deployment Architecture](#3-deployment-architecture)
4. [Managing Plans & Pricing](#4-managing-plans--pricing)
5. [Managing Users & Profiles](#5-managing-users--profiles)
6. [Credit System & Wallets](#6-credit-system--wallets)
7. [Razorpay Payment Management](#7-razorpay-payment-management)
8. [Email Templates](#8-email-templates)
9. [Resume Templates (Marketplace)](#9-resume-templates-marketplace)
10. [Job Alert System & Crawl Sources](#10-job-alert-system--crawl-sources)
11. [Monitoring Analyses & LLM Usage](#11-monitoring-analyses--llm-usage)
12. [Celery Task Monitoring](#12-celery-task-monitoring)
13. [Notifications Management](#13-notifications-management)
14. [Health Checks & Observability](#14-health-checks--observability)
15. [Environment Variables Reference](#15-environment-variables-reference)
16. [Management Commands](#16-management-commands)
17. [Periodic Tasks (Celery Beat)](#17-periodic-tasks-celery-beat)
18. [Backup & Recovery](#18-backup--recovery)
19. [Security Checklist](#19-security-checklist)
20. [Troubleshooting](#20-troubleshooting)

---

## 1. Overview

**i-Luffy** is an AI-powered resume optimization platform. Users upload PDF resumes, provide job descriptions, and receive:
- ATS compatibility scores (generic, Workday, Greenhouse)
- Keyword gap analysis
- Section-by-section feedback
- AI-rewritten bullet points
- Generated improved resumes (PDF/DOCX)
- Interview prep questions
- Cover letters
- Smart job alerts

As an admin, you manage plans, pricing, credit costs, email templates, resume templates, crawl sources, and monitor platform health.

---

## 2. Accessing the Admin Panel

### URL

```
Production:   https://<backend>.up.railway.app/admin/
Development:  http://localhost:8000/admin/
```

### Creating a Superuser

```bash
python manage.py createsuperuser
```

You'll be prompted for username, email, and password. This account has full admin access.

### Admin Panel Sections

| Section | Models Available |
|---------|-----------------|
| **Accounts** | User Profiles, Notification Preferences, Email Templates, Plans, Wallets, Wallet Transactions, Credit Costs, Razorpay Payments, Razorpay Subscriptions, Webhook Events, Consent Logs, Contact Submissions |
| **Analyzer** | Resumes, Resume Analyses, Scrape Results, LLM Responses, Generated Resumes, Job Search Profiles, Job Alerts, Discovered Jobs, Job Matches, Job Alert Runs, Crawl Sources, Sent Alerts, Notifications, Resume Versions, Interview Preps, Cover Letters, Resume Templates, Resume Chat Sessions |

---

## 3. Deployment Architecture

The platform runs on **Railway** with four separate services sharing the same codebase:

| Service | `SERVICE_TYPE` | Purpose |
|---------|---------------|---------|
| **Web** | `web` | Django + Gunicorn — serves API requests |
| **Worker** | `worker` | Celery worker — processes async tasks (analysis, PDF generation, job crawling) |
| **Beat** | `beat` | Celery beat scheduler — runs periodic tasks |
| **Flower** (optional) | `flower` | Celery monitoring dashboard |

### Infrastructure Dependencies

| Component | Service | Purpose |
|-----------|---------|---------|
| **PostgreSQL** | Railway (managed) | Primary database |
| **Redis** | Railway (managed) | Cache, Celery broker, session store |
| **Cloudflare R2** | External | File storage (resumes, PDFs, generated files) |
| **OpenRouter** | External | LLM API gateway (Claude, GPT-4o, Gemini) |
| **Razorpay** | External | Payment gateway (subscriptions, top-ups) |
| **SMTP** | External (Gmail/etc.) | Transactional emails |
| **Firecrawl** | External | Job board scraping for Smart Job Alerts |

### Startup Sequence (Web Service)

1. Acquire migration lock (`flock`)
2. Run `python manage.py migrate --noinput`
3. Run `python manage.py seed_email_templates` — creates/updates default email templates
4. Run `python manage.py seed_plans` — creates Free/Pro plans if missing
5. Start Gunicorn with configured workers/threads

---

## 4. Managing Plans & Pricing

Plans control what users can do. Access via **Admin → Accounts → Plans**.

### Plan Fields

| Field | Description |
|-------|-------------|
| **name** | Display name shown to users (e.g., "Free", "Pro") |
| **slug** | Code identifier (e.g., `free`, `pro`) — don't change after creation |
| **billing_cycle** | `free`, `monthly`, `yearly`, or `lifetime` |
| **price** | Current price in INR (what users pay) |
| **original_price** | Strikethrough price shown on pricing page (0 = no discount badge) |
| **credits_per_month** | Credits auto-granted each billing cycle |
| **max_credits_balance** | Cap on monthly credit grants (top-ups bypass this) |
| **topup_credits_per_pack** | Credits per top-up purchase (0 = top-ups disabled) |
| **topup_price** | Price per top-up pack in INR |
| **analyses_per_month** | Max analyses (0 = unlimited) |
| **max_resume_size_mb** | Max upload file size |
| **max_resumes_stored** | Concurrent resume storage limit (0 = unlimited) |
| **api_rate_per_hour** | API rate limit for this plan's users |

### Feature Flags (per Plan)

| Flag | Controls |
|------|----------|
| `job_notifications` | Can user create job alerts (Pro only) |
| `pdf_export` | Can export analysis as PDF |
| `share_analysis` | Can generate public share links |
| `job_tracking` | Can use job tracking features |
| `priority_queue` | Analyses processed in priority Celery queue |
| `email_support` | Has email support access |
| `premium_templates` | Can use premium resume templates |

### Razorpay Plan Sync

When you create or update a **paid** plan:
1. A Razorpay plan is **auto-created** via the API
2. The `razorpay_plan_id` field is populated automatically
3. Existing subscribers stay on their old pricing until they re-subscribe

**Admin Actions Available:**
- **Sync with Razorpay** — Manually force-sync selected plans with Razorpay
- **Duplicate Plans** — Clone a plan (starts deactivated for review)
- **Deactivate / Activate** — Control plan visibility (deactivated plans can't be assigned to new users)

> **Important:** Plans should never be deleted — deactivate them instead to preserve audit trails. The delete button is intentionally disabled.

### Plan Upgrade/Downgrade Logic

- **Upgrade** (e.g., Free → Pro): Immediate. Credits granted as upgrade bonus. `plan_valid_until` = now + 30 days.
- **Downgrade** (e.g., Pro → Free): Deferred. Sets `pending_plan`. User stays on current plan until `plan_valid_until` expires.
- **Same plan**: No changes.

---

## 5. Managing Users & Profiles

### User Profiles (Admin → Accounts → User Profiles)

Each Django User has a one-to-one `UserProfile` with:
- **plan** — Current subscription plan (FK to Plan)
- **plan_valid_until** — Billing cycle end date
- **pending_plan** — Scheduled downgrade plan (applied when cycle ends)
- **country_code / mobile_number** — Phone info
- **auth_provider** — `email` or `google` (how they signed up)
- **avatar_url** — Profile picture (from Google or uploaded)
- **is_email_verified** — Whether email verification completed
- **Consent flags** — `agreed_to_terms`, `agreed_to_data_usage`, `marketing_opt_in`
- **Social links** — `website_url`, `github_url`, `linkedin_url`

### User Lifecycle

1. User registers (email or Google OAuth) → UserProfile, NotificationPreference, and Wallet auto-created
2. Free plan assigned by default (with initial credits)
3. Email verification link sent
4. User can upgrade to Pro via Razorpay

### Account Deletion

Users can delete their account via `DELETE /api/v1/auth/me/`. This cascade-deletes all associated data (analyses, resumes, wallet, etc.).

### Consent Logs (Admin → Accounts → Consent Logs)

Immutable GDPR audit trail. Every consent agreement/withdrawal is logged with:
- Consent type (terms, data usage, marketing)
- Whether they agreed or withdrew
- Version of the legal document
- IP address, user agent, timestamp

---

## 6. Credit System & Wallets

### How Credits Work

Every AI-powered action costs credits:

| Action | Default Cost | Config Key |
|--------|-------------|------------|
| Resume Analysis | 1 credit | `resume_analysis` |
| Resume Generation (improved PDF/DOCX) | 1 credit | `resume_generation` |
| Job Alert Manual Run | 1 credit | `job_alert_run` |
| Interview Prep Generation | 1 credit | `interview_prep` |
| Cover Letter Generation | 1 credit | `cover_letter` |
| Resume Builder (finalize) | 2 credits | `resume_builder` |

### Managing Credit Costs (Admin → Accounts → Credit Costs)

Each action's cost is stored in the `CreditCost` table. Change costs **without code deploys**:

1. Go to **Credit Costs** in admin
2. Find the action slug (e.g., `resume_analysis`)
3. Change the `cost` field
4. Save — takes effect immediately

**Seed defaults:** `python manage.py seed_credit_costs`

### Wallets (Admin → Accounts → Wallets)

Each user has one wallet with a `balance` field. View/search by username.

### Wallet Transactions (Admin → Accounts → Wallet Transactions)

Immutable audit log. Every credit change creates a transaction:

| Type | Description |
|------|-------------|
| `plan_credit` | Monthly plan credit grant |
| `topup` | Top-up purchase |
| `analysis_debit` | Credit deduction for an action |
| `refund` | Credit refund (failed analysis, cancelled) |
| `admin_adjustment` | Manual admin adjustment |
| `upgrade_bonus` | Credits granted on plan upgrade |

**Key guarantees:**
- Atomic with `select_for_update()` — no race conditions
- Balance never goes negative
- Failed analyses auto-refund credits
- Cancelled analyses auto-refund credits

---

## 7. Razorpay Payment Management

### Payment Records (Admin → Accounts → Razorpay Payments)

Tracks every Razorpay payment attempt:
- **payment_type**: `subscription` or `topup`
- **status**: `created` → `authorized` → `captured` → (or `failed`/`refunded`)
- **amount**: In paise (₹499 = 49900)
- **credits_granted**: Boolean — whether plan/credits have been applied
- **webhook_verified**: Whether confirmed via webhook

### Subscriptions (Admin → Accounts → Razorpay Subscriptions)

Tracks subscription lifecycle:
- **status**: `created` → `authenticated` → `active` → `cancelled`/`expired`
- Each user can have at most one active subscription
- Historical subscriptions preserved for audit

### Webhook Events (Admin → Accounts → Webhook Events)

Deduplication log for Razorpay webhooks. Each processed `event_id` is stored to prevent replay attacks.

### Payment Flow

```
User clicks "Subscribe" → Frontend opens Razorpay Checkout
→ User completes payment → Frontend calls verify endpoint
→ Backend verifies signature → Activates plan + grants credits
→ Webhook confirms asynchronously (idempotent backup)
```

### Webhook Setup (Razorpay Dashboard)

1. Go to Razorpay Dashboard → Webhooks
2. Add webhook URL: `https://<backend>.up.railway.app/api/v1/auth/payments/webhook/`
3. Select events: `subscription.activated`, `subscription.charged`, `subscription.cancelled`, `subscription.halted`, `payment.captured`, `payment.failed`
4. Set webhook secret → update `RAZORPAY_WEBHOOK_SECRET` env var

---

## 8. Email Templates

### Managing Templates (Admin → Accounts → Email Templates)

Templates use Django template syntax for variable substitution. Each template has:
- **slug** — Code identifier (referenced in Python code)
- **category** — `auth`, `notification`, `marketing`, `system`
- **subject** — Email subject (supports `{{ variables }}`)
- **html_body** — HTML email body
- **plain_text_body** — Auto-generated from HTML if left blank
- **is_active** — Inactive templates cannot be sent

### Default Templates

Seeded by `python manage.py seed_email_templates`:

| Slug | Category | When Sent |
|------|----------|-----------|
| `welcome` | auth | After email verification succeeds |
| `email-verification` | auth | On registration (with verification link) |
| `password-reset` | auth | When user requests password reset |
| `analysis-complete` | notification | When analysis finishes (respects notification preferences) |

### Available Template Variables

| Variable | Available In |
|----------|-------------|
| `{{ username }}` | All templates |
| `{{ app_name }}` | All templates (defaults to "i-Luffy") |
| `{{ frontend_url }}` | All templates |
| `{{ support_email }}` | All templates |
| `{{ verify_url }}` | email-verification |
| `{{ reset_link }}` | password-reset |
| `{{ analysis_id }}`, `{{ jd_role }}`, `{{ overall_grade }}`, `{{ ats_score }}` | analysis-complete |

### Security

Templates are rendered with a **sandboxed engine** — `{% load %}`, `{% include %}`, `{% url %}`, and other potentially dangerous template tags are disabled. Only variable substitution (`{{ var }}`) and basic filters work.

---

## 9. Resume Templates (Marketplace)

### Managing Templates (Admin → Analyzer → Resume Templates)

Resume templates control the look of generated resumes/cover letters:

| Field | Description |
|-------|-------------|
| **name** | Display name (e.g., "ATS Classic") |
| **slug** | Code identifier used in API (e.g., `ats_classic`) |
| **category** | `professional`, `creative`, `academic`, `executive` |
| **preview_image** | Thumbnail shown in template picker |
| **is_premium** | Requires paid plan with `premium_templates` enabled |
| **is_active** | Hidden from marketplace if inactive |
| **sort_order** | Display ordering (lower = first) |

### Available Templates

Each template has a corresponding PDF and DOCX renderer in `analyzer/services/`:
- `ats_classic` — ATS-optimized professional
- `modern` / `modern_clean` — Modern two-column design
- `creative` — Bold creative layout
- `minimal` — Clean minimalist
- `executive` — Executive/leadership style

### Adding New Templates

1. Create PDF renderer: `analyzer/services/resume_<slug>_pdf.py`
2. Create DOCX renderer: `analyzer/services/resume_<slug>_docx.py`
3. Register in `analyzer/services/template_registry.py`
4. Add metadata via Django Admin (name, slug, category, preview)

---

## 10. Job Alert System & Crawl Sources

### Crawl Sources (Admin → Analyzer → Crawl Sources)

Admin-managed list of job boards/career pages that the daily crawl scrapes:

| Field | Description |
|-------|-------------|
| **name** | Display name (e.g., "LinkedIn", "Google Careers") |
| **source_type** | `job_board` (uses URL template with `{query}/{location}`) or `company` (static URL) |
| **url_template** | URL with `{query}` and `{location}` placeholders |
| **is_active** | Inactive sources skipped during crawl |
| **priority** | Lower number = crawled first |
| **last_crawled_at** | Timestamp of last successful crawl |

### Job Alert Pipeline

1. User creates a job alert linked to a specific resume
2. System extracts a **Job Search Profile** from the resume via LLM (titles, skills, seniority, industries)
3. Daily/weekly: Firecrawl scrapes job boards using search profile as queries
4. LLM scores discovered jobs for relevance (0-100)
5. Matching jobs (above threshold) create `JobMatch` records
6. User is notified via email and in-app notification
7. User provides feedback (relevant/irrelevant/applied/dismissed)

### Job Alert Runs (Admin → Analyzer → Job Alert Runs)

Audit log of each crawl+match pipeline execution:
- Jobs discovered, jobs matched, credits used
- Notification sent status
- Duration and any errors

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `JOB_MATCH_THRESHOLD` | 0.60 | Minimum relevance score for a match |
| `MAX_CRAWL_JOBS_PER_RUN` | 200 | Cap on jobs scraped per run |

---

## 11. Monitoring Analyses & LLM Usage

### Resume Analyses (Admin → Analyzer → Resume Analyses)

View all analyses including soft-deleted ones:
- Filter by status (`pending`, `processing`, `done`, `failed`)
- Filter by JD input type (`text`, `url`, `form`)
- Filter by AI provider used
- Filter by deleted status
- Search by username, job role, company

### LLM Responses (Admin → Analyzer → LLM Responses)

Every AI call is logged with:
- **model_used** — Which LLM model (e.g., `anthropic/claude-3.5-haiku`)
- **call_purpose** — `analysis`, `resume_rewrite`, `job_matching`, `profile_extraction`, `job_extraction`, `interview_prep`, `cover_letter`
- **Token counts** — `prompt_tokens`, `completion_tokens`, `total_tokens`
- **estimated_cost_usd** — Approximate cost based on known model pricing
- **duration_seconds** — How long the LLM call took
- **status** — `pending`, `done`, `failed`

Use this to:
- Monitor AI spending
- Identify slow/failing models
- Audit prompt content if needed

### Scrape Results (Admin → Analyzer → Scrape Results)

Logs of all Firecrawl web scraping operations (JD URLs and job board crawls).

---

## 12. Celery Task Monitoring

### API Endpoints (Admin-Only)

These require `is_staff=True` (superuser/admin):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/admin/celery/workers/` | GET | Active workers, stats, uptime |
| `/api/v1/admin/celery/tasks/active/` | GET | Currently executing tasks |
| `/api/v1/admin/celery/tasks/<task_id>/` | GET | Status of a specific task |
| `/api/v1/admin/celery/queues/` | GET | Queue lengths (requires Redis) |

### Flower Dashboard (Optional)

Deploy as a separate Railway service with `SERVICE_TYPE=flower`:
- Access via configured `FLOWER_USER`/`FLOWER_PASSWORD`
- Real-time task monitoring, worker control, graphs

---

## 13. Notifications Management

### In-App Notifications (Admin → Analyzer → Notifications)

View/manage all user notifications:
- Types: `job_match`, `analysis_done`, `resume_generated`, `system`
- Filter by read/unread status
- Contains metadata for deep-linking

### Notification Preferences (Admin → Accounts → Notification Preferences)

Per-user toggles for email/mobile notifications:
- Job Alerts
- Feature Updates
- Newsletters
- Policy Changes

### Contact Submissions (Admin → Accounts → Contact Submissions)

Landing page contact form entries. Review and respond manually.

---

## 14. Health Checks & Observability

### Health Check Endpoint

```
GET /api/v1/health/
```

Returns JSON with status of:
- **database** — PostgreSQL connectivity
- **cache** — Redis connectivity
- **celery** — Worker availability

Returns 200 if database + cache are OK, 503 otherwise. Used by Railway's health checker.

### Prometheus Metrics

Scraped at `/metrics` (django_prometheus):

| Metric | Type | Description |
|--------|------|-------------|
| `resume_ai_analysis_duration_seconds` | Histogram | End-to-end analysis time |
| `resume_ai_active_analyses` | Gauge | Currently processing analyses |
| `resume_ai_analysis_total` | Counter | Total analyses by status |
| `resume_ai_llm_tokens_total` | Counter | Token usage by provider |
| `resume_ai_credit_operations_total` | Counter | Credit ops by type |
| `resume_ai_credit_amount_total` | Counter | Credit amounts by type |
| `resume_ai_payment_failures_total` | Counter | Payment failures by reason |

### Logging

| Environment | Format | Output |
|-------------|--------|--------|
| Production | JSON (structured) | stdout → Railway log aggregation |
| Development | Human-readable | stdout + `logs/django.log` (rotating 10MB × 5) |

Logger names: `analyzer`, `accounts`, `django`, `django.request`

---

## 15. Environment Variables Reference

### Required (Production)

| Variable | Example | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `<secure random>` | Django secret key — **must change from default** |
| `DEBUG` | `False` | Must be False in production |
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection URL |
| `REDIS_URL` | `redis://...` | Redis for cache + Celery broker |
| `OPENROUTER_API_KEY` | `sk-or-v1-...` | OpenRouter API key for LLM calls |
| `CORS_ALLOWED_ORIGINS` | `https://app.example.com` | Frontend URL(s), comma-separated |
| `FRONTEND_URL` | `https://app.example.com` | Used in email links |

### Razorpay (Required for Payments)

| Variable | Description |
|----------|-------------|
| `RAZORPAY_KEY_ID` | Razorpay API key ID |
| `RAZORPAY_KEY_SECRET` | Razorpay API key secret |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook verification secret |

### File Storage (R2)

| Variable | Description |
|----------|-------------|
| `AWS_STORAGE_BUCKET_NAME` | R2 bucket name |
| `AWS_ACCESS_KEY_ID` | R2 access key |
| `AWS_SECRET_ACCESS_KEY` | R2 secret key |
| `AWS_S3_ENDPOINT_URL` | R2 endpoint (`https://<account>.r2.cloudflarestorage.com`) |

### Email

| Variable | Default | Description |
|----------|---------|-------------|
| `EMAIL_BACKEND` | console (dev) | Use `django.core.mail.backends.smtp.EmailBackend` for production |
| `EMAIL_HOST` | `smtp.gmail.com` | SMTP host |
| `EMAIL_PORT` | `587` | SMTP port |
| `EMAIL_HOST_USER` | — | SMTP username |
| `EMAIL_HOST_PASSWORD` | — | SMTP password (app-specific password for Gmail) |
| `DEFAULT_FROM_EMAIL` | `noreply@resumeai.app` | Sender address |

### Optional Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-haiku` | The LLM model to use |
| `AI_MAX_TOKENS` | `4096` | Max tokens for LLM responses |
| `MAX_PDF_PAGES` | `50` | Max resume pages accepted |
| `MAX_RESUME_SIZE_MB` | `5` | Max resume file size |
| `JD_FETCH_TIMEOUT` | `10` | JD URL fetch timeout (seconds) |
| `JOB_MATCH_THRESHOLD` | `0.60` | Minimum job relevance score |
| `GUNICORN_WORKERS` | `2` | Gunicorn worker processes |
| `GUNICORN_THREADS` | `2` | Gunicorn threads per worker |
| `CELERY_CONCURRENCY` | `2` | Celery worker concurrency |
| `GOOGLE_OAUTH2_CLIENT_ID` | — | For Google sign-in |

### Rate Limiting

| Variable | Default |
|----------|---------|
| `ANON_THROTTLE_RATE` | `60/hour` |
| `USER_THROTTLE_RATE` | `200/hour` |
| `ANALYZE_THROTTLE_RATE` | `10/hour` |
| `READONLY_THROTTLE_RATE` | `120/hour` |
| `WRITE_THROTTLE_RATE` | `60/hour` |
| `PAYMENT_THROTTLE_RATE` | `30/hour` |
| `AUTH_THROTTLE_RATE` | `20/hour` |

---

## 16. Management Commands

Run via `python manage.py <command>`:

| Command | Description |
|---------|-------------|
| `seed_plans` | Create/update Free and Pro plans with default configurations |
| `seed_email_templates` | Create/update default email templates |
| `seed_credit_costs` | Seed CreditCost rows with default values |
| `sync_razorpay_plans` | Force-sync all paid plans with Razorpay API |
| `createsuperuser` | Create admin user |
| `migrate` | Apply database migrations |
| `collectstatic` | Gather static files for WhiteNoise |

---

## 17. Periodic Tasks (Celery Beat)

Celery Beat runs these tasks automatically:

| Task | Schedule | Description |
|------|----------|-------------|
| `cleanup_stale_analyses` | Every 15 minutes | Mark analyses stuck in "processing" for 30+ min as failed; refund credits |
| `flush_expired_tokens` | Daily | Purge expired JWT blacklist entries |
| `send_weekly_digest_task` | Monday 9 AM UTC | Send weekly digest email to users |
| Crawl jobs (if configured) | Daily | Managed via Django Admin → Periodic Tasks (django_celery_beat) |

---

## 18. Backup & Recovery

### Database Backups

```bash
# Dump database (PostgreSQL)
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql

# Restore
psql $DATABASE_URL < backup_20260301.sql
```

Existing backups are stored in `backups/` directory.

### File Storage

Resume files and generated documents are stored in Cloudflare R2. R2 provides built-in redundancy. For additional safety, enable R2 versioning in the Cloudflare dashboard.

---

## 19. Security Checklist

- [ ] `SECRET_KEY` is a unique, unpredictable value (not the default)
- [ ] `DEBUG=False` in production
- [ ] Razorpay keys are real (not placeholders)
- [ ] `CORS_ALLOWED_ORIGINS` lists only your frontend domain(s)
- [ ] HTTPS enforced (Railway handles SSL termination)
- [ ] HSTS enabled (1 year, include subdomains, preload)
- [ ] `X-Frame-Options: DENY` to prevent clickjacking
- [ ] `X-Content-Type-Options: nosniff` enabled
- [ ] JWT refresh tokens rotated on use with blacklisting
- [ ] Webhook signature verification active for Razorpay
- [ ] Rate limiting configured on all endpoints
- [ ] Email templates use sandboxed rendering (no `{% load %}`)
- [ ] File uploads restricted to PDF, max 5MB
- [ ] Soft-delete preserves audit trails (no hard deletes for analyses)

---

## 20. Troubleshooting

### Analyses Stuck in "Processing"

The `cleanup_stale_analyses` periodic task auto-marks these as failed after 30 minutes and refunds credits. You can also:
1. Check Celery worker status: `GET /api/v1/admin/celery/workers/`
2. Check the specific task: `GET /api/v1/admin/celery/tasks/<task_id>/`
3. Manually cancel via API or admin panel

### Razorpay Plan Sync Failed

1. Check logs for the error message
2. Verify Razorpay API keys are correct
3. Use Admin → Plans → Actions → "Sync with Razorpay"
4. Or run: `python manage.py sync_razorpay_plans`

### Webhook Not Receiving Events

1. Check Razorpay Dashboard → Webhooks → Event deliveries
2. Verify the webhook URL is correct and publicly accessible
3. Check `RAZORPAY_WEBHOOK_SECRET` matches the dashboard
4. Review Webhook Events in admin for duplicate detection

### Users Not Receiving Emails

1. Check `EMAIL_BACKEND` is set to SMTP (not console)
2. Verify SMTP credentials
3. Check the email template exists and is active
4. Check user's notification preferences
5. Look for errors in the `accounts` logger output

### LLM Calls Failing

1. Check `OPENROUTER_API_KEY` is valid and has credits
2. Check LLM Responses in admin for error messages
3. Try a different model via `OPENROUTER_MODEL`
4. Check OpenRouter status page for outages

### Health Check Returning 503

1. **database: error** — Check PostgreSQL connection, `DATABASE_URL`
2. **cache: error** — Check Redis connection, `REDIS_URL`
3. **celery: unavailable** — Check worker service is running

---

*This guide covers the complete admin operational surface of the i-Luffy platform. For API documentation, see `FRONTEND_API_GUIDE.md`. For architecture details, see `ARCHITECTURE_FLOW.md`.*
