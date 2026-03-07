# COMPREHENSIVE REPOSITORY SCAN REPORT
## resume_ai_with_luffy

**Report Generated:** March 7, 2026
**Repository Path:** `/home/user/resume_ai_with_luffy`
**Scan Type:** Comprehensive (all files, all models, all views)

---

## 1. PROJECT OVERVIEW

**Purpose:** AI-powered resume optimization and intelligent job matching platform. Users upload PDF resumes, provide job descriptions (via text, URL, or structured form), and receive comprehensive ATS analysis with scoring, keyword gaps, section-wise suggestions, and AI-improved bullet points. Includes job alert matching, interview prep generation, cover letter synthesis, and a conversational resume builder.

**Tech Stack:**
- **Framework:** Django 4.2.16 + Django REST Framework 3.15.2
- **Language:** Python 3.12+
- **Database:** PostgreSQL 15+ (required) with pgvector for embeddings
- **Caching/Queue:** Redis 7+ (Celery broker, cache, rate limiting)
- **Task Processing:** Celery 5.4.0 + django-celery-beat 2.7.0
- **Authentication:** JWT (djangorestframework-simplejwt 5.3.1) + Google OAuth
- **LLM Integration:** OpenAI, Anthropic Claude, or Luffy (self-hosted, pluggable)
- **PDF/Document Processing:** pdfplumber, reportlab, python-docx, Playwright (HTML-to-PDF)
- **Job Scraping:** Firecrawl 4.16.0 + BeautifulSoup fallback
- **File Storage:** Cloudflare R2 (S3-compatible) or local filesystem
- **Payments:** Razorpay subscriptions + one-time top-ups
- **Deployment:** Railway (Gunicorn + nixpacks/Docker)

---

## 2. DIRECTORY STRUCTURE

```
/home/user/resume_ai_with_luffy/
├── resume_ai/                      # Django project configuration
│   ├── settings.py                 # Main Django settings (env-driven)
│   ├── urls.py                     # Root URL router
│   ├── wsgi.py                     # WSGI application
│   ├── celery.py                   # Celery app initialization
│   ├── exception_handler.py        # Custom DRF exception formatter
│   ├── middleware.py               # Rate limit header injection
│   └── metrics.py                  # Prometheus metrics collection
│
├── accounts/                       # User authentication, plans, payments, wallets
│   ├── models.py                   # 13 data models
│   ├── views.py                    # Auth/profile endpoints
│   ├── views_payments.py           # Razorpay payment flows
│   ├── serializers.py              # Request/response schemas
│   ├── urls.py                     # Auth routes (/api/v1/auth/*)
│   ├── razorpay_service.py         # Razorpay API integration
│   ├── email_utils.py              # Email template rendering/sending
│   ├── services.py                 # Business logic (credits, wallet)
│   ├── throttles.py                # Custom rate limiters
│   ├── management/commands/        # seed_plans, seed_credit_costs
│   ├── migrations/                 # 20 schema versions
│   └── tests/                      # 7 test modules
│
├── analyzer/                       # Core resume analysis, job matching, feeds
│   ├── models.py                   # 35+ data models (2338 lines)
│   ├── views.py                    # 30+ API endpoints
│   ├── views_feed.py               # Feed, trending skills, news
│   ├── views_ingest.py             # Crawler bot ingest API
│   ├── views_skills.py             # Skill catalogue endpoints
│   ├── views_chat.py               # Resume builder chat endpoints
│   ├── views_health.py             # Health check
│   ├── serializers.py              # Analysis result schemas
│   ├── urls.py                     # Main API routes (/api/v1/*)
│   ├── urls_feed.py                # Feed routes (/api/v1/feed/*)
│   ├── urls_ingest.py              # Crawler API routes (/api/v1/ingest/*)
│   ├── urls_skills.py              # Skill routes (/api/v1/skills/*)
│   ├── tasks.py                    # 10+ Celery async tasks
│   ├── admin.py                    # Django Admin configuration
│   ├── services/                   # Business logic modules (20+)
│   ├── migrations/                 # 38 schema versions
│   └── tests/                      # 20 test modules
│
├── mobile/                         # (stub) Future mobile app
├── docs/                           # Documentation
├── logs/                           # Application logs
│
├── manage.py                       # Django CLI
├── entrypoint.sh                   # Railway startup script
├── Procfile                        # Heroku/Railway process definitions
├── railway.json                    # Railway deployment config
├── nixpacks.toml                   # System package dependencies
├── runtime.txt                     # Python 3.12
├── requirements.txt                # 78 pinned dependencies
├── .env.example                    # Configuration template (65 variables)
└── .gitignore                      # Standard Python ignores
```

