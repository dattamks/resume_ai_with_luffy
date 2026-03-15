# Product Requirements Document (PRD)

## Resume AI (i-Luffy) — AI-Powered Resume Analysis & Career Platform

**Version:** 1.0
**Date:** 2026-03-15
**Status:** In Production (Railway)

---

## 1. Product Overview

### 1.1 Vision

Resume AI (i-Luffy) is an AI-powered career platform that helps job seekers optimize their resumes, discover relevant job opportunities, and prepare for interviews — all from a single application.

### 1.2 Problem Statement

Job seekers face multiple disconnected challenges:
- Resumes are rejected by ATS (Applicant Tracking Systems) before a human ever reads them
- No easy way to tailor resumes to specific job descriptions
- Job discovery is fragmented across multiple platforms
- Interview preparation lacks personalization to the target role
- Cover letters are tedious to write from scratch

### 1.3 Solution

A unified platform that:
1. Analyzes resumes against job descriptions using AI, producing actionable ATS scores and improvement suggestions
2. Generates optimized resumes in multiple professional templates
3. Crawls and matches jobs from multiple sources using embedding-based semantic matching
4. Generates personalized interview prep materials and cover letters
5. Provides a conversational resume builder for creating resumes from scratch

### 1.4 Target Users

- **Primary:** Active job seekers (entry-level to mid-career professionals)
- **Secondary:** Career changers, students entering the workforce
- **Geography:** India-first (Razorpay payments, INR pricing), expanding internationally

---

## 2. Architecture Overview

### 2.1 Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend Framework | Django 5.x + Django REST Framework |
| Authentication | JWT (SimpleJWT) with token rotation & blacklisting |
| Task Queue | Celery + Redis (broker & result backend) |
| Database | PostgreSQL (Railway) + pgvector for embeddings |
| File Storage | Cloudflare R2 (S3-compatible) |
| AI Provider | OpenRouter (Claude 3.5 Haiku default) |
| Job Scraping | Firecrawl API |
| Payments | Razorpay (subscriptions + one-time orders) |
| Monitoring | Prometheus metrics, structured JSON logging |
| Deployment | Railway (web + worker + beat services) |
| Frontend | Separate SPA (Cloudflare Pages), communicates via REST API |
| Mobile | React Native / Expo (in development) |

### 2.2 Service Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Frontend    │     │ Crawler Bot │     │   Mobile    │
│  (SPA)       │     │ (External)  │     │   (Expo)    │
└──────┬───────┘     └──────┬───────┘     └──────┬──────┘
       │                    │                     │
       │ JWT Auth           │ X-Crawler-Key       │ JWT Auth
       ▼                    ▼                     ▼
┌──────────────────────────────────────────────────────────┐
│                    Django API Server                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ accounts │  │ analyzer │  │ ingest   │  │ health   │ │
│  │ (auth,   │  │ (resume  │  │ (crawler │  │ (status, │ │
│  │  billing)│  │  analysis)│  │  API)    │  │  metrics)│ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │
└──────────────────────┬───────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐   ┌──────────┐   ┌──────────┐
   │PostgreSQL│   │  Redis   │   │Cloudflare│
   │+pgvector │   │(cache,   │   │ R2       │
   │          │   │ broker)  │   │(files)   │
   └──────────┘   └──────────┘   └──────────┘
