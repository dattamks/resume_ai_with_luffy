# Frontend API Integration Guide

> **Last updated:** 2026-02-22
> Technical reference for frontend developers integrating with the Resume AI backend.

---

## Table of Contents

1. [Base URL & Authentication](#1-base-url--authentication)
2. [Auth Endpoints](#2-auth-endpoints)
3. [Analysis Endpoints](#3-analysis-endpoints)
4. [Response Schemas](#4-response-schemas)
5. [Pagination](#5-pagination)
6. [Rate Limiting](#6-rate-limiting)
7. [Polling for Analysis Status](#7-polling-for-analysis-status)
8. [LLM Analysis Output Schema](#8-llm-analysis-output-schema)
9. [Recent Backend Changes (Breaking)](#9-recent-backend-changes-breaking)
10. [Error Handling Reference](#10-error-handling-reference)

---

## 1. Base URL & Authentication

### Base URL

```
Development:  http://localhost:8000/api
Production:   https://<backend>.up.railway.app/api
```

Set via environment variable: `VITE_API_URL`

### Authentication — JWT (Bearer Token)

All endpoints except `/api/auth/register/`, `/api/auth/login/`, and `/api/health/` require a JWT access token.

```
Authorization: Bearer <access_token>
```

**Token lifetimes:**
| Token    | Lifetime   |
|----------|------------|
| Access   | 1 hour     |
| Refresh  | 7 days     |

Refresh tokens are **rotated on use** — each refresh call returns a new refresh token and blacklists the old one.

**Refresh flow:**
```
POST /api/auth/token/refresh/
Body: { "refresh": "<refresh_token>" }
→ { "access": "<new_access>", "refresh": "<new_refresh>" }
```

---

## 2. Auth Endpoints

All prefixed with `/api/auth/`.

### POST `/api/auth/register/`

Create a new user account. Returns tokens immediately (auto-login).

**Request:**
```json
{
  "username": "john",
  "email": "john@example.com",
  "password": "SecurePass123!",
  "password2": "SecurePass123!"
}
```

**Response (201 Created):**
```json
{
  "user": {
    "id": 1,
    "username": "john",
    "email": "john@example.com",
    "date_joined": "2026-02-22T10:00:00Z"
  },
  "access": "<jwt_access_token>",
  "refresh": "<jwt_refresh_token>"
}
```

**Errors (400):** Password too weak, passwords don't match, duplicate username.

---

### POST `/api/auth/login/`

**Request:**
```json
{
  "username": "john",
  "password": "SecurePass123!"
}
```

**Response (200 OK):**
```json
{
  "access": "<jwt_access_token>",
  "refresh": "<jwt_refresh_token>",
  "user": {
    "id": 1,
    "username": "john",
    "email": "john@example.com",
    "date_joined": "2026-02-22T10:00:00Z"
  }
}
```

---

### POST `/api/auth/logout/`

🔒 Requires auth. Blacklists the refresh token.

**Request:**
```json
{
  "refresh": "<refresh_token>"
}
```

**Response (200):** `{ "detail": "Successfully logged out." }`
**Error (400):** `{ "detail": "Invalid token." }`

---

### GET `/api/auth/me/`

🔒 Requires auth. Returns the current user profile.

**Response (200):**
```json
{
  "id": 1,
  "username": "john",
  "email": "john@example.com",
  "date_joined": "2026-02-22T10:00:00Z"
}
```

---

### POST `/api/auth/token/refresh/`

Exchange a valid refresh token for new access + refresh tokens.

**Request:**
```json
{ "refresh": "<refresh_token>" }
```

**Response (200):**
```json
{
  "access": "<new_access_token>",
  "refresh": "<new_refresh_token>"
}
```

---

## 3. Analysis Endpoints

All prefixed with `/api/`.

### POST `/api/analyze/` — Submit New Analysis

🔒 Requires auth. **Throttled:** 10/hour per user. **Content-Type: `multipart/form-data`**.

Submits a resume PDF + job description for async analysis. Returns immediately with a tracking ID.

**⚠️ Idempotency guard:** A second submit within 30 seconds returns **409 Conflict**. The frontend should disable the submit button after the first click.

**Form fields:**

| Field               | Type     | Required | Description |
|---------------------|----------|----------|-------------|
| `resume_file`       | File     | ✅       | PDF file, max 5 MB, must have `.pdf` extension and `%PDF` magic bytes |
| `jd_input_type`     | String   | ✅       | One of: `"text"`, `"url"`, `"form"` |
| `jd_text`           | String   | If type=`text` | Raw job description text |
| `jd_url`            | String   | If type=`url`  | URL to a job posting (scraped via Firecrawl) |
| `jd_role`           | String   | If type=`form` | Job title / role name |
| `jd_company`        | String   | No       | Company name (form mode) |
| `jd_skills`         | String   | No       | Comma-separated skills (form mode) |
| `jd_experience_years` | Integer | No     | Required years of experience (form mode) |
| `jd_industry`       | String   | No       | Industry/domain (form mode) |
| `jd_extra_details`  | String   | No       | Free-text additional details (form mode) |

**Response (202 Accepted):**
```json
{
  "id": 42,
  "status": "processing"
}
```

**Errors:**
- `400` — Validation error (bad PDF, missing required fields)
- `409` — Duplicate submission (idempotency lock active)
- `429` — Rate limit exceeded

---

### GET `/api/analyses/` — List Analyses

🔒 Requires auth. Returns **paginated** list of the user's own analyses (newest first).

**Query parameters:**

| Param  | Default | Description |
|--------|---------|-------------|
| `page` | 1       | Page number |

**Response (200):**
```json
{
  "count": 47,
  "next": "https://api.example.com/api/analyses/?page=3",
  "previous": "https://api.example.com/api/analyses/?page=1",
  "results": [
    {
      "id": 42,
      "jd_role": "Backend Engineer",
      "jd_company": "Acme Corp",
      "status": "done",
      "pipeline_step": "done",
      "ats_score": 78,
      "ai_provider_used": "OpenRouterProvider",
      "report_pdf_url": "https://r2.example.com/reports/report_42.pdf",
      "created_at": "2026-02-22T14:30:00Z"
    }
  ]
}
```

**⚠️ BREAKING CHANGE:** Previously returned a flat array. Now returns a paginated envelope with `count`, `next`, `previous`, `results`. Page size: **20 items**.

---

### GET `/api/analyses/<id>/` — Analysis Detail

🔒 Requires auth. Returns the full analysis with nested scrape result and LLM response.

**Response (200):** See [Detail Response Schema](#detail-response-schema) below.

---

### GET `/api/analyses/<id>/status/` — Poll Status (Lightweight)

🔒 Requires auth. Ultra-fast polling endpoint — reads from Redis cache first.

**Response (200):**
```json
{
  "status": "processing",
  "pipeline_step": "llm_call",
  "ats_score": null,
  "error_message": ""
}
```

**Status values:** `"pending"` → `"processing"` → `"done"` | `"failed"`

**Pipeline step values (in order):**
1. `"pending"` — Not started
2. `"pdf_extract"` — Extracting text from resume PDF
3. `"jd_scrape"` — Resolving/scraping job description
4. `"llm_call"` — Calling AI model for analysis
5. `"parse_result"` — Parsing and saving results
6. `"done"` — Complete
7. `"failed"` — An error occurred

**Recommended polling strategy:**
- Poll every **2 seconds** while `status === "processing"`
- Stop polling when `status === "done"` or `status === "failed"`
- Show `pipeline_step` as a progress indicator to the user

---

### POST `/api/analyses/<id>/retry/` — Retry Failed Analysis

🔒 Requires auth. **Throttled:** 10/hour (shares analyze throttle).

Retries a failed analysis from its last incomplete pipeline step.

**Request:** Empty body.

**Response (202):**
```json
{
  "id": 42,
  "status": "processing",
  "pipeline_step": "llm_call"
}
```

**Errors:**
- `400` — Analysis is already complete
- `404` — Not found / not owned by user
- `409` — Analysis is already processing

---

### DELETE `/api/analyses/<id>/delete/` — Delete Analysis

🔒 Requires auth.

**Response (204):** No content.
**Error (404):** Not found / not owned by user.

---

### GET `/api/analyses/<id>/export-pdf/` — Download PDF Report

🔒 Requires auth.

If a pre-generated PDF exists (stored in Cloudflare R2), redirects to the signed URL (302). Otherwise generates on-the-fly and returns the PDF bytes directly.

**Response:** PDF file download (`Content-Type: application/pdf`)

**Errors:**
- `400` — Analysis not complete yet
- `404` — Not found

---

### GET `/api/health/` — Health Check

🔓 Public (no auth required).

**Response (200):** `{ "status": "ok" }`
**Response (503):** `{ "status": "error", "detail": "..." }`

---

## 4. Response Schemas

### Detail Response Schema

Returned by `GET /api/analyses/<id>/`:

```json
{
  "id": 42,
  "resume_file": "resumes/resume_abc123.pdf",
  "resume_file_url": "https://r2.example.com/resumes/resume_abc123.pdf",
  "jd_input_type": "text",
  "jd_text": "We need a senior Python developer...",
  "jd_url": "",
  "jd_role": "Senior Python Developer",
  "jd_company": "TechCorp Inc.",
  "jd_skills": "Python, Django, PostgreSQL, AWS",
  "jd_experience_years": 5,
  "jd_industry": "Technology/SaaS",
  "jd_extra_details": "Remote position, requires 5+ years experience in backend development.",
  "resolved_jd": "We need a senior Python developer...",
  "scrape_result": null,
  "llm_response": {
    "id": "a1b2c3d4-...",
    "parsed_response": { "...see LLM schema below..." },
    "model_used": "anthropic/claude-haiku-4.5",
    "status": "done",
    "error_message": "",
    "duration_seconds": 4.32,
    "created_at": "2026-02-22T14:30:05Z"
  },
  "status": "done",
  "pipeline_step": "done",
  "error_message": "",
  "ats_score": 78,
  "ats_score_breakdown": {
    "keyword_match": 72,
    "format_score": 85,
    "relevance_score": 76
  },
  "keyword_gaps": ["Kubernetes", "Terraform", "CI/CD"],
  "section_suggestions": {
    "summary": "Add a targeted summary mentioning Python and cloud experience.",
    "experience": "Include metrics in bullet points — quantify impact.",
    "skills": "Add missing keywords: Kubernetes, Terraform.",
    "education": "Education section is well-structured.",
    "overall": "Strong technical background but needs better keyword alignment."
  },
  "rewritten_bullets": [
    {
      "original": "Worked on backend services",
      "rewritten": "Architected and maintained 12 Python/Django microservices serving 50K+ daily active users, reducing API latency by 40%",
      "reason": "Added specifics, metrics, and action verb"
    }
  ],
  "overall_assessment": "Strong Python background with relevant experience. Key gaps are in DevOps/cloud skills mentioned in the JD. Priority: add Kubernetes and CI/CD experience, quantify achievements.",
  "ai_provider_used": "OpenRouterProvider",
  "celery_task_id": "abc-123-def",
  "report_pdf_url": "https://r2.example.com/reports/report_42.pdf",
  "created_at": "2026-02-22T14:30:00Z",
  "updated_at": "2026-02-22T14:30:12Z"
}
```

### Scrape Result (nested, when `jd_input_type === "url"`)

```json
{
  "id": "uuid-...",
  "source_url": "https://jobs.example.com/posting/12345",
  "summary": "Senior Python Developer at TechCorp...",
  "status": "done",
  "error_message": "",
  "created_at": "2026-02-22T14:30:02Z",
  "updated_at": "2026-02-22T14:30:03Z"
}
```

> **Note:** `markdown` and `json_data` fields are **no longer exposed** in the API to reduce payload size. Only the `summary` field is returned.

### LLM Response (nested)

```json
{
  "id": "uuid-...",
  "parsed_response": { "...full LLM output..." },
  "model_used": "anthropic/claude-haiku-4.5",
  "status": "done",
  "error_message": "",
  "duration_seconds": 4.32,
  "created_at": "2026-02-22T14:30:05Z"
}
```

> **Note:** `prompt_sent` and `raw_response` fields are **no longer exposed** in the API to reduce payload size (~160KB saved per response).

---

## 5. Pagination

**⚠️ BREAKING CHANGE** — The list endpoint now returns paginated responses.

| Setting   | Value |
|-----------|-------|
| Page size | 20    |
| Style     | `PageNumberPagination` |
| Query param | `?page=N` |

**Envelope format:**
```json
{
  "count": 47,
  "next": "http://api.example.com/api/analyses/?page=3",
  "previous": "http://api.example.com/api/analyses/?page=1",
  "results": [ ... ]
}
```

**Frontend migration:**
```js
// BEFORE
const analyses = response.data;

// AFTER
const { count, next, previous, results } = response.data;
const analyses = results;
```

---

## 6. Rate Limiting

| Scope     | Default Limit | Env Var Override        |
|-----------|---------------|------------------------|
| General API (per user) | 30 / hour | `USER_THROTTLE_RATE` |
| Analyze endpoint | 10 / hour | `ANALYZE_THROTTLE_RATE` |

When rate-limited, the API returns:

```
HTTP 429 Too Many Requests
{
  "detail": "Request was throttled. Expected available in 120 seconds."
}
```

The `Retry-After` header is also set.

**Exempt endpoints (no throttle):**
- `GET /api/analyses/` (list)
- `GET /api/analyses/<id>/` (detail)
- `GET /api/analyses/<id>/status/` (polling)
- `DELETE /api/analyses/<id>/delete/`
- `GET /api/analyses/<id>/export-pdf/`

---

## 7. Polling for Analysis Status

After submitting an analysis (`POST /api/analyze/`), poll the lightweight status endpoint:

```
GET /api/analyses/<id>/status/
```

### Recommended implementation:

```js
async function pollAnalysisStatus(analysisId, onUpdate) {
  const POLL_INTERVAL = 2000; // 2 seconds
  const MAX_POLLS = 150;      // 5 minutes max

  for (let i = 0; i < MAX_POLLS; i++) {
    const { data } = await api.get(`/analyses/${analysisId}/status/`);
    onUpdate(data);

    if (data.status === 'done' || data.status === 'failed') {
      return data;
    }

    await new Promise(r => setTimeout(r, POLL_INTERVAL));
  }

  throw new Error('Polling timeout');
}
```

### Pipeline step → UI label mapping:

| `pipeline_step` | Suggested UI Text |
|-----------------|-------------------|
| `pending`       | "Queued..." |
| `pdf_extract`   | "Reading your resume..." |
| `jd_scrape`     | "Fetching job description..." |
| `llm_call`      | "AI is analyzing..." |
| `parse_result`  | "Finalizing results..." |
| `done`          | "Complete!" |
| `failed`        | "Analysis failed" |

---

## 8. LLM Analysis Output Schema

The AI returns the following JSON schema. These fields are stored in `llm_response.parsed_response` and also flattened onto the top-level analysis object.

```json
{
  "job_metadata": {
    "job_title": "Senior Python Developer",
    "company": "TechCorp Inc.",
    "skills": "Python, Django, PostgreSQL, AWS, Docker",
    "experience_years": 5,
    "industry": "Technology/SaaS",
    "extra_details": "Remote position. Team of 8 engineers. Series B startup focused on developer tools."
  },
  "ats_score": 78,
  "ats_score_breakdown": {
    "keyword_match": 72,
    "format_score": 85,
    "relevance_score": 76
  },
  "keyword_gaps": [
    "Kubernetes",
    "Terraform",
    "CI/CD"
  ],
  "section_suggestions": {
    "summary": "Add a targeted professional summary highlighting Python and cloud expertise.",
    "experience": "Quantify achievements with metrics. Use stronger action verbs.",
    "skills": "Add missing JD keywords: Kubernetes, Terraform, Docker.",
    "education": "Education section is appropriate and well-formatted.",
    "overall": "Strong technical profile. Focus on adding DevOps keywords and quantifying impact."
  },
  "rewritten_bullets": [
    {
      "original": "Worked on backend services",
      "rewritten": "Architected and maintained 12 Python/Django microservices serving 50K+ DAU, reducing API latency by 40%",
      "reason": "Added specifics, metrics, and strong action verb"
    }
  ],
  "overall_assessment": "Strong Python background with relevant experience. Key gaps in DevOps/cloud skills. Priority actions: add Kubernetes experience, quantify achievements, add targeted summary."
}
```

### Field reference:

| Field | Type | Description |
|-------|------|-------------|
| `job_metadata.job_title` | string | Job title extracted from JD by LLM |
| `job_metadata.company` | string | Company name (empty string if not found) |
| `job_metadata.skills` | string | Comma-separated key skills from JD |
| `job_metadata.experience_years` | int \| null | Required years of experience |
| `job_metadata.industry` | string | Industry/domain (empty string if unclear) |
| `job_metadata.extra_details` | string | 2-4 sentence summary of other JD details |
| `ats_score` | int (0-100) | Overall ATS compatibility score |
| `ats_score_breakdown.keyword_match` | int (0-100) | How many JD keywords appear in resume |
| `ats_score_breakdown.format_score` | int (0-100) | Resume structure and readability |
| `ats_score_breakdown.relevance_score` | int (0-100) | Overall alignment with the role |
| `keyword_gaps` | string[] | Keywords from JD missing in resume |
| `section_suggestions.summary` | string | Feedback on summary/objective section |
| `section_suggestions.experience` | string | Feedback on work experience |
| `section_suggestions.skills` | string | Feedback on skills section |
| `section_suggestions.education` | string | Feedback on education section |
| `section_suggestions.overall` | string | High-level structural feedback |
| `rewritten_bullets[].original` | string | Original bullet from resume |
| `rewritten_bullets[].rewritten` | string | Improved version |
| `rewritten_bullets[].reason` | string | Explanation of what was improved |
| `overall_assessment` | string | 2-3 sentence summary of strengths, gaps, priorities |

### How `jd_role`, `jd_company`, etc. are populated:

- **`form` input type:** User provides these fields directly → stored as-is.
- **`text` / `url` input type:** The LLM extracts `job_metadata` from the JD and populates `jd_role`, `jd_company`, `jd_skills`, `jd_experience_years`, `jd_industry`, `jd_extra_details` **only** if the user didn't supply them.

This means the frontend can always rely on these fields being populated on a completed analysis, regardless of input type.

---

## 9. Recent Backend Changes (Breaking)

### 9.1 Pagination on list endpoint

**Affected:** `GET /api/analyses/`

Previously returned a flat JSON array. Now returns a paginated envelope:

```js
// Old: response.data = [...]
// New: response.data = { count, next, previous, results: [...] }
```

**Action required:** Update all list consumers to read `response.data.results`.

---

### 9.2 Idempotency guard on analyze

**Affected:** `POST /api/analyze/`

A second submission within 30 seconds now returns **409 Conflict**:

```json
{ "detail": "An analysis is already being submitted. Please wait." }
```

**Action required:** Handle 409 responses. Disable the submit button after first click. Show a "please wait" message.

---

### 9.3 Serializer field changes

**Removed from `scrape_result` nested object:**
- `markdown` (large raw scrape text)
- `json_data` (raw scrape JSON)

**Removed from `llm_response` nested object:**
- `prompt_sent` (the full prompt sent to the LLM)
- `raw_response` (raw LLM text output)

These fields were large (~160KB+) and not used by the frontend. If you were displaying any of these, they are no longer available.

**Added to `scrape_result` nested object:**
- `summary` — Concise text summary from Firecrawl

---

### 9.4 New fields on analysis detail

These fields are now populated for all JD input types (not just `form`):

| Field | Type | Description |
|-------|------|-------------|
| `jd_role` | string | Job title |
| `jd_company` | string | Company name |
| `jd_skills` | string | Comma-separated skills |
| `jd_experience_years` | int \| null | Required experience |
| `jd_industry` | string | Industry/domain |
| `jd_extra_details` | string | Additional JD summary |

For `text` and `url` inputs, these are extracted by the LLM from the job description. The frontend can display them universally.

---

### 9.5 AI provider change

The backend now uses **OpenRouter** (model: `anthropic/claude-haiku-4.5`) instead of the Luffy self-hosted LLM. The `ai_provider_used` field on analyses will show `"OpenRouterProvider"` or the model name.

No frontend action required — this is transparent to the frontend.

---

## 10. Error Handling Reference

### HTTP Status Codes

| Code | Meaning | When |
|------|---------|------|
| 200  | OK | Successful GET/POST |
| 201  | Created | Successful registration |
| 202  | Accepted | Analysis submitted (async processing) |
| 204  | No Content | Successful DELETE |
| 302  | Redirect | PDF export → R2 signed URL |
| 400  | Bad Request | Validation error, invalid data |
| 401  | Unauthorized | Missing/expired JWT token |
| 404  | Not Found | Resource doesn't exist or not owned by user |
| 409  | Conflict | Duplicate submission / already processing |
| 429  | Too Many Requests | Rate limit exceeded |
| 500  | Server Error | Unexpected backend error |
| 503  | Service Unavailable | Database unreachable (health check) |

### Error response format:

```json
{
  "detail": "Human-readable error message."
}
```

Or for validation errors (400):

```json
{
  "field_name": ["Error message for this field."],
  "other_field": ["Another error."]
}
```

---

## Quick Reference — All Endpoints

| Method | URL | Auth | Throttle | Description |
|--------|-----|------|----------|-------------|
| POST | `/api/auth/register/` | ❌ | User | Create account |
| POST | `/api/auth/login/` | ❌ | User | Get JWT tokens |
| POST | `/api/auth/logout/` | ✅ | User | Blacklist refresh token |
| POST | `/api/auth/token/refresh/` | ❌ | User | Refresh JWT |
| GET | `/api/auth/me/` | ✅ | User | Current user profile |
| POST | `/api/analyze/` | ✅ | Analyze (10/hr) | Submit analysis |
| GET | `/api/analyses/` | ✅ | None | List analyses (paginated) |
| GET | `/api/analyses/<id>/` | ✅ | None | Full analysis detail |
| GET | `/api/analyses/<id>/status/` | ✅ | None | Poll status (lightweight) |
| POST | `/api/analyses/<id>/retry/` | ✅ | Analyze (10/hr) | Retry failed analysis |
| DELETE | `/api/analyses/<id>/delete/` | ✅ | None | Delete analysis |
| GET | `/api/analyses/<id>/export-pdf/` | ✅ | None | Download PDF report |
| GET | `/api/health/` | ❌ | None | Health check |