---

## 3. DJANGO APPS & MODELS

### App 1: `accounts` (User Management, Plans, Payments) — 13 Models

| Model | Purpose |
|-------|---------|
| `UserProfile` | Extended user info (plan, phone, country, Google OAuth fields) |
| `NotificationPreference` | Email/SMS toggles (6 notification types) |
| `EmailTemplate` | Reusable email templates (auth, alerts, marketing, system) |
| `Plan` | Subscription tiers (Free/Pro/Enterprise) with quotas, credits |
| `Wallet` | User credit balance |
| `WalletTransaction` | Immutable audit log (plan credit, topup, debit, refund, admin adjust) |
| `CreditCost` | Admin-managed per-action costs |
| `RazorpayPayment` | Payment attempt tracking |
| `RazorpaySubscription` | Subscription lifecycle management |
| `ConsentLog` | Immutable consent audit (ToS, data usage, marketing) |
| `EmailVerificationToken` | 24-hour email verification tokens |
| `ContactSubmission` | Landing page contact form submissions |
| `WebhookEvent` | Razorpay webhook deduplication |

### App 2: `analyzer` (Resume Analysis, Job Matching, Feeds) — 35+ Models

| Category | Models |
|----------|--------|
| **Resume & Analysis** | `Resume`, `ResumeAnalysis`, `ResumeVersion`, `GeneratedResume` |
| **Companies & Jobs** | `Company`, `CompanyEntity`, `CompanyCareerPage`, `DiscoveredJob`, `JobAlert`, `JobMatch`, `JobSearchProfile`, `RoleFamily` |
| **Job Infrastructure** | `CrawlSource`, `JobAlertRun`, `SentAlert`, `UserCompanyFollow`, `NewsSnippet`, `Skill` |
| **AI Content** | `InterviewPrep`, `InterviewQuestion`, `CoverLetter` |
| **Resume Builder** | `ResumeChat`, `ResumeChatMessage` |
| **Infrastructure** | `LLMResponse`, `ScrapeResult`, `Notification`, `UserActivity`, `ResumeTemplate` |

**Total: 48 Models**

---

## 4. API ENDPOINTS (60+)

### Authentication (`/api/v1/auth/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/register/` | Register user |
| POST | `/login/` | Login (JWT tokens) |
| POST | `/logout/` | Logout |
| POST | `/logout-all/` | Revoke all devices |
| POST | `/token/refresh/` | Refresh access token |
| POST | `/verify-email/` | Verify email token |
| POST | `/resend-verification/` | Resend verification |
| GET | `/me/` | Current user profile |
| POST | `/avatar/` | Upload profile picture |
| POST | `/change-password/` | Change password |
| POST | `/forgot-password/` | Initiate password reset |
| POST | `/reset-password/` | Reset via token |
| GET | `/notifications/` | Notification preferences |
| POST | `/google/` | Google OAuth login |
| POST | `/google/complete/` | Google OAuth callback |
| POST | `/contact/` | Landing page contact form |

### Wallet & Credits (`/api/v1/auth/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/wallet/` | Wallet balance + stats |
| GET | `/wallet/transactions/` | Transaction history |
| GET | `/wallet/transactions/export/` | CSV export |
| POST | `/wallet/topup/` | Top-up credits |

### Plans & Subscriptions (`/api/v1/auth/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/plans/` | List plans |
| POST | `/plans/subscribe/` | Subscribe to plan |
| POST | `/payments/subscribe/` | Create subscription (Razorpay) |
| POST | `/payments/subscribe/verify/` | Verify payment |
| POST | `/payments/subscribe/cancel/` | Cancel subscription |
| GET | `/payments/subscribe/status/` | Subscription status |
| POST | `/payments/topup/` | Create top-up order |
| POST | `/payments/topup/verify/` | Verify top-up |
| POST | `/payments/webhook/` | Razorpay webhook handler |
| GET | `/payments/history/` | Payment history |