```

---

## 3. Feature Specifications

### 3.1 User Accounts & Authentication

#### 3.1.1 Registration
- Email + password registration with Django password validation
- Username validation (3-30 chars, alphanumeric + underscore, reserved names blocked)
- Required consent checkboxes: Terms of Service, Data Usage Policy
- Optional marketing opt-in
- Email verification via tokenized link (24-hour expiry)
- Consent audit trail (immutable `ConsentLog` model)

#### 3.1.2 Authentication
- JWT-based with 1-hour access tokens and 7-day refresh tokens
- Token rotation on refresh (old refresh token blacklisted)
- Google OAuth2 (ID token + authorization code flows)
- Two-step Google sign-up: verify token → complete registration with username/password/consent
- Login activity tracking (`UserActivity` model)

#### 3.1.3 Account Management
- View/update profile (username, email, name, phone, location, social links)
- Avatar upload (JPEG/PNG/WebP, max 2 MB, stored in R2)
- Change password (invalidates all existing JWT sessions)
- Forgot/reset password via email link
- Delete account (cascading deletion, subscription cancellation, token blacklisting)
- Logout / logout all devices (bulk token blacklisting)
- Notification preferences (per-category email/mobile toggles)

### 3.2 Subscription Plans & Billing

#### 3.2.1 Plan Tiers
- **Free:** Limited analyses/month, basic features, 5 stored resumes
- **Pro:** Higher quotas, premium templates, job alerts, email support, credit top-ups
- Plans are admin-managed (`Plan` model with ~25 configurable fields)

#### 3.2.2 Credit System
- Actions cost credits (configurable via `CreditCost` admin model)
- Monthly credit grants with balance cap (prevents hoarding)
- Credits deducted upfront, refunded on failure
- Atomic transactions with `select_for_update()` (no race conditions)
- Immutable wallet transaction audit log

#### 3.2.3 Payments (Razorpay)
- **Subscriptions:** Razorpay subscription API for recurring Pro billing
- **Top-ups:** One-time Razorpay orders for credit packs
- Signature-based payment verification (HMAC-SHA256)
- Webhook processing with replay protection (`WebhookEvent` deduplication)
- Idempotent credit provisioning (prevents double-grant)
- Payment history with pagination

#### 3.2.4 Plan Transitions
- Upgrade: Immediate plan switch + bonus credits
- Downgrade: Scheduled at end of billing cycle (`pending_plan`)
- Expired plan processing via periodic Celery task

### 3.3 Resume Analysis (Core Feature)

#### 3.3.1 Input
- Upload PDF resume (validated: magic bytes, page count, file size per plan)
- Job description via three input modes:
  - **URL:** Scraped via Firecrawl with SSRF protection and caching
  - **Text:** Raw job description pasted by user
  - **Form:** Structured fields (role, company, skills, experience, industry)

#### 3.3.2 Processing Pipeline
Four-step resumable pipeline with crash recovery:
1. **PDF Extract** — Text extraction via pdfplumber
2. **JD Scrape** — Fetch/resolve job description
3. **LLM Call** — Send resume + JD to AI provider, get structured analysis
4. **Parse Result** — Extract scores, feedback, suggestions from LLM response

Each step commits to DB before proceeding (can resume from any point).

#### 3.3.3 Output
- Overall grade (A/B/C/D/F)
- ATS compatibility score (0-100)
- Detailed scores: keyword match, skills alignment, formatting, experience fit
- Section-by-section feedback
- Sentence-level improvement suggestions
- Quick wins (highest-impact changes)
- Keyword analysis (present/missing)
- ATS disclaimers
- Job metadata extraction (title, company, skills, experience, industry)

#### 3.3.4 Features
- Retry failed analyses (free for system faults, costs credits for user-error retries)
- Share analysis via public token link
- Dashboard statistics (aggregated scores, trends, monthly analysis counts)
- Resume deduplication via file hash
- Concurrent submission prevention (idempotency lock)
- Token usage tracking and cost estimation per analysis

### 3.4 Resume Generation

#### 3.4.1 AI-Powered Generation
- Generate improved resume from analysis results + original resume
- Multiple output formats: PDF, DOCX
- Multiple templates: ATS Classic, Modern, Creative, Executive, Minimal, Modern Luxe
- Template registry with premium/free gating
- Celery-based async rendering

#### 3.4.2 Conversational Resume Builder
- Chat-based interface for building resumes from scratch
- Two modes: Guided (step-by-step) and Text (free-form conversation)
- Sources: start from scratch, use existing resume as base, or import from analysis
- Session management (max 5 active sessions per user, 50 message limit)
- Credit deduction on finalize, refund on failure

#### 3.4.3 Resume Versioning
- Track versions of generated resumes
- Rename/organize generated resumes
- Soft-delete support on Resume model

### 3.5 Job Discovery & Matching

#### 3.5.1 Job Crawling
- External crawler bot ingests jobs via authenticated API (`X-Crawler-Key`)
- Supports: single + bulk ingest for companies, entities, career pages, jobs, news
- `CrawlSource` management (which URLs to crawl, scheduling)
- Job deduplication via `source` + `external_id`

#### 3.5.2 Semantic Job Matching
- pgvector-based embedding storage for job descriptions
- Embedding generation via OpenRouter (text-embedding-3-small)
- Configurable match threshold (default 0.60 cosine similarity)
- Batch processing of ingested jobs with debounced Celery tasks

#### 3.5.3 Job Alerts
- User-defined search profiles (role, skills, location preferences)
- Automatic matching when new jobs are ingested
- Email/mobile notification delivery (per notification preferences)
- Max alerts per plan (e.g., Pro = 5 alerts)
- Alert run history and match tracking

#### 3.5.4 Job Feed
- Personalized feed based on user's job search profiles
- Company following
- Job feedback (thumbs up/down) for improving match quality
- Country-based filtering

### 3.6 Interview Prep & Cover Letters

#### 3.6.1 Interview Preparation
- AI-generated interview questions based on resume + job description
- Personalized to the specific role and company
- Question bank model for accumulating practice questions
- Async generation via Celery

#### 3.6.2 Cover Letters
- AI-generated cover letters tailored to job + resume
- Based on analysis results for maximum relevance
- Async generation via Celery

### 3.7 Company Intelligence

#### 3.7.1 Company Profiles
- Company model with metadata (industry, size, headquarters, etc.)
- Company entities (regional offices, subsidiaries)
- Career pages tracking
- News snippet aggregation
- User company following/unfollowing

#### 3.7.2 Skill & Role Intelligence
- `Skill` model for taxonomy management
- `RoleFamily` for categorizing roles
- Skill enrichment service
- Aggregated skill demand analytics

### 3.8 Platform Features

#### 3.8.1 Monitoring & Observability
- Prometheus metrics (credit operations, API latency)
- Structured JSON logging in production
- Health check endpoints
- Admin digest emails (morning + night, IST-adjusted)
- Celery task health monitoring

#### 3.8.2 Rate Limiting
- Tiered throttle scopes: anon, user, analyze, readonly, write, payment, auth
- IP-based for anonymous, user-based for authenticated
- Rate limit headers in responses (X-RateLimit-Limit/Remaining/Reset)
- Configurable rates via environment variables

#### 3.8.3 Email System
- Template-based emails stored in DB (`EmailTemplate` model)
- Categories: auth, notification, marketing, system
- Django template syntax for variable substitution
- SMTP in production, console backend for development
- Weekly user digest, admin daily digest

---

## 4. Data Models Summary

### 4.1 Accounts App

| Model | Purpose |
|-------|---------|
| `UserProfile` | Extended user data (plan, consent, Google OAuth, geography) |
| `NotificationPreference` | Per-user notification toggles |
| `Plan` | Subscription tiers with quotas and feature flags |
| `Wallet` | Per-user credit balance |
| `WalletTransaction` | Immutable credit change audit log |
| `CreditCost` | Admin-configurable per-action credit costs |
| `RazorpayPayment` | Payment attempt tracking |
| `RazorpaySubscription` | Subscription lifecycle tracking |
| `ConsentLog` | Immutable consent audit trail |
| `EmailTemplate` | Reusable email templates |
| `EmailVerificationToken` | Short-lived verification tokens |
| `ContactSubmission` | Landing page contact form entries |
| `WebhookEvent` | Webhook replay protection |

### 4.2 Analyzer App

| Model | Purpose |
|-------|---------|
| `Resume` | Uploaded resume files with deduplication |
| `ResumeAnalysis` | Analysis results with resumable pipeline |
| `LLMResponse` | AI provider call tracking |
| `ScrapeResult` | JD URL scrape cache |
| `GeneratedResume` | AI-generated resume documents |
| `ResumeVersion` | Resume version tracking |
| `ResumeTemplate` | Template registry (free/premium) |
| `ResumeChat` / `ResumeChatMessage` | Conversational builder sessions |
| `DiscoveredJob` | Crawled job listings |
| `JobAlert` / `JobAlertRun` / `JobMatch` | Job matching system |
| `JobSearchProfile` | User job preferences |
| `Company` / `CompanyEntity` / `CompanyCareerPage` | Company data |
| `CrawlSource` | Job crawl configuration |
| `InterviewPrep` | Generated interview materials |
| `CoverLetter` | Generated cover letters |
| `UserActivity` | Activity tracking (streaks, engagement) |
| `Notification` | In-app notifications |
| `Skill` / `RoleFamily` | Taxonomy models |
| `NewsSnippet` | Company news aggregation |

---

## 5. API Structure

### 5.1 Authentication (`/api/v1/auth/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/register/` | POST | Public | Create account |
| `/login/` | POST | Public | Get JWT tokens |
| `/logout/` | POST | JWT | Blacklist refresh token |
| `/logout-all/` | POST | JWT | Blacklist all user tokens |
| `/me/` | GET/PUT/DELETE | JWT | Profile CRUD + account deletion |
| `/change-password/` | POST | JWT | Change password |
| `/forgot-password/` | POST | Public | Request password reset email |
| `/reset-password/` | POST | Public | Reset password with token |
| `/verify-email/` | POST | Public | Verify email token |
| `/resend-verification/` | POST | JWT | Resend verification email |
| `/google/` | POST | Public | Google OAuth login |
| `/google/complete/` | POST | Public | Complete Google sign-up |
| `/notifications/` | GET/PUT | JWT | Notification preferences |
| `/avatar/` | POST/DELETE | JWT | Avatar upload/remove |
| `/wallet/` | GET | JWT | Wallet balance |
| `/wallet/transactions/` | GET | JWT | Transaction history |
| `/wallet/transactions/export/` | GET | JWT | CSV export |
| `/plans/` | GET | Public | List available plans |
| `/plans/subscribe/` | POST | JWT | Subscribe to plan |
| `/contact/` | POST | Public | Contact form submission |

### 5.2 Payments (`/api/v1/payments/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/subscribe/` | POST | JWT | Create Razorpay subscription |
| `/subscribe/verify/` | POST | JWT | Verify subscription payment |
| `/subscribe/cancel/` | POST | JWT | Cancel subscription |
| `/subscribe/status/` | GET | JWT | Subscription status |
| `/topup/` | POST | JWT | Create top-up order |
| `/topup/verify/` | POST | JWT | Verify top-up payment |
| `/webhook/` | POST | Signature | Razorpay webhook |
| `/history/` | GET | JWT | Payment history |

### 5.3 Analysis (`/api/v1/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/analyze/` | POST | JWT | Submit resume for analysis |
| `/analyses/` | GET | JWT | List analyses |
| `/analyses/<id>/` | GET/DELETE | JWT | Analysis detail/delete |
| `/analyses/<id>/retry/` | POST | JWT | Retry failed analysis |
| `/analyses/<id>/share/` | POST | JWT | Generate share link |
| `/analyses/<id>/pdf/` | GET | JWT | Download PDF report |
| `/shared/<token>/` | GET | Public | View shared analysis |
| `/resumes/` | GET | JWT | List uploaded resumes |
| `/resumes/<id>/` | PATCH/DELETE | JWT | Rename/delete resume |
| `/dashboard/` | GET | JWT | Dashboard statistics |

### 5.4 Resume Generation (`/api/v1/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/generated-resumes/` | GET/POST | JWT | List/create generated resumes |
| `/generated-resumes/<id>/` | GET/DELETE | JWT | Detail/delete |
| `/generated-resumes/<id>/download/` | GET | JWT | Download file |
| `/templates/` | GET | JWT | List available templates |
| `/resume-chat/start/` | POST | JWT | Start builder session |
| `/resume-chat/` | GET | JWT | List sessions |
| `/resume-chat/<id>/` | GET/DELETE | JWT | Session detail/delete |
| `/resume-chat/<id>/submit/` | POST | JWT | Submit guided step |
| `/resume-chat/<id>/message/` | POST | JWT | Send text message |
| `/resume-chat/<id>/finalize/` | POST | JWT | Generate final resume |

### 5.5 Jobs & Alerts (`/api/v1/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/job-alerts/` | GET/POST | JWT | List/create job alerts |
| `/job-alerts/<id>/` | PUT/DELETE | JWT | Update/delete alert |
| `/job-alerts/<id>/runs/` | GET | JWT | Alert run history |
| `/job-matches/` | GET | JWT | List job matches |
| `/job-matches/<id>/feedback/` | POST | JWT | Submit match feedback |

### 5.6 Ingest API (`/api/v1/ingest/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/companies/` | GET/POST | API Key | List/upsert companies |
| `/companies/bulk/` | POST | API Key | Bulk upsert companies |
| `/entities/` | GET/POST | API Key | List/upsert entities |
| `/entities/bulk/` | POST | API Key | Bulk upsert entities |
| `/career-pages/` | POST | API Key | Upsert career page |
| `/jobs/` | POST | API Key | Upsert job |
| `/jobs/bulk/` | POST | API Key | Bulk upsert jobs (max 500) |
| `/crawl-sources/` | GET | API Key | List crawl sources |
| `/crawl-sources/<id>/` | PATCH | API Key | Update crawl source |
| `/news/` | POST | API Key | Upsert news snippet |
| `/news/bulk/` | POST | API Key | Bulk upsert news (max 200) |
| `/news/deactivate/` | POST | API Key | Deactivate news snippets |
| `/ping/` | GET | API Key | Auth health check |

---

## 6. Non-Functional Requirements

### 6.1 Performance
- API response time < 500ms for read endpoints
- Analysis pipeline < 60s end-to-end (depends on AI provider)
- Celery task timeout: 10 min hard limit, 9 min soft limit
- Database connection pooling (conn_max_age=600)
- Redis caching for throttle state, sessions, and JD scrape cache

### 6.2 Scalability
- Horizontal scaling via Railway replicas (stateless web servers)
- Celery workers scale independently
- Migration locking via `flock` prevents concurrent schema changes
- pgvector for efficient embedding similarity search

### 6.3 Security
- HTTPS enforced in production (HSTS 1 year)
- JWT with rotation and blacklisting
- CORS restricted to configured origins (no wildcard)
- SSRF protection on JD URL fetching
- Rate limiting on all endpoints (tiered by scope)
- Razorpay webhook signature verification
- HMAC-signed temporary tokens for Google OAuth flow
- Django password validators (similarity, minimum length, common, numeric)
- Content-Security-Policy via X-Frame-Options: DENY
- No CORS_ALLOW_CREDENTIALS (JWT header-based auth)
- Production secret key validation (rejects insecure default)

### 6.4 Reliability
- Resumable analysis pipeline (crash recovery from any step)
- Idempotent payment processing (webhook deduplication)
- Credit refund on analysis failure
- Atomic wallet operations (select_for_update)
- Stale analysis cleanup (Celery beat every 15 minutes)
- Expired token cleanup (daily)

### 6.5 Observability
- Structured JSON logging in production
- Prometheus metrics endpoint
- Rate limit headers in all responses
- Admin digest emails (2x daily)
- Celery task tracking (started, time limits)

---

## 7. Deployment

### 7.1 Railway Services

| Service | `SERVICE_TYPE` | Purpose |
|---------|---------------|---------|
| Web | `web` | Gunicorn WSGI server |
| Worker | `worker` | Celery task processing |
| Beat | `beat` | Periodic task scheduling |
| Flower | `flower` | Celery monitoring dashboard |

### 7.2 Environment Variables

31+ configuration variables covering:
- Django core (SECRET_KEY, DEBUG, ALLOWED_HOSTS)
- Database (DATABASE_URL)
- Redis (REDIS_URL)
- AI providers (OPENROUTER_API_KEY, model config)
- File storage (AWS_* for Cloudflare R2)
- Payments (RAZORPAY_KEY_ID, KEY_SECRET, WEBHOOK_SECRET)
- OAuth (GOOGLE_OAUTH2_CLIENT_ID, CLIENT_SECRET)
- Scraping (FIRECRAWL_API_KEY)
- Crawler (CRAWLER_API_KEY, CRAWLER_BOT_INGEST_URL)
- Email (SMTP config)
- Rate limits (per-scope throttle rates)
- Feature config (thresholds, limits)

### 7.3 Startup Sequence (Web)
1. Run migrations (with flock for concurrency safety)
2. Seed email templates
3. Seed subscription plans
4. Seed credit costs
5. Start Gunicorn

---

## 8. Known Limitations & Technical Debt

1. **No automated plan expiry enforcement at request time** — relies solely on periodic Celery task
2. **Single AI provider at a time** — factory pattern exists but only OpenRouter is implemented
3. **No WebSocket/SSE** — analysis progress polling via HTTP (no real-time updates)
4. **Email uniqueness not enforced at DB level** — Django's User model allows duplicate emails; enforced at serializer level only
5. **No file virus scanning** — uploaded PDFs are validated for format but not scanned for malware
6. **Job crawling depends on external Firecrawl API** — single point of failure for JD URL scraping
7. **Mobile app is in early development** — React Native / Expo shell exists but feature-incomplete
8. **No admin dashboard beyond Django Admin** — all admin operations require Django Admin access
9. **Dead code:** `topup_credits()` in services.py, unused AI provider references in .env.example

---

## 9. Future Roadmap (Inferred)

Based on codebase structure and TODO files:
1. Mobile app feature parity (React Native)
2. Additional AI providers (Claude direct, OpenAI direct — factory pattern ready)
3. Real-time analysis progress (WebSocket/SSE)
4. Multi-language resume support
5. Resume template marketplace
6. Company review integration
7. Salary insights
8. LinkedIn profile import
9. Bulk resume processing for recruiters
10. API access tier for enterprise customers
