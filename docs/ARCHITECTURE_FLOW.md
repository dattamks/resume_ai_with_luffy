# i-Luffy — Architecture & Flow Document

> **Last updated:** 2026-03-01 &nbsp;|&nbsp; **Platform version:** v0.27.0
> Deep technical reference describing how every component connects, what happens at every stage, and what systems are involved.

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [System Components](#2-system-components)
3. [Django Project Structure](#3-django-project-structure)
4. [Authentication & Authorization Flow](#4-authentication--authorization-flow)
5. [Resume Analysis Pipeline (Core)](#5-resume-analysis-pipeline-core)
6. [Resume Generation Pipeline](#6-resume-generation-pipeline)
7. [Conversational Resume Builder Flow](#7-conversational-resume-builder-flow)
8. [Interview Prep Generation Flow](#8-interview-prep-generation-flow)
9. [Cover Letter Generation Flow](#9-cover-letter-generation-flow)
10. [Smart Job Alert Pipeline](#10-smart-job-alert-pipeline)
11. [Payment & Subscription Flow](#11-payment--subscription-flow)
12. [Credit System Flow](#12-credit-system-flow)
13. [Notification System](#13-notification-system)
14. [Email System](#14-email-system)
15. [File Storage Flow](#15-file-storage-flow)
16. [Caching Strategy](#16-caching-strategy)
17. [Rate Limiting Architecture](#17-rate-limiting-architecture)
18. [Data Models & Relationships](#18-data-models--relationships)
19. [Celery Task Architecture](#19-celery-task-architecture)
20. [Observability Stack](#20-observability-stack)
21. [Security Architecture](#21-security-architecture)
22. [API Versioning & URL Structure](#22-api-versioning--url-structure)
23. [Deployment Pipeline](#23-deployment-pipeline)

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENTS                                        │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                     │
│  │ React (Vite) │   │ React Native │   │   API Tools  │                     │
│  │  Web SPA     │   │  Mobile App  │   │  (Postman)   │                     │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                     │
└─────────┼──────────────────┼──────────────────┼─────────────────────────────┘
          │ HTTPS            │ HTTPS            │ HTTPS
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RAILWAY PLATFORM                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        WEB SERVICE                                  │    │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────┐                │    │
│  │  │  Gunicorn   │→│ Django/DRF   │→│   Business   │                │    │
│  │  │  (WSGI)     │  │  Views +     │  │   Logic      │                │    │
│  │  │             │  │  Serializers │  │ (Services)   │                │    │
│  │  └────────────┘  └──────────────┘  └──────┬───────┘                │    │
│  │                                           │                         │    │
│  │         ┌─────────────────────────────────┼──────────────────┐      │    │
│  │         │              MIDDLEWARE          │                  │      │    │
│  │         │  Prometheus ← CORS ← Security ← RateLimit Headers │      │    │
│  │         └─────────────────────────────────┼──────────────────┘      │    │
│  └───────────────────────────────────────────┼─────────────────────────┘    │
│                                              │                              │
│  ┌────────────────┐  ┌────────────────┐      │                              │
│  │  CELERY WORKER │  │  CELERY BEAT   │      │                              │
│  │  (Async Tasks) │  │  (Scheduler)   │      │                              │
│  │                │  │                │      │                              │
│  │  • Analysis    │  │  • Stale       │      │                              │
│  │  • PDF Gen     │  │    cleanup     │      │                              │
│  │  • Resume Gen  │  │  • Token flush │      │                              │
│  │  • Job Crawl   │  │  • Weekly      │      │                              │
│  │  • Interview   │  │    digest      │      │                              │
│  │  • Cover Letter│  │  • Job crawl   │      │                              │
│  └───────┬────────┘  └───────┬────────┘      │                              │
│          │                   │               │                              │
│          ▼                   ▼               ▼                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     INFRASTRUCTURE                                  │    │
│  │                                                                     │    │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │    │
│  │  │  PostgreSQL   │    │    Redis      │    │  Cloudflare  │          │    │
│  │  │  (Database)   │    │  (Cache +     │    │     R2       │          │    │
│  │  │              │    │   Broker)     │    │ (File Store) │          │    │
│  │  └──────────────┘    └──────────────┘    └──────────────┘          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────┐
│   OpenRouter     │ │   Razorpay   │ │  Firecrawl   │
│   (LLM API)     │ │  (Payments)  │ │  (Scraping)  │
│                  │ │              │ │              │
│  Claude 3.5      │ │ Subscriptions│ │ Job boards   │
│  GPT-4o          │ │ One-time     │ │ Career pages │
│  Gemini          │ │ Webhooks     │ │              │
└──────────────────┘ └──────────────┘ └──────────────┘
```

---

## 2. System Components

### Django Apps

| App | Responsibility |
|-----|---------------|
| **`accounts`** | User management, auth, profiles, plans, wallets, credits, payments, email templates, consent logging |
| **`analyzer`** | Resume analysis, generation, job alerts, notifications, interview prep, cover letters, chat builder, templates, Celery tasks |
| **`resume_ai`** | Project configuration (settings, URLs, WSGI, Celery app, middleware, Prometheus metrics) |

### External Services

| Service | Used For | Called By |
|---------|----------|-----------|
| **OpenRouter** | LLM API calls (analysis, rewriting, job matching, interview prep, cover letters) | `analyzer/services/ai_providers/` |
| **Razorpay** | Payment processing (subscriptions + one-time top-ups) | `accounts/razorpay_service.py` |
| **Firecrawl** | Web scraping (JD URLs + job board crawling) | `analyzer/services/jd_fetcher.py`, `analyzer/services/job_sources/` |
| **SMTP** | Email delivery | `accounts/email_utils.py` |
| **Cloudflare R2** | File storage (via S3-compatible API) | Django `storages` backend |

---

## 3. Django Project Structure

```
resume_ai_with_luffy/
├── resume_ai/                 # Project config
│   ├── settings.py            #   All configuration (DB, cache, Celery, CORS, security, etc.)
│   ├── urls.py                #   Root URL routing → admin, health, accounts, analyzer
│   ├── celery.py              #   Celery app configuration
│   ├── wsgi.py                #   WSGI entry point (Gunicorn)
│   ├── middleware.py           #   RateLimitHeadersMiddleware
│   └── metrics.py             #   Prometheus metric definitions
│
├── accounts/                  # User & payment management
│   ├── models.py              #   UserProfile, Plan, Wallet, WalletTransaction, CreditCost,
│   │                          #   NotificationPreference, EmailTemplate, ConsentLog,
│   │                          #   RazorpayPayment, RazorpaySubscription, WebhookEvent,
│   │                          #   ContactSubmission, EmailVerificationToken
│   ├── views.py               #   Auth views (register, login, logout, me, password, Google OAuth,
│   │                          #   email verification, wallet, plans, avatar, contact)
│   ├── views_payments.py      #   Razorpay payment views (subscribe, verify, cancel, topup, webhook)
│   ├── serializers.py         #   DRF serializers for all account models
│   ├── services.py            #   Credit/wallet business logic (deduct, refund, add, topup, subscribe)
│   ├── razorpay_service.py    #   Razorpay API integration (subscriptions, orders, webhooks)
│   ├── email_utils.py         #   Templated email sending (sandboxed rendering)
│   ├── throttles.py           #   Custom throttle classes with rate-limit header injection
│   ├── urls.py                #   URL routing for /api/v1/auth/* endpoints
│   ├── admin.py               #   Django admin configuration for all account models
│   └── management/commands/   #   seed_plans, seed_email_templates, seed_credit_costs, sync_razorpay_plans
│
├── analyzer/                  # Resume analysis & features
│   ├── models.py              #   Resume, ResumeAnalysis, ScrapeResult, LLMResponse,
│   │                          #   GeneratedResume, JobSearchProfile, JobAlert, DiscoveredJob,
│   │                          #   JobMatch, JobAlertRun, CrawlSource, SentAlert, Notification,
│   │                          #   ResumeVersion, InterviewPrep, CoverLetter, ResumeTemplate,
│   │                          #   ResumeChat, ResumeChatMessage
│   ├── views.py               #   All analyzer API views (analyze, analyses, resumes, dashboard,
│   │                          #   share, generate, job alerts, notifications, version history,
│   │                          #   bulk analysis, interview prep, cover letter, templates)
│   ├── views_chat.py          #   Conversational resume builder views
│   ├── views_celery.py        #   Admin-only Celery monitoring views
│   ├── views_health.py        #   Health check endpoint
│   ├── serializers.py         #   DRF serializers for all analyzer models
│   ├── tasks.py               #   Celery tasks (analysis, PDF gen, resume gen, job crawl,
│   │                          #   interview prep, cover letter, cleanup, flush tokens)
│   ├── signals.py             #   File cleanup signals (post_delete for Resume, ResumeAnalysis)
│   ├── urls.py                #   URL routing for /api/v1/* analyzer endpoints
│   ├── admin.py               #   Django admin for all analyzer models
│   └── services/              #   Business logic modules:
│       ├── analyzer.py        #     ResumeAnalyzer — orchestrates the analysis pipeline
│       ├── pdf_extractor.py   #     PDF text extraction (pdfplumber)
│       ├── jd_fetcher.py      #     JD URL scraping (requests + BeautifulSoup + Firecrawl)
│       ├── resume_parser.py   #     Structured resume data extraction
│       ├── resume_generator.py#     LLM-based resume rewriting
│       ├── pdf_report.py      #     Analysis report PDF generation
│       ├── template_registry.py#    Resume template → renderer mapping
│       ├── resume_pdf_renderer.py # ATS Classic PDF renderer
│       ├── resume_docx_renderer.py# ATS Classic DOCX renderer
│       ├── resume_modern_*.py #     Modern template renderers
│       ├── resume_creative_*.py#    Creative template renderers
│       ├── resume_minimal_*.py #    Minimal template renderers
│       ├── resume_executive_*.py#   Executive template renderers
│       ├── resume_chat_service.py#  Conversational builder session logic
│       ├── interview_prep.py  #     Interview prep generation
│       ├── cover_letter.py    #     Cover letter generation
│       ├── job_search_profile.py#   Resume → job search profile extraction
│       ├── job_matcher.py     #     Job matching with relevance scoring
│       ├── embedding_service.py#    Text embedding generation
│       ├── embedding_matcher.py#    Vector similarity matching (pgvector)
│       └── ai_providers/      #     LLM provider abstraction:
│           ├── factory.py     #       get_ai_provider() → configured provider
│           └── openrouter_provider.py # OpenRouter API client
```

---

## 4. Authentication & Authorization Flow

### Registration Flow (Email)

```
Client                          Backend
  │                                │
  │  POST /api/v1/auth/register/   │
  │  {username, email, password,   │
  │   agree_to_terms, ...}         │
  │──────────────────────────────→│
  │                                │  1. Validate input (RegisterSerializer)
  │                                │  2. Create Django User
  │                                │  3. Auto-create: UserProfile (free plan),
  │                                │     NotificationPreference, Wallet (with initial credits)
  │                                │  4. Record ConssentLog entries (terms, data usage, marketing)
  │                                │  5. Generate JWT tokens (access + refresh)
  │                                │  6. Create EmailVerificationToken
  │                                │  7. Send verification email
  │  {user, access, refresh,       │
  │   email_verification_required} │
  │←──────────────────────────────│
  │                                │
  │  POST /api/v1/auth/verify-email/
  │  {token}                       │
  │──────────────────────────────→│
  │                                │  1. Find token, check not used/expired
  │                                │  2. Mark token used, set is_email_verified=True
  │                                │  3. Send welcome email
  │  {detail: "Email verified"}    │
  │←──────────────────────────────│
```

### Registration Flow (Google OAuth)

```
Client                          Backend
  │                                │
  │  POST /api/v1/auth/google/     │
  │  {id_token}                    │
  │──────────────────────────────→│
  │                                │  1. Verify Google ID token against Google APIs
  │                                │  2. Extract: email, name, picture, google_sub
  │                                │  3. If user exists with google_sub → return JWT tokens
  │                                │  4. If user exists by email but different provider → error
  │                                │  5. If new user → return temp_token for completing registration
  │  {access, refresh}             │  (Or: {temp_token, needs_completion: true})
  │  OR {temp_token}               │
  │←──────────────────────────────│
  │                                │
  │  POST /api/v1/auth/google/complete/
  │  {temp_token, username,        │
  │   agree_to_terms, ...}         │
  │──────────────────────────────→│
  │                                │  1. Validate temp_token (not expired, TTL=10min)
  │                                │  2. Create User with Google profile data
  │                                │  3. Auto-verify email (Google-verified)
  │                                │  4. Create profile + wallet + consent logs
  │  {user, access, refresh}       │
  │←──────────────────────────────│
```

### JWT Token Lifecycle

```
Login/Register → {access (1h), refresh (7d)}
     │
     ▼
Client stores tokens → Attaches access to every request
     │
     │ (access expired — 401 response)
     ▼
POST /api/v1/auth/token/refresh/ {refresh}
     │
     ▼
Backend rotates: new access + new refresh → old refresh blacklisted
     │
     │ (refresh expired or blacklisted)
     ▼
Redirect to login
```

### Authorization Layers

```
Request
  │
  ▼
Middleware (CORS → Security → WhiteNoise → CSRF → Auth → RateLimit)
  │
  ▼
DRF Authentication (JWTAuthentication → extracts user from token)
  │
  ▼
DRF Permission (IsAuthenticated / AllowAny / IsAdminUser)
  │
  ▼
Throttle Check (per-scope rate limits: anon, user, analyze, readonly, write, payment, auth)
  │
  ▼
View Logic (plan feature flags, credit checks, quota enforcement)
```

---

## 5. Resume Analysis Pipeline (Core)

This is the most important flow — the primary value proposition of the platform.

### Overview

```
POST /api/v1/analyze/ (multipart/form-data)
    │
    ▼
┌─────────────────┐
│  VIEW LAYER     │  1. Validate input (serializer)
│  (Django/DRF)   │  2. Check plan quotas (monthly limit, storage limit, file size)
│                 │  3. Deduct credits (atomic, select_for_update)
│                 │  4. Idempotency guard (Redis lock, 30s TTL)
│                 │  5. Deduplicate resume (SHA-256 hash → get_or_create)
│                 │  6. Create ResumeAnalysis record (status=processing)
│                 │  7. Dispatch Celery task → run_analysis_task.delay(id, user_id)
│                 │  8. Return 202 Accepted {id, status, credits_used, balance}
└─────────────────┘
    │
    ▼ (async)
┌─────────────────────────────────────────────────────────────────────────┐
│  CELERY WORKER — run_analysis_task                                      │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  ResumeAnalyzer.run(analysis) — orchestrates 5 pipeline steps    │  │
│  │                                                                   │  │
│  │  ┌──────────────┐   Each step:                                    │  │
│  │  │ Step 1:      │   • Checks if already done (resume support)     │  │
│  │  │ PDF Extract  │   • Executes the action                         │  │
│  │  │              │   • Saves result + pipeline_step to DB           │  │
│  │  │ pdfplumber   │   • If crash → can resume from this step        │  │
│  │  └──────┬───────┘                                                 │  │
│  │         │                                                          │  │
│  │         ▼                                                          │  │
│  │  ┌──────────────┐                                                 │  │
│  │  │ Step 2:      │   Three modes:                                   │  │
│  │  │ JD Resolve   │   • text → use directly                         │  │
│  │  │              │   • url  → scrape with Firecrawl → ScrapeResult │  │
│  │  │ JDFetcher    │   • form → assemble from structured fields      │  │
│  │  └──────┬───────┘   Cached: recent scrapes reused (24h)            │  │
│  │         │                                                          │  │
│  │         ▼                                                          │  │
│  │  ┌──────────────┐                                                 │  │
│  │  │ Step 3:      │   1. Build prompt (resume_text + resolved_jd)   │  │
│  │  │ LLM Call     │   2. Send to OpenRouter API                     │  │
│  │  │              │   3. Record: LLMResponse (prompt, raw response, │  │
│  │  │ OpenRouter   │      tokens, cost, duration, model)              │  │
│  │  │ (Claude/etc) │   4. Parse JSON from LLM output                 │  │
│  │  └──────┬───────┘                                                 │  │
│  │         │                                                          │  │
│  │         ▼                                                          │  │
│  │  ┌──────────────┐                                                 │  │
│  │  │ Step 4:      │   Map LLM JSON → ResumeAnalysis fields:         │  │
│  │  │ Parse Result │   • overall_grade (A-F)                          │  │
│  │  │              │   • scores (generic_ats, workday_ats, etc.)      │  │
│  │  │              │   • keyword_analysis (matched, missing, add)     │  │
│  │  │              │   • section_feedback (per-section scores)        │  │
│  │  │              │   • sentence_suggestions (original → suggested)  │  │
│  │  │              │   • formatting_flags, quick_wins, summary        │  │
│  │  │              │   • ats_score (generic_ats for dashboard)        │  │
│  │  └──────┬───────┘                                                 │  │
│  │         │                                                          │  │
│  │         ▼                                                          │  │
│  │  ┌──────────────┐                                                 │  │
│  │  │ Step 5:      │   Extract structured data from resume_text:     │  │
│  │  │ Resume Parse │   • contact info (name, email, phone, etc.)     │  │
│  │  │              │   • experience (companies, roles, bullets)       │  │
│  │  │ parse_resume │   • education, skills, certifications, etc.     │  │
│  │  │ _text()      │   Saved to analysis.parsed_content (JSON)       │  │
│  │  └──────┬───────┘                                                 │  │
│  │         │                                                          │  │
│  │         ▼                                                          │  │
│  │  STATUS = done, pipeline_step = done                               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  Post-analysis:                                                         │
│  1. Update Redis cache with final status (for fast polling)             │
│  2. Dispatch generate_pdf_report_task (async PDF upload to R2)          │
│  3. Send analysis-complete email (respects notification preferences)    │
│  4. Record Prometheus metrics (duration, status, tokens)                │
│                                                                         │
│  On failure:                                                            │
│  1. status=failed, pipeline_step=failed, error_message set              │
│  2. Auto-retry on transient errors (ConnectionError, OSError, Timeout)  │
│  3. Max 2 retries with exponential backoff (30s, 60s, 120s max)        │
│  4. Final failure → refund credits (if deducted)                        │
│  5. Update Redis cache with error status                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### Polling for Results

```
Client                          Backend
  │                                │
  │  GET /api/v1/analyses/{id}/status/
  │──────────────────────────────→│
  │                                │  1. Check Redis cache first (O(1) lookup)
  │                                │  2. If miss → query DB (only 'id', 'status',
  │                                │     'pipeline_step', 'overall_grade', 'ats_score')
  │                                │  3. Populate Redis cache (1h TTL)
  │  {status, pipeline_step,       │
  │   overall_grade, ats_score}    │
  │←──────────────────────────────│
  │                                │
  │  (repeat every 2-3 seconds     │
  │   until status = "done")       │
```

### Credit Deduction & Refund Flow

```
Analysis Start:
  deduct_credits(user, 'resume_analysis')
    │
    ├─ Wallet.objects.select_for_update()  ← atomic lock
    ├─ Check balance >= cost
    ├─ Subtract cost from balance
    ├─ Create WalletTransaction (type=analysis_debit)
    └─ Return {balance_before, balance_after, cost}

Analysis Failure/Cancel:
  refund_credits(user, 'resume_analysis')
    │
    ├─ Check analysis.credits_deducted == True
    ├─ Wallet.objects.select_for_update()
    ├─ Add cost back to balance
    ├─ Create WalletTransaction (type=refund)
    └─ Set analysis.credits_deducted = False
```

---

## 6. Resume Generation Pipeline

```
POST /api/v1/analyses/{id}/generate-resume/
  │
  ▼
View: Validate → Plan gating (premium templates) → Deduct credits → Create GeneratedResume
  │
  ▼ (async)
Celery: generate_improved_resume_task
  │
  ├─ Step 1: Build rewrite prompt from analysis findings
  │          (keyword gaps, section feedback, sentence suggestions, quick wins)
  │
  ├─ Step 2: Call LLM → get structured resume JSON
  │          (contact, summary, experience, education, skills, etc.)
  │
  ├─ Step 3: Record LLMResponse (prompt, raw response, tokens, cost)
  │
  ├─ Step 4: Render via template registry
  │          template_registry.get_renderer(template_slug, format)
  │            → resume_pdf_renderer.py or resume_docx_renderer.py
  │            → returns file bytes
  │
  ├─ Step 5: Upload to R2 (via Django FileField → S3Boto3Storage)
  │
  └─ Step 6: Update GeneratedResume (status=done, file=URL, resume_content=JSON)
```

### Template Registry

```python
template_registry = {
    ('ats_classic', 'pdf'):  resume_pdf_renderer.render,
    ('ats_classic', 'docx'): resume_docx_renderer.render,
    ('modern', 'pdf'):       resume_modern_pdf.render,
    ('modern', 'docx'):      resume_modern_docx.render,
    ('creative', 'pdf'):     resume_creative_pdf.render,
    ('creative', 'docx'):    resume_creative_docx.render,
    ('minimal', 'pdf'):      resume_minimal_pdf.render,
    ('minimal', 'docx'):     resume_minimal_docx.render,
    ('executive', 'pdf'):    resume_executive_pdf.render,
    ('executive', 'docx'):   resume_executive_docx.render,
}
```

---

## 7. Conversational Resume Builder Flow

```
POST /api/v1/resume-chat/start/           ← Create session
  │
  ▼
ResumeChat created (status=active, step=start)
  │
  ▼
POST /api/v1/resume-chat/{id}/submit/      ← Submit each step
  │  {action: "continue", payload: {...}}
  │
  ▼
resume_chat_service.process_step(chat, action, payload)
  │
  ├─ Step: start       → Welcome message, source selection
  ├─ Step: contact     → Collect name, email, phone, location, links
  ├─ Step: target_role → Job title, company, industry, experience level
  ├─ Step: experience_input  → Work history (companies, roles, dates, bullets)
  ├─ Step: experience_review → AI polishes bullet points (LLM call)
  ├─ Step: education   → Degrees, institutions, dates
  ├─ Step: skills      → Technical + soft skills
  ├─ Step: certifications → Professional certs
  ├─ Step: projects    → Notable projects
  ├─ Step: review      → AI final polish + suggestions (LLM call)
  └─ Step: done        → Ready for finalization
  │
  │ Each step:
  │   1. Creates user message (ResumeChatMessage, role=user)
  │   2. Processes payload → updates chat.resume_data progressively
  │   3. Creates assistant message with ui_spec (tells frontend what to render)
  │   4. Advances to next step (or stays if validation fails)
  │
  ▼
POST /api/v1/resume-chat/{id}/finalize/    ← Generate final file
  │  {template: "ats_classic", format: "pdf"}
  │
  ▼
finalize_resume(chat, template, format)
  │
  ├─ Deduct credits (resume_builder = 2 credits)
  ├─ Create GeneratedResume from chat.resume_data
  ├─ Dispatch rendering task
  └─ Mark chat status=completed
```

### Message UI Spec

Each assistant message includes a `ui_spec` JSON that tells the frontend what interactive component to render:

```json
{
  "type": "form",
  "fields": [
    {"name": "name", "type": "text", "label": "Full Name", "required": true},
    {"name": "email", "type": "email", "label": "Email"},
    {"name": "skills", "type": "chips", "label": "Skills"}
  ],
  "actions": [
    {"label": "Continue", "action": "continue"},
    {"label": "Skip", "action": "skip"}
  ]
}
```

---

## 8. Interview Prep Generation Flow

```
POST /api/v1/analyses/{id}/interview-prep/
  │
  ▼
View: Check analysis is done → Check no pending prep → Deduct credits
  │
  ▼ (async)
Celery: generate_interview_prep_task
  │
  ├─ Build prompt from: analysis results, resume text, JD text
  │  Focus on: gaps, weak areas, role requirements
  │
  ├─ Call LLM → get structured JSON:
  │    questions: [{category, question, why_asked, sample_answer, difficulty}]
  │    tips: [general interview advice]
  │
  ├─ Record LLMResponse (tokens, cost, duration)
  │
  └─ Update InterviewPrep (status=done, questions, tips)
      │
      ▼
  On failure: refund credits, status=failed
```

---

## 9. Cover Letter Generation Flow

```
POST /api/v1/analyses/{id}/cover-letter/
  │  {tone: "professional|conversational|enthusiastic"}
  │
  ▼
View: Check analysis is done → Check no pending for this tone → Deduct credits
  │
  ▼ (async)
Celery: generate_cover_letter_task
  │
  ├─ Build prompt from: analysis results, resume text, JD text, desired tone
  │
  ├─ Call LLM → get structured output:
  │    content (plain text), content_html (formatted HTML)
  │
  ├─ Generate PDF from content_html
  │
  ├─ Upload PDF to R2
  │
  ├─ Record LLMResponse (tokens, cost, duration)
  │
  └─ Update CoverLetter (status=done, content, content_html, file)
      │
      ▼
  On failure: refund credits, status=failed
```

---

## 10. Smart Job Alert Pipeline

### Alert Creation

```
POST /api/v1/job-alerts/
  │  {resume_id, frequency: "daily|weekly", preferences: {...}}
  │
  ▼
View: Check Pro plan → Validate resume exists → Create JobAlert → Set next_run_at
  │
  ▼ (async)
Celery: extract_job_search_profile_task(resume_id)
  │
  ├─ Read resume text
  ├─ Call LLM → extract: titles, skills, seniority, industries, locations, experience years
  ├─ Save JobSearchProfile (OneToOne with Resume)
  └─ Generate embedding (if pgvector available)
```

### Job Discovery & Matching (Periodic or Manual)

```
Celery Beat (daily/weekly)  OR  POST /api/v1/job-alerts/{id}/run/ (manual)
  │
  ▼
crawl_jobs_for_alert_task(alert_id)
  │
  ├─ Step 1: Build search queries from JobSearchProfile
  │          (combine titles + skills + locations)
  │
  ├─ Step 2: Crawl job boards (via Firecrawl API)
  │          CrawlSource (admin-managed) → url_template + {query} + {location}
  │          LinkedIn, Indeed, company career pages
  │
  ├─ Step 3: Parse discovered jobs → DiscoveredJob records
  │          Deduplicated by (source, external_id)
  │
  ├─ Step 4: Score relevance (0-100) via LLM
  │          Compare each job against resume/profile
  │          Generate match_reason text
  │
  ├─ Step 5: Create JobMatch records for scores above threshold
  │          JOB_MATCH_THRESHOLD (default 0.60 → 60/100)
  │
  ├─ Step 6: Dedup notifications (SentAlert table)
  │          Skip jobs already sent to this user via same channel
  │
  ├─ Step 7: Send notifications:
  │          • In-app: Create Notification record
  │          • Email: Send templated email (if job_alerts_email=true)
  │
  ├─ Step 8: Update alert: last_run_at, set_next_run()
  │
  └─ Step 9: Create JobAlertRun audit record
             (jobs_discovered, jobs_matched, credits_used, duration)
```

### Feedback Loop

```
POST /api/v1/job-alerts/{id}/matches/{match_id}/feedback/
  │  {feedback: "relevant|irrelevant|applied|dismissed", reason: "..."}
  │
  ▼
Update JobMatch.user_feedback → used to improve future matching
```

---

## 11. Payment & Subscription Flow

### Subscription (Pro Plan)

```
Client                    Backend                     Razorpay
  │                          │                           │
  │ POST /payments/subscribe/│                           │
  │ {plan_slug: "pro"}       │                           │
  │─────────────────────────→│                           │
  │                          │  1. Validate plan          │
  │                          │  2. Check no active sub    │
  │                          │  3. Get razorpay_plan_id   │
  │                          │──────────────────────────→│
  │                          │  4. Create subscription    │
  │                          │←──────────────────────────│
  │                          │  5. Store RazorpaySubscription
  │                          │     + RazorpayPayment      │
  │ {subscription_id,        │                           │
  │  key_id, amount, ...}    │                           │
  │←─────────────────────────│                           │
  │                          │                           │
  │  Open Razorpay Checkout  │                           │
  │  (client-side SDK)       │                           │
  │─────────────────────────────────────────────────────→│
  │                          │         Payment completed  │
  │←─────────────────────────────────────────────────────│
  │                          │                           │
  │ POST /payments/subscribe/verify/                     │
  │ {sub_id, payment_id,     │                           │
  │  signature}              │                           │
  │─────────────────────────→│                           │
  │                          │  1. HMAC-SHA256 signature  │
  │                          │     verification           │
  │                          │  2. Idempotency check      │
  │                          │     (credits_granted?)     │
  │                          │  3. Update subscription    │
  │                          │     status=active          │
  │                          │  4. Upgrade user's plan    │
  │                          │  5. Grant bonus credits    │
  │                          │  6. Set plan_valid_until   │
  │ {status: "active", ...}  │                           │
  │←─────────────────────────│                           │
  │                          │                           │
  │                          │  Webhook (async backup)    │
  │                          │←──────────────────────────│
  │                          │  1. Verify signature       │
  │                          │  2. Dedup (WebhookEvent)   │
  │                          │  3. Process (idempotent)   │
  │                          │  4. Return 200             │
```

### Top-Up (One-Time Credit Purchase)

```
POST /payments/topup/ {quantity: 2}
  │
  ▼
Backend: Validate plan supports top-ups → Create Razorpay Order → Store RazorpayPayment
  │
  ▼
Client opens Razorpay checkout → Completes payment
  │
  ▼
POST /payments/topup/verify/ {order_id, payment_id, signature}
  │
  ▼
Backend: Verify HMAC signature → Idempotency check → Add credits to wallet
  │  credits_added = plan.topup_credits_per_pack × quantity
  │  WalletTransaction(type=topup)
  │
  ▼
Response: {credits_added, balance_after, ...}
```

---

## 12. Credit System Flow

```
┌─────────────────────────────────────┐
│           CREDIT SOURCES            │
│                                     │
│  Plan Monthly Grant ──────────┐     │
│  Top-Up Purchase ─────────────┤     │
│  Upgrade Bonus ───────────────┤     │
│  Admin Adjustment ────────────┤     │
│  Refund (failed analysis) ────┤     │
│                               ▼     │
│                         ┌─────────┐ │
│                         │ WALLET  │ │
│                         │ balance │ │
│                         └────┬────┘ │
│                              │      │
│  Resume Analysis ◄───────────┤      │
│  Resume Generation ◄─────────┤      │
│  Interview Prep ◄────────────┤      │
│  Cover Letter ◄──────────────┤      │
│  Job Alert Run ◄─────────────┤      │
│  Resume Builder ◄────────────┘      │
│                                     │
│         CREDIT CONSUMERS            │
└─────────────────────────────────────┘

Every mutation:
  1. select_for_update() on Wallet (row-level lock)
  2. Validate balance >= cost
  3. Update balance
  4. Create WalletTransaction (immutable audit log)
  5. Release lock

Costs are configurable in CreditCost table (no code redeploy needed).
```

---

## 13. Notification System

```
Event Triggers:
  • Analysis complete → Notification(type=analysis_done)
  • Resume generated  → Notification(type=resume_generated)
  • Job match found   → Notification(type=job_match)
  • System event      → Notification(type=system)

Each notification creates:
  1. Notification record (in-app bell)
     {user, title, body, link, notification_type, metadata}
  2. Email (if user's notification preferences allow)
     Uses EmailTemplate + email_utils.send_templated_email()

Dedup for job alerts:
  SentAlert table prevents resending same job to same user on same channel.

Client polling:
  GET /notifications/unread-count/ → badge number
  GET /notifications/              → paginated list
  POST /notifications/mark-read/   → mark individual or all
```

---

## 14. Email System

```
Email sending flow:

1. Code calls: send_templated_email(slug, recipient, context)
2. Lookup EmailTemplate by slug (must be active)
3. Merge context with defaults: {app_name, frontend_url, support_email, ...}
4. Render subject + html_body through SANDBOXED template engine
   (no {% load %}, {% include %}, {% url %} — only {{ variables }})
5. Auto-generate plain_text_body from HTML (strip tags)
6. Send via EmailMultiAlternatives (HTML + plain text)

Backend configuration:
  Development: EMAIL_BACKEND = console (prints to stdout)
  Production:  EMAIL_BACKEND = SMTP (Gmail, SES, etc.)
```

---

## 15. File Storage Flow

```
                    Upload                               Download
                      │                                      │
                      ▼                                      ▼
              ┌───────────────┐                    ┌─────────────────┐
              │ Django Model  │                    │  Signed URL     │
              │ FileField     │                    │  (R2, 1h TTL)   │
              └───────┬───────┘                    └────────┬────────┘
                      │                                     │
            ┌─────────┼─────────┐                          │
            │         │         │                          │
     [R2 configured]  │  [No R2]                           │
            │         │         │                          │
            ▼         │         ▼                          │
     S3Boto3Storage   │   Local MEDIA_ROOT                 │
     (Cloudflare R2)  │   (/media/resumes/)                │
            │         │                                    │
            └─────────┘                                    │
                                                           │
Files stored:                                              │
  • resumes/          — Uploaded PDF resumes                │
  • reports/          — Analysis PDF reports                │
  • generated_resumes/— AI-generated improved resumes      │
  • cover_letters/    — Generated cover letter PDFs         │
  • template_previews/— Resume template thumbnails         │

Deduplication:
  Resume.compute_hash() → SHA-256 → unique per (user, hash)
  Same file uploaded twice → reuses existing record

Cleanup:
  post_delete signal on Resume → deletes file from R2/local
  post_delete signal on ResumeAnalysis → deletes report_pdf
  Soft-delete on analysis → deletes report_pdf, clears heavy fields
```

---

## 16. Caching Strategy

```
┌────────────────────────────────────────────────────────────────────┐
│                         REDIS CACHE                                │
│                                                                    │
│  Key Pattern                    │ TTL    │ Set By       │ Used By  │
│  ──────────────────────────────┼────────┼──────────────┼──────────│
│  analysis_status:{user}:{id}   │ 1 hour │ Celery task  │ Polling  │
│  dashboard_stats:{user}        │ 5 min  │ Dashboard API│ Dashboard│
│  analyze_lock:{user}           │ 30 sec │ Analyze view │ Idempot. │
│  _health_check                 │ 5 sec  │ Health check │ Health   │
│  DRF throttle keys             │ varies │ DRF throttle │ Rate lim │
│                                                                    │
│  Production: django_redis.cache.RedisCache                         │
│  Development: django.core.cache.backends.locmem.LocMemCache       │
│  Testing: LocMemCache (always, even if REDIS_URL set)             │
└────────────────────────────────────────────────────────────────────┘
```

---

## 17. Rate Limiting Architecture

```
Request → DRF Throttle Classes → Rate Decision
  │
  ├─ HeaderAwareAnonThrottle (for unauthenticated)
  │    Rate: ANON_THROTTLE_RATE (60/hour)
  │    Key: IP address
  │
  ├─ HeaderAwareUserThrottle (for authenticated)
  │    Rate: USER_THROTTLE_RATE (200/hour)
  │    Key: user ID
  │
  ├─ AnalyzeThrottle (analysis endpoints)
  │    Rate: ANALYZE_THROTTLE_RATE (10/hour)
  │
  ├─ ReadOnlyThrottle (GET endpoints)
  │    Rate: READONLY_THROTTLE_RATE (120/hour)
  │
  ├─ WriteThrottle (POST/PUT/DELETE)
  │    Rate: WRITE_THROTTLE_RATE (60/hour)
  │
  ├─ PaymentThrottle (payment endpoints)
  │    Rate: PAYMENT_THROTTLE_RATE (30/hour)
  │
  └─ AuthEndpointThrottle (login/register)
       Rate: AUTH_THROTTLE_RATE (20/hour)

Response headers injected by RateLimitHeadersMiddleware:
  X-RateLimit-Limit: 200
  X-RateLimit-Remaining: 187
  X-RateLimit-Reset: 1709312400

429 Too Many Requests:
  Retry-After: 3600
  X-RateLimit-Remaining: 0
```

---

## 18. Data Models & Relationships

```
User (Django built-in)
  │
  ├── 1:1 UserProfile
  │    └── FK → Plan
  │         └── FK → Plan (pending_plan)
  │
  ├── 1:1 NotificationPreference
  │
  ├── 1:1 Wallet
  │    └── 1:N WalletTransaction
  │
  ├── 1:N Resume
  │    ├── 1:1 JobSearchProfile
  │    ├── 1:N ResumeVersion
  │    └── 1:N JobAlert
  │         ├── 1:N JobMatch → FK DiscoveredJob
  │         └── 1:N JobAlertRun
  │
  ├── 1:N ResumeAnalysis
  │    ├── FK → Resume
  │    ├── FK → ScrapeResult
  │    ├── FK → LLMResponse
  │    ├── 1:N GeneratedResume
  │    │    └── FK → LLMResponse
  │    ├── 1:N InterviewPrep
  │    │    └── FK → LLMResponse
  │    └── 1:N CoverLetter
  │         └── FK → LLMResponse
  │
  ├── 1:N ResumeChat
  │    ├── FK → Resume (base_resume, optional)
  │    ├── FK → GeneratedResume (output, optional)
  │    └── 1:N ResumeChatMessage
  │         └── FK → LLMResponse (optional)
  │
  ├── 1:N RazorpayPayment
  ├── 1:N RazorpaySubscription → FK Plan
  ├── 1:N ConsentLog
  ├── 1:N Notification
  ├── 1:N SentAlert → FK DiscoveredJob
  └── 1:N EmailVerificationToken

Standalone:
  CreditCost (action → cost mapping)
  EmailTemplate (slug → email content)
  CrawlSource (job board definitions)
  ResumeTemplate (template marketplace metadata)
  WebhookEvent (dedup log)
  ContactSubmission (landing page contact form)
```

---

## 19. Celery Task Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CELERY CONFIGURATION                           │
│                                                                     │
│  Broker:   Redis (production) / memory:// (dev, tasks run eagerly) │
│  Backend:  Redis (production) / cache+memory:// (dev)               │
│  Timezone: UTC                                                      │
│  Serializer: JSON                                                   │
│  Hard limit: 600s (10 min)                                          │
│  Soft limit: 540s (9 min)                                           │
│  Max tasks per child: 50 (worker restart after 50 tasks)           │
└─────────────────────────────────────────────────────────────────────┘

Task                              Retries  Backoff   Trigger
─────────────────────────────────────────────────────────────────
run_analysis_task                 2        30s exp   API request
generate_pdf_report_task          2        15s       After analysis done
generate_improved_resume_task     2        15s       API request
extract_job_search_profile_task   2        15s       After alert created
crawl_jobs_for_alert_task         1        30s       Beat schedule / manual
match_jobs_task                   1        15s       After crawl done
generate_interview_prep_task      2        15s       API request
generate_cover_letter_task        2        15s       API request
cleanup_stale_analyses            0        —         Beat: every 15 min
flush_expired_tokens              0        —         Beat: daily
send_weekly_digest_task           0        —         Beat: Monday 9 AM UTC

Error handling:
  • autoretry_for: ConnectionError, OSError, TimeoutError
  • retry_backoff: True (exponential)
  • retry_backoff_max: 120 seconds
  • acks_late: True (re-deliver on worker crash)
  • reject_on_worker_lost: True
```

---

## 20. Observability Stack

```
┌──────────────────────────────────────────────────────────────┐
│                     METRICS (Prometheus)                      │
│                                                              │
│  Django Prometheus Middleware → /metrics endpoint             │
│  Custom metrics in resume_ai/metrics.py:                     │
│    • Analysis duration histogram                             │
│    • Active analysis gauge                                    │
│    • Analysis total counter (by status)                      │
│    • LLM token usage counter (by provider)                   │
│    • Credit operations counter (by type)                     │
│    • Credit amount counter (by type)                         │
│    • Payment failure counter (by reason)                     │
│    • Celery task duration histogram                           │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                     LOGGING                                   │
│                                                              │
│  Production: JSON format (pythonjsonlogger)                  │
│    → stdout → Railway log aggregation                        │
│    Fields: timestamp, logger, level, message, service        │
│                                                              │
│  Development: Human-readable format                          │
│    → stdout + logs/django.log (rotating 10MB × 5 backups)   │
│                                                              │
│  Logger hierarchy:                                           │
│    root          → WARNING                                   │
│    django        → WARNING                                   │
│    django.request→ ERROR                                     │
│    analyzer      → INFO (configurable via APP_LOG_LEVEL)     │
│    accounts      → INFO (configurable via APP_LOG_LEVEL)     │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                     HEALTH CHECK                              │
│                                                              │
│  GET /api/v1/health/                                         │
│    → Database connectivity                                   │
│    → Redis/cache connectivity                                │
│    → Celery worker availability                              │
│                                                              │
│  Returns 200 {status: "ok"} or 503 {status: "error"}        │
│  Used by: Railway health check, uptime monitors              │
└──────────────────────────────────────────────────────────────┘
```

---

## 21. Security Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SECURITY LAYERS                                  │
│                                                                     │
│  Transport:                                                         │
│    • HTTPS enforced (SECURE_SSL_REDIRECT)                          │
│    • HSTS: 1 year, include subdomains, preload                     │
│    • SECURE_PROXY_SSL_HEADER for Railway reverse proxy              │
│                                                                     │
│  Authentication:                                                    │
│    • JWT (access=1h, refresh=7d)                                    │
│    • Refresh token rotation with blacklisting                      │
│    • Google OAuth2 ID token verification                            │
│    • Password hashing: PBKDF2 (Django default)                     │
│                                                                     │
│  Authorization:                                                     │
│    • DRF permissions: IsAuthenticated, AllowAny, IsAdminUser        │
│    • Plan-based feature gating (feature flags on Plan model)        │
│    • Object-level: users can only access their own data             │
│                                                                     │
│  Input Validation:                                                  │
│    • DRF serializers for all inputs                                 │
│    • File size limits (MAX_RESUME_SIZE_MB)                         │
│    • PDF-only file upload restriction                               │
│    • Email template sandboxing (no {% load %})                     │
│                                                                     │
│  Anti-abuse:                                                        │
│    • Rate limiting (7 scopes, configurable per-scope rates)         │
│    • Idempotency locks (Redis) for analysis submissions            │
│    • Webhook signature verification (HMAC-SHA256)                   │
│    • Webhook replay protection (WebhookEvent dedup)                │
│    • CORS restricted to configured origins                         │
│                                                                     │
│  Data Protection:                                                   │
│    • Soft-delete for analyses (audit trail preserved)              │
│    • Consent logging (GDPR-compliant)                              │
│    • Data export endpoint (GDPR Right of Access)                   │
│    • Account deletion (cascade delete)                             │
│    • Signed URLs for R2 files (1h TTL)                             │
│                                                                     │
│  Headers:                                                           │
│    • X-Frame-Options: DENY                                          │
│    • X-Content-Type-Options: nosniff                               │
│    • Strict-Transport-Security: max-age=31536000                   │
│    • CSRF protection (cookie-based)                                │
│    • Rate limit headers (X-RateLimit-*)                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 22. API Versioning & URL Structure

All endpoints live under `/api/v1/`:

```
/admin/                              Django Admin
/metrics                             Prometheus metrics (django_prometheus)
/api/v1/health/                      Health check

/api/v1/auth/                        Authentication & account management
  ├── register/                      POST   Create account
  ├── login/                         POST   Get JWT tokens
  ├── logout/                        POST   Blacklist refresh token
  ├── logout-all/                    POST   Blacklist all sessions
  ├── token/refresh/                 POST   Rotate tokens
  ├── verify-email/                  POST   Verify email with token
  ├── resend-verification/           POST   Resend verification email
  ├── me/                            GET/PUT/DELETE  Profile CRUD
  ├── avatar/                        POST   Upload avatar
  ├── change-password/               POST   Change password
  ├── forgot-password/               POST   Request reset link
  ├── reset-password/                POST   Reset with token
  ├── notifications/                 GET/PUT Notification preferences
  ├── google/                        POST   Google OAuth login
  ├── google/complete/               POST   Complete Google registration
  ├── contact/                       POST   Landing page contact form
  ├── wallet/                        GET    View balance
  ├── wallet/transactions/           GET    Transaction history
  ├── wallet/transactions/export/    GET    Export as CSV
  ├── wallet/topup/                  POST   Free top-up (deprecated in favor of payments)
  ├── plans/                         GET    List plans
  ├── plans/subscribe/               POST   Change plan
  ├── payments/subscribe/            POST   Create Razorpay subscription
  ├── payments/subscribe/verify/     POST   Verify subscription payment
  ├── payments/subscribe/cancel/     POST   Cancel subscription
  ├── payments/subscribe/status/     GET    Subscription status
  ├── payments/topup/                POST   Create top-up order
  ├── payments/topup/verify/         POST   Verify top-up payment
  ├── payments/webhook/              POST   Razorpay webhook (no auth)
  └── payments/history/              GET    Payment history

/api/v1/                             Analyzer endpoints
  ├── analyze/                       POST   Start analysis
  ├── analyze/bulk/                  POST   Bulk analysis (up to 10 JDs)
  ├── analyses/                      GET    List analyses (paginated, filtered)
  ├── analyses/compare/              GET    Compare 2-5 analyses side-by-side
  ├── analyses/bulk-delete/          POST   Soft-delete multiple analyses
  ├── analyses/{id}/                 GET    Analysis detail
  ├── analyses/{id}/status/          GET    Polling endpoint (Redis-cached)
  ├── analyses/{id}/retry/           POST   Retry failed analysis
  ├── analyses/{id}/delete/          DELETE Soft-delete analysis
  ├── analyses/{id}/cancel/          POST   Cancel stuck analysis
  ├── analyses/{id}/export-pdf/      GET    Download PDF report
  ├── analyses/{id}/export-json/     GET    Download JSON export
  ├── analyses/{id}/share/           POST/DELETE Generate/revoke share link
  ├── analyses/{id}/generate-resume/ POST   Generate improved resume
  ├── analyses/{id}/generated-resume/GET    Poll generation status
  ├── analyses/{id}/generated-resume/download/ GET Download generated file
  ├── analyses/{id}/interview-prep/  POST/GET Generate/view interview prep
  ├── analyses/{id}/cover-letter/    POST/GET Generate/view cover letter
  ├── shared/{token}/                GET    Public shared analysis (no auth)
  ├── shared/{token}/summary/        GET    Public lightweight summary
  ├── resumes/                       GET    List resumes
  ├── resumes/{id}/                  DELETE Delete resume
  ├── resumes/{id}/versions/         GET    Version history
  ├── resumes/bulk-delete/           POST   Bulk delete resumes
  ├── dashboard/stats/               GET    Dashboard analytics
  ├── generated-resumes/             GET    List generated resumes
  ├── generated-resumes/{id}/        DELETE Delete generated resume
  ├── job-alerts/                    GET/POST List/create job alerts
  ├── job-alerts/{id}/               GET/PUT/DELETE Alert detail/update/deactivate
  ├── job-alerts/{id}/matches/       GET    List matched jobs
  ├── job-alerts/{id}/matches/{mid}/feedback/ POST Update match feedback
  ├── job-alerts/{id}/run/           POST   Manual job discovery trigger
  ├── notifications/                 GET    List notifications
  ├── notifications/unread-count/    GET    Unread badge count
  ├── notifications/mark-read/       POST   Mark notifications as read
  ├── interview-preps/               GET    List all interview preps
  ├── cover-letters/                 GET    List all cover letters
  ├── templates/                     GET    List resume templates
  ├── account/export/                GET    GDPR data export
  ├── resume-chat/start/             POST   Start builder session
  ├── resume-chat/                   GET    List sessions
  ├── resume-chat/resumes/           GET    List resumes for base selection
  ├── resume-chat/{id}/              GET/DELETE Session detail/delete
  ├── resume-chat/{id}/submit/       POST   Submit step action
  ├── resume-chat/{id}/finalize/     POST   Generate final file
  ├── admin/celery/workers/          GET    Worker status (admin only)
  ├── admin/celery/tasks/active/     GET    Active tasks (admin only)
  ├── admin/celery/tasks/{id}/       GET    Task status (admin only)
  └── admin/celery/queues/           GET    Queue lengths (admin only)
```

---

## 23. Deployment Pipeline

```
Code Push → Railway Auto-Deploy → Build (nixpacks) → rolling restart

┌──────────────────────────────────────────────────────────────────┐
│  entrypoint.sh (per SERVICE_TYPE)                                │
│                                                                  │
│  web:                                                            │
│    flock -w 120 /tmp/migrate.lock python manage.py migrate       │
│    python manage.py seed_email_templates                         │
│    python manage.py seed_plans                                   │
│    gunicorn resume_ai.wsgi:application                           │
│      --bind 0.0.0.0:$PORT --workers 2 --threads 2              │
│                                                                  │
│  worker:                                                         │
│    celery -A resume_ai worker -l info                            │
│      --concurrency 2 --max-tasks-per-child 50                   │
│                                                                  │
│  beat:                                                           │
│    celery -A resume_ai beat -l info                              │
│      --scheduler django_celery_beat.schedulers:DatabaseScheduler │
│                                                                  │
│  flower (optional):                                              │
│    celery -A resume_ai flower --port $PORT                       │
│      --basic-auth admin:$FLOWER_PASSWORD                        │
└──────────────────────────────────────────────────────────────────┘

Migration safety:
  • flock ensures only one replica runs migrations at a time
  • Other replicas wait up to 120s, then proceed regardless
  • seed commands are idempotent (create if not exists)
```

---

*This document provides the complete technical architecture of i-Luffy. For API integration details, see `FRONTEND_API_GUIDE.md`. For admin operations, see `docs/ADMIN_USAGE_GUIDE.md`. For user features, see `docs/USER_GUIDE.md`.*