### Resume Analysis (`/api/v1/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/analyze/` | Main analysis endpoint |
| GET | `/analyses/` | List analyses |
| GET | `/analyses/<id>/` | Get analysis details |
| GET | `/analyses/<id>/status/` | Poll async status |
| POST | `/analyses/<id>/retry/` | Retry failed analysis |
| POST | `/analyses/<id>/cancel/` | Cancel processing |
| DELETE | `/analyses/<id>/delete/` | Soft delete |
| POST | `/analyses/<id>/export-pdf/` | Export PDF report |
| POST | `/analyses/<id>/export-json/` | Export JSON |
| POST | `/analyses/<id>/share/` | Generate share link |
| GET | `/shared/<token>/` | View shared analysis |
| POST | `/analyses/bulk-delete/` | Bulk soft delete |
| POST | `/analyses/compare/` | Compare analyses |

### Resume Management (`/api/v1/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/resumes/` | List uploaded resumes |
| DELETE | `/resumes/<id>/` | Delete resume |
| POST | `/resumes/<id>/set-default/` | Mark as default |
| GET | `/resumes/<id>/versions/` | Version history |
| POST | `/resumes/bulk-delete/` | Bulk delete |

### Generated Resumes (`/api/v1/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/analyses/<id>/generate-resume/` | Trigger generation |
| GET | `/analyses/<id>/generated-resume/` | Get status |
| GET | `/analyses/<id>/generated-resume/download/` | Download PDF/DOCX |
| GET | `/generated-resumes/` | List generated |
| DELETE | `/generated-resumes/<id>/` | Delete generated |

### Job Alerts (`/api/v1/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/job-alerts/` | List/Create alerts |
| GET/POST/DELETE | `/job-alerts/<id>/` | CRUD operations |
| GET | `/job-alerts/<id>/matches/` | List matches |
| POST | `/job-alerts/<id>/matches/<id>/feedback/` | Submit feedback |
| POST | `/job-alerts/<id>/run/` | Trigger manual run |

### Content Generation (`/api/v1/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/analyses/<id>/interview-prep/` | Generate interview prep |
| GET | `/interview-preps/` | List prep sessions |
| POST | `/analyses/<id>/cover-letter/` | Generate cover letter |
| GET | `/cover-letters/` | List cover letters |

### Dashboard (`/api/v1/dashboard/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/stats/` | Stats overview |
| GET | `/skill-gap/` | Skill gap analysis |
| GET | `/market-insights/` | Market insights |
| GET | `/activity/` | Activity data |

### Feed (`/api/v1/feed/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/jobs/` | Recommended jobs |
| GET | `/insights/` | Industry insights |
| GET | `/trending-skills/` | Trending skills |
| GET | `/hub/` | Job feed hub |
| GET | `/news/` | News articles |

### Skills (`/api/v1/skills/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all skills |
| GET | `/<name>/` | Skill details |

### Resume Builder Chat (`/api/v1/`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/resume-chat/start/` | Start builder session |
| GET | `/resume-chat/` | List sessions |
| GET | `/resume-chat/<id>/` | Get session |
| POST | `/resume-chat/<id>/message/` | Send message |
| POST | `/resume-chat/<id>/submit/` | Submit step |
| POST | `/resume-chat/<id>/finalize/` | Finalize & generate |

### Crawler Bot Ingest API (`/api/v1/ingest/`) — Requires `X-Crawler-Key`
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ping/` | Health check |
| POST | `/companies/` | Ingest company |
| POST | `/companies/bulk/` | Bulk ingest |
| POST | `/entities/` | Ingest entity |
| POST | `/jobs/` | Ingest job |
| POST | `/jobs/bulk/` | Bulk ingest |
| POST | `/news/` | Ingest news |
| POST | `/news/bulk/` | Bulk ingest |

### Admin & System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health/` | Health check |
| GET | `/metrics/` | Prometheus metrics |
| GET | `/api/v1/admin/celery/workers/` | Active workers |
| GET | `/api/v1/admin/celery/tasks/active/` | Active tasks |

---

## 5. DEPENDENCIES (78 pinned packages)

| Category | Packages |
|----------|----------|
| **Core Framework** | Django==4.2.16, djangorestframework==3.15.2 |
| **Authentication** | djangorestframework-simplejwt==5.3.1, google-auth==2.38.0 |
| **Database** | psycopg2-binary==2.9.10, pgvector==0.4.2 |
| **Caching** | django-redis==5.4.0, redis==5.4.0 |
| **Async Tasks** | celery[redis]==5.4.0, django-celery-beat==2.7.0 |
| **PDF Processing** | pdfplumber==0.11.4, reportlab==4.4.0, playwright==1.50.0 |
| **Document Gen** | python-docx==1.1.2, Pillow==10.4.0 |
| **Web Scraping** | firecrawl-py==4.16.0, beautifulsoup4==4.12.3 |
| **AI APIs** | openai==1.57.2 |
| **Payments** | razorpay==2.0.0 |
| **File Storage** | django-storages[boto3]==1.14.4, boto3==1.36.14 |
| **Production** | gunicorn==22.0.0, whitenoise==6.8.2 |
| **Monitoring** | django-prometheus==2.3.1, flower==2.0.1 |

