# resume_ai_with_luffy

AI-powered resume optimization API. Upload a PDF resume, provide a job description, and get back an ATS score, keyword gaps, section-wise suggestions, and rewritten bullet points.

## Stack

- **Django 4.2** + **Django REST Framework**
- **SQLite** (dev) — swap to Postgres for production
- **JWT auth** via `djangorestframework-simplejwt`
- **PDF parsing** via `pdfplumber`
- **JD scraping** via `requests` + `BeautifulSoup`
- **AI**: pluggable — Claude (Anthropic) or OpenAI GPT-4o

---

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — add your API key

python manage.py migrate
python manage.py runserver
```

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
