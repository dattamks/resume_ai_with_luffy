# resume_ai_with_luffy

AI-powered resume optimization API. Upload a PDF resume, provide a job description, and get back an ATS score, keyword gaps, section-wise suggestions, and rewritten bullet points.

## Stack

- **Django 4.2** + **Django REST Framework**
- **PostgreSQL** (required — dev and production) + **pgvector** for embeddings
- **Redis** — cache, Celery broker, throttle state
- **Celery** — async task processing (analysis, resume generation, job crawling)
- **JWT auth** via `djangorestframework-simplejwt`
- **PDF parsing** via `pdfplumber`
- **JD scraping** via `Firecrawl` + `BeautifulSoup` fallback
- **AI**: OpenRouter (Claude, GPT-4o, Gemini) — pluggable provider architecture
- **Storage**: Cloudflare R2 (S3-compatible) for resume uploads
- **Deployment**: Railway (Gunicorn + WhiteNoise)

---

## Local Development Setup

### Prerequisites

- Python 3.12+
- PostgreSQL 15+ with pgvector extension
- Redis 7+

### PostgreSQL Setup

**Option A — Docker (recommended):**

```bash
# Start PostgreSQL with pgvector
docker run -d --name resume-ai-postgres \
  -e POSTGRES_DB=resume_ai \
  -e POSTGRES_USER=resume_ai \
  -e POSTGRES_PASSWORD=localdev123 \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Start Redis
docker run -d --name resume-ai-redis \
  -p 6379:6379 \
  redis:7-alpine
```

**Option B — System install (Ubuntu/Debian):**

```bash
sudo apt install postgresql postgresql-contrib
sudo -u postgres createdb resume_ai
sudo -u postgres createuser resume_ai --createdb
sudo -u postgres psql -c "ALTER USER resume_ai PASSWORD 'localdev123';"

# Install pgvector extension
sudo apt install postgresql-16-pgvector
sudo -u postgres psql -d resume_ai -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**Option C — macOS (Homebrew):**

```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
createdb resume_ai
psql resume_ai -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Environment Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — required variables:
#   DATABASE_URL=postgresql://resume_ai:localdev123@localhost:5432/resume_ai
#   REDIS_URL=redis://localhost:6379/0
#   OPENROUTER_API_KEY=<your-key>
#   SECRET_KEY=<random-string>
```

### Database Migration & Seed

```bash
python manage.py migrate
python manage.py seed_plans          # Create Free/Pro/Enterprise plans
python manage.py seed_credit_costs   # Set per-action credit costs
python manage.py seed_email_templates  # Load email templates
python manage.py load_interview_questions  # Load interview question bank
python manage.py createsuperuser     # Admin access
```

### Run

```bash
# Terminal 1 — Django
python manage.py runserver

# Terminal 2 — Celery worker (for async tasks)
celery -A resume_ai worker --loglevel=info

# Terminal 3 — Celery Beat (for scheduled tasks)
celery -A resume_ai beat --loglevel=info
```

### Important Notes

- **PostgreSQL is required** — SQLite is not supported. Job matching uses pgvector embeddings, and several queries use PostgreSQL-specific features (`PERCENT_RANK`, `JSONField` lookups, `ArrayAgg`).
- **pgvector extension required** — Must be installed and enabled (`CREATE EXTENSION vector;`). Used for resume/job embedding similarity search.
- **Redis required** — Used for Celery task queue, Django cache, and rate limiting.

---

## API Endpoints

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register/` | Register a new user |
| POST | `/api/auth/login/` | Login — returns `access` + `refresh` tokens |
| POST | `/api/auth/logout/` | Invalidate refresh token |
| POST | `/api/auth/token/refresh/` | Refresh access token |
| GET  | `/api/auth/me/` | Current user info |

### Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/analyze/` | Upload resume + JD → full analysis |
| GET  | `/api/analyses/` | List user's past analyses |
| GET  | `/api/analyses/<id>/` | Get full details of one analysis |

---

## POST /api/analyze/ — Request

Send as `multipart/form-data`.

**Always required:**

| Field | Type | Description |
|-------|------|-------------|
| `resume_file` | File (PDF) | Resume — max 5MB |
| `jd_input_type` | string | `"text"`, `"url"`, or `"form"` |

**When `jd_input_type = "text"`:**

| Field | Type |
|-------|------|
| `jd_text` | string — full job description |

**When `jd_input_type = "url"`:**

| Field | Type |
|-------|------|
| `jd_url` | string — URL to job posting |

**When `jd_input_type = "form"`:**

| Field | Type | Required |
|-------|------|----------|
| `jd_role` | string | Yes |
| `jd_company` | string | No |
| `jd_skills` | string (comma-separated) | No |
| `jd_experience_years` | integer | No |
| `jd_industry` | string | No |
| `jd_extra_details` | string | No |

---

## POST /api/analyze/ — Response

```json
{
  "id": 1,
  "status": "done",
  "ats_score": 72,
  "ats_score_breakdown": {
    "keyword_match": 65,
    "format_score": 80,
    "relevance_score": 70
  },
  "keyword_gaps": ["Kubernetes", "CI/CD", "System Design"],
  "section_suggestions": {
    "summary": "Add a 2-3 sentence summary targeting the role.",
    "experience": "Lead bullets with strong action verbs; add metrics (%, $, x).",
    "skills": "Add missing tools: Kubernetes, Terraform.",
    "education": "Looks good.",
    "overall": "Strong experience section. Summary missing. Add measurable outcomes."
  },
  "rewritten_bullets": [
    {
      "original": "Worked on backend services",
      "rewritten": "Designed and shipped 3 REST microservices handling 50K req/day using Django and PostgreSQL.",
      "reason": "Added specifics, metrics, and action-verb opening."
    }
  ],
  "overall_assessment": "Solid background for this role with 72/100 ATS match. Primary gaps are cloud-native keywords (Kubernetes, CI/CD) and lack of quantified achievements. Add those and your score should exceed 85.",
  "ai_provider_used": "ClaudeProvider",
  "created_at": "2026-02-21T10:00:00Z"
}
```

---

## Switching AI Provider

In `.env`:

```
AI_PROVIDER=openai        # use OpenAI GPT-4o
AI_PROVIDER=claude        # use Anthropic Claude (default)
```

To add a new provider: implement `AIProvider` in `analyzer/services/ai_providers/`, then register it in `factory.py`.