---

## 6. CODE QUALITY & ISSUES

### Security Assessment: STRONG

- No hardcoded secrets (env-driven configuration)
- SECRET_KEY validation (raises error if insecure default in production)
- HTTPS enforcement (SECURE_SSL_REDIRECT when DEBUG=False)
- Secure cookies (SESSION_COOKIE_SECURE, CSRF, SameSite)
- Razorpay webhook signature verification (HMAC-SHA256)
- JWT with rotation & blacklist
- Password validators enabled
- 100% ORM-based (no SQL injection risk)
- No eval()/exec() usage

### Potential Issues

| Issue | Severity | Description |
|-------|----------|-------------|
| Print in migration | Low | `migrations/0030_*.py` uses `print()` instead of logger |
| N+1 queries | Medium | Some views lack `select_related()`/`prefetch_related()` |
| Large models.py | Low | `analyzer/models.py` at 2338 lines — consider splitting |
| Missing type hints | Low | Type hints used selectively, not comprehensively |

### Test Coverage: MODERATE

- **27 test files** (7 accounts, 20 analyzer)
- **Well covered:** Authentication, JWT, payments, profile operations, basic analysis
- **Gaps:** Feed/recommendation logic, crawler bot ingest, job matching algorithm, edge cases (malformed PDFs, timeout handling)

### Migrations: CLEAN
- 58 total (20 accounts + 38 analyzer)
- Linear progression, no conflicts, all up-to-date

---

## 7. DEPLOYMENT

### Architecture
```
[Web] Gunicorn (2 workers x 2 threads) --> [PostgreSQL 15+]
[Worker] Celery (concurrency=2)         --> [Redis 7+]
[Beat] Celery Beat scheduler
[Flower] Task monitoring (optional)
```

### Deployment Platform: Railway
- **Builder:** Nixpacks (installs Playwright Chromium dependencies)
- **Entrypoint:** `entrypoint.sh` (detects SERVICE_TYPE: web/worker/beat/flower)
- **Migrations:** Run with `flock` to prevent concurrent execution across replicas
- **Auto-seeding:** Plans, credit costs, email templates on first startup

---

## 8. SUMMARY

| Metric | Value |
|--------|-------|
| Django Apps | 2 core (accounts, analyzer) |
| Database Models | 48 total |
| API Endpoints | 60+ RESTful routes |
| Migrations | 58 total |
| Celery Tasks | 10+ async tasks |
| Services/Modules | 20+ business logic modules |
| Test Files | 27 test modules |
| Dependencies | 78 pinned packages |
| External Integrations | 5 (OpenAI, Anthropic, Luffy, Firecrawl, Razorpay) |
| Python Version | 3.12+ |
| Django Version | 4.2.16 LTS |

---

## 9. FINAL ASSESSMENT

**Project Maturity:** Production-grade, actively maintained
**Code Quality:** Well-structured, follows Django conventions
**Test Coverage:** Moderate (covers critical paths)
**Security:** Strong (no hardcoded secrets, proper crypto)
**Scalability:** Horizontally scalable (stateless web, async tasks)

### Strengths
- Modular architecture with clear separation of concerns
- Pluggable AI provider system (Claude/OpenAI/Luffy)
- Comprehensive async task pipeline
- Rich ORM models with constraints and indexes
- Multi-modal payment system (subscriptions + top-ups)
- Sophisticated job matching with pgvector embeddings
- Proper soft-delete patterns for data retention

### Areas for Improvement
1. Add integration tests for full analysis pipeline
2. Add `select_related()` to query hotspots (N+1 prevention)
3. Split large `analyzer/models.py` into submodules
4. Replace `print()` with Django logger in migrations
5. Add comprehensive type hints
6. Set up error tracking (e.g., Sentry)
7. Add database query performance monitoring

### Recommended Next Steps
1. Implement caching layer for feed queries
2. Monitor Celery task latency and optimize
3. Add integration tests for feed/recommendation logic
4. Set up APM (Application Performance Monitoring)
