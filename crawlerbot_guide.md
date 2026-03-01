# Crawler Bot Ingest API Guide

> **Last updated:** 2026-03-01 &nbsp;|&nbsp; **API version:** v1.0.0
> Comprehensive technical reference for the external Crawler Bot service integrating with the i-Luffy backend.

---

## Quick Start (TL;DR)

**1. Set the shared secret** — same value in both services' `.env`:

```env
CRAWLER_API_KEY=your-strong-random-secret-here
INGEST_BASE_URL=https://<backend>.up.railway.app/api/v1/ingest
```

Generate a key: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

**2. Test auth:**

```bash
curl -H "X-Crawler-Key: your-secret" https://<backend>.up.railway.app/api/v1/ingest/ping/
# → {"status": "ok", ...}
```

**3. Ingest order** (FK dependencies):

```
Companies → Entities → Career Pages → Jobs
                                       ↑ (jobs can skip steps 1-3)
```

**4. Minimum viable job ingest** (no company/entity needed):

```bash
curl -X POST https://<backend>.up.railway.app/api/v1/ingest/jobs/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "firecrawl",
    "external_id": "google-swe-123",
    "url": "https://careers.google.com/jobs/123/",
    "title": "Senior Software Engineer",
    "company": "Google",
    "location": "Bangalore, India",
    "skills_required": ["Python", "Go", "Kubernetes"],
    "seniority_level": "senior",
    "employment_type": "full_time",
    "remote_policy": "hybrid"
  }'
```

**5. Bulk ingest** (up to 500 jobs per request):

```bash
curl -X POST https://<backend>.up.railway.app/api/v1/ingest/jobs/bulk/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{ "jobs": [ { "source": "firecrawl", "external_id": "...", "url": "...", "title": "..." }, ... ] }'
```

**All upserts are idempotent** — calling the same endpoint with the same data just updates the existing record. No duplicates.

**No rate limiting** on ingest endpoints — the X-Crawler-Key auth is sufficient.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Base URL & Authentication](#2-base-url--authentication)
3. [API Client Setup](#3-api-client-setup)
4. [Ping / Health Check](#4-ping--health-check)
5. [Company Ingest](#5-company-ingest)
6. [Company Entity Ingest](#6-company-entity-ingest)
7. [Career Page Ingest](#7-career-page-ingest)
8. [Job Ingest](#8-job-ingest)
9. [Crawl Sources](#9-crawl-sources)
10. [Ingestion Order & Dependencies](#10-ingestion-order--dependencies)
11. [Error Handling](#11-error-handling)
12. [Rate Limiting](#12-rate-limiting)
13. [Data Model Reference](#13-data-model-reference)
14. [Full Workflow Example](#14-full-workflow-example)
15. [Environment Variables](#15-environment-variables)
16. [Quick Reference — All Endpoints](#16-quick-reference--all-endpoints)

---

## 1. Architecture Overview

```
┌─────────────────────────┐                              ┌─────────────────────────┐
│                         │   HTTP POST/GET (JSON)       │                         │
│   Crawler Bot Service   │  ─────────────────────────►  │   i-Luffy Backend       │
│   (separate Django app) │   X-Crawler-Key: <secret>    │   (this project)        │
│                         │                              │                         │
│   Responsibilities:     │                              │   Responsibilities:     │
│   • Crawl job boards    │                              │   • Store companies     │
│   • Scrape career pages │                              │   • Store jobs          │
│   • Extract job data    │                              │   • Match to users      │
│   • Enrich via LLM      │  ◄─────────────────────────  │   • Send notifications  │
│                         │   GET crawl-sources          │   • Serve frontend      │
└─────────────────────────┘                              └─────────────────────────┘
```

### Data Flow

1. **Crawler Bot** starts a crawl run
2. Fetches active **Crawl Sources** from the backend (`GET /api/v1/ingest/crawl-sources/`)
3. For each source, scrapes job listings from the URL
4. Extracts & enriches job data (title, skills, seniority, etc.)
5. **Ingests companies** first (`POST /api/v1/ingest/companies/`)
6. **Ingests entities** next (`POST /api/v1/ingest/entities/`)
7. **Ingests career pages** (optional, `POST /api/v1/ingest/career-pages/`)
8. **Ingests jobs** last (`POST /api/v1/ingest/jobs/` or `/jobs/bulk/`)
9. Updates `last_crawled_at` on the crawl source (`PATCH /api/v1/ingest/crawl-sources/<id>/`)

---

## 2. Base URL & Authentication

### Base URL

```
Development:  http://localhost:8000/api/v1/ingest
Production:   https://<backend>.up.railway.app/api/v1/ingest
```

### Authentication — Shared Secret

All ingest endpoints use a shared API key passed in the `X-Crawler-Key` HTTP header. **No JWT tokens are needed.**

```
X-Crawler-Key: <your-secret-key>
Content-Type: application/json
```

| Header          | Required | Description                                  |
|-----------------|----------|----------------------------------------------|
| `X-Crawler-Key` | **Yes**  | Shared secret matching `CRAWLER_API_KEY` env var |
| `Content-Type`  | **Yes**  | Must be `application/json` for POST/PATCH    |

**Error responses for auth failures:**

| Status | Meaning                            |
|--------|------------------------------------|
| `401`  | `X-Crawler-Key` header missing     |
| `403`  | Key provided but doesn't match     |

### Setting the Key

Both services need the same secret in their environment:

```env
# In the i-Luffy backend (.env)
CRAWLER_API_KEY=your-strong-random-secret-here

# In the Crawler Bot service (.env)
CRAWLER_API_KEY=your-strong-random-secret-here
INGEST_BASE_URL=https://<backend>.up.railway.app/api/v1/ingest
```

---

## 3. API Client Setup

### Python Example (requests)

```python
import requests

INGEST_BASE_URL = "http://localhost:8000/api/v1/ingest"
CRAWLER_API_KEY = "your-strong-random-secret-here"

session = requests.Session()
session.headers.update({
    "X-Crawler-Key": CRAWLER_API_KEY,
    "Content-Type": "application/json",
})

# Quick auth check
resp = session.get(f"{INGEST_BASE_URL}/ping/")
assert resp.status_code == 200
print(resp.json())  # {"status": "ok", "service": "resume-ai-ingest", "timestamp": "..."}
```

### Django REST Framework Client

```python
import requests

class IngestClient:
    """HTTP client for pushing data to the i-Luffy ingest API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            "X-Crawler-Key": api_key,
            "Content-Type": "application/json",
        })

    def ping(self) -> dict:
        resp = self.session.get(f"{self.base_url}/ping/")
        resp.raise_for_status()
        return resp.json()

    def ingest_company(self, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}/companies/", json=data)
        resp.raise_for_status()
        return resp.json()

    def ingest_companies_bulk(self, companies: list[dict]) -> dict:
        resp = self.session.post(
            f"{self.base_url}/companies/bulk/",
            json={"companies": companies},
        )
        resp.raise_for_status()
        return resp.json()

    def ingest_entity(self, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}/entities/", json=data)
        resp.raise_for_status()
        return resp.json()

    def ingest_entities_bulk(self, entities: list[dict]) -> dict:
        resp = self.session.post(
            f"{self.base_url}/entities/bulk/",
            json={"entities": entities},
        )
        resp.raise_for_status()
        return resp.json()

    def ingest_career_page(self, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}/career-pages/", json=data)
        resp.raise_for_status()
        return resp.json()

    def ingest_job(self, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}/jobs/", json=data)
        resp.raise_for_status()
        return resp.json()

    def ingest_jobs_bulk(self, jobs: list[dict]) -> dict:
        resp = self.session.post(
            f"{self.base_url}/jobs/bulk/",
            json={"jobs": jobs},
        )
        resp.raise_for_status()
        return resp.json()

    def get_crawl_sources(self) -> list[dict]:
        resp = self.session.get(f"{self.base_url}/crawl-sources/")
        resp.raise_for_status()
        return resp.json()

    def update_crawl_source(self, source_id: str, last_crawled_at: str) -> dict:
        resp = self.session.patch(
            f"{self.base_url}/crawl-sources/{source_id}/",
            json={"last_crawled_at": last_crawled_at},
        )
        resp.raise_for_status()
        return resp.json()
```

---

## 4. Ping / Health Check

Quick endpoint to verify authentication is working.

### `GET /api/v1/ingest/ping/`

**curl:**

```bash
curl -X GET https://<backend>.up.railway.app/api/v1/ingest/ping/ \
  -H "X-Crawler-Key: your-strong-random-secret-here"
```

**Response `200 OK`:**

```json
{
  "status": "ok",
  "service": "resume-ai-ingest",
  "timestamp": "2026-03-01T10:30:00.000Z"
}
```

**Response `403 Forbidden`:**

```json
{
  "detail": "Authentication credentials were not provided."
}
```

---

## 5. Company Ingest

### 5.1 Upsert a Single Company

**`POST /api/v1/ingest/companies/`**

Creates or updates a company based on the unique `name` field.

**curl:**

```bash
curl -X POST https://<backend>.up.railway.app/api/v1/ingest/companies/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Google",
    "industry": "Technology",
    "company_size": "enterprise",
    "headquarters_country": "United States",
    "headquarters_city": "Mountain View",
    "tech_stack": ["Python", "Go", "Java", "Kubernetes"]
  }'
```

**Request Body:**

```json
{
  "name": "Google",
  "description": "A multinational technology company specializing in search, cloud, and AI.",
  "logo": "https://logo.clearbit.com/google.com",
  "industry": "Technology",
  "founded_year": 1998,
  "company_size": "enterprise",
  "headquarters_country": "United States",
  "headquarters_city": "Mountain View",
  "linkedin_url": "https://www.linkedin.com/company/google/",
  "glassdoor_url": "https://www.glassdoor.com/Overview/Working-at-Google-EI_IE9079.htm",
  "tech_stack": ["Python", "Go", "Java", "Kubernetes", "TensorFlow"]
}
```

| Field                  | Type     | Required | Notes                                                    |
|------------------------|----------|----------|----------------------------------------------------------|
| `name`                 | string   | **Yes**  | Brand name. **Upsert key** — must be unique.             |
| `slug`                 | string   | No       | Auto-generated from `name` if omitted.                   |
| `description`          | string   | No       | Brief company description.                               |
| `logo`                 | URL      | No       | URL to company logo image.                               |
| `industry`             | string   | No       | e.g., "Technology", "Finance", "Healthcare".             |
| `founded_year`         | integer  | No       | e.g., 1998.                                              |
| `company_size`         | string   | No       | One of: `startup`, `small`, `mid`, `large`, `enterprise`.|
| `headquarters_country` | string   | No       | e.g., "United States", "India".                          |
| `headquarters_city`    | string   | No       | e.g., "Mountain View", "Bangalore".                      |
| `linkedin_url`         | URL      | No       | LinkedIn company page URL.                               |
| `glassdoor_url`        | URL      | No       | Glassdoor overview URL.                                  |
| `tech_stack`           | string[] | No       | Known technologies, e.g., `["Python", "Kubernetes"]`.    |
| `is_active`            | boolean  | No       | Default `true`. Set `false` to hide.                     |

**Response `201 Created`:**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Google",
  "slug": "google",
  "description": "A multinational technology company...",
  "logo": "https://logo.clearbit.com/google.com",
  "industry": "Technology",
  "founded_year": 1998,
  "company_size": "enterprise",
  "headquarters_country": "United States",
  "headquarters_city": "Mountain View",
  "linkedin_url": "https://www.linkedin.com/company/google/",
  "glassdoor_url": "https://www.glassdoor.com/Overview/Working-at-Google-EI_IE9079.htm",
  "tech_stack": ["Python", "Go", "Java", "Kubernetes", "TensorFlow"],
  "is_active": true,
  "created_at": "2026-03-01T10:30:00Z",
  "updated_at": "2026-03-01T10:30:00Z"
}
```

### 5.2 Bulk Upsert Companies

**`POST /api/v1/ingest/companies/bulk/`**

**curl:**

```bash
curl -X POST https://<backend>.up.railway.app/api/v1/ingest/companies/bulk/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "companies": [
      { "name": "Google", "industry": "Technology", "company_size": "enterprise" },
      { "name": "Stripe", "industry": "Fintech", "company_size": "large" }
    ]
  }'
```

**Request Body:**

```json
{
  "companies": [
    {
      "name": "Google",
      "industry": "Technology",
      "company_size": "enterprise",
      "headquarters_country": "United States"
    },
    {
      "name": "Stripe",
      "industry": "Fintech",
      "company_size": "large",
      "headquarters_country": "United States"
    }
  ]
}
```

**Response `201 Created`:**

```json
{
  "created_or_updated": [
    { "name": "Google", "id": "a1b2c3d4-..." },
    { "name": "Stripe", "id": "d5e6f7a8-..." }
  ],
  "errors": []
}
```

**Response with partial failures:**

```json
{
  "created_or_updated": [
    { "name": "Google", "id": "a1b2c3d4-..." }
  ],
  "errors": [
    {
      "index": 1,
      "errors": { "company_size": ["\"huge\" is not a valid choice."] }
    }
  ]
}
```

### 5.3 List Companies

**`GET /api/v1/ingest/companies/`**

Returns all active companies. Useful for the crawler to check existing data before ingesting.

**Response `200 OK`:**

```json
[
  {
    "id": "a1b2c3d4-...",
    "name": "Google",
    "slug": "google",
    "industry": "Technology",
    ...
  }
]
```

---

## 6. Company Entity Ingest

### 6.1 Upsert a Single Entity

**`POST /api/v1/ingest/entities/`**

Creates or updates an entity keyed on `(company, display_name, operating_country)`.

> **Prerequisite:** The parent `Company` must already exist.

**Request Body:**

```json
{
  "company_name": "Google",
  "legal_name": "Google India Pvt Ltd",
  "display_name": "Google India",
  "operating_country": "India",
  "operating_city": "Bangalore",
  "is_headquarters": false,
  "is_indian_entity": true,
  "website": "https://careers.google.com/locations/bangalore/"
}
```

| Field               | Type    | Required | Notes                                                        |
|---------------------|---------|----------|--------------------------------------------------------------|
| `company_name`      | string  | **Yes**  | Must match an existing Company `name` (case-insensitive).    |
| `display_name`      | string  | **Yes**  | Short name for display, e.g., "Google India".                |
| `operating_country` | string  | **Yes**  | Country of operation.                                        |
| `legal_name`        | string  | No       | Registered legal entity name.                                |
| `operating_city`    | string  | No       | City of operation.                                           |
| `is_headquarters`   | boolean | No       | Default `false`.                                             |
| `is_indian_entity`  | boolean | No       | Default `false`. Quick filter for India.                     |
| `website`           | URL     | No       | Corporate website for this entity.                           |
| `is_active`         | boolean | No       | Default `true`.                                              |

**Response `201 Created`:**

```json
{
  "id": "b2c3d4e5-...",
  "company": "a1b2c3d4-...",
  "company_name": "Google",
  "legal_name": "Google India Pvt Ltd",
  "display_name": "Google India",
  "operating_country": "India",
  "operating_city": "Bangalore",
  "is_headquarters": false,
  "is_indian_entity": true,
  "website": "https://careers.google.com/locations/bangalore/",
  "is_active": true,
  "career_pages": [],
  "created_at": "2026-03-01T10:31:00Z",
  "updated_at": "2026-03-01T10:31:00Z"
}
```

**Error — company not found:**

```json
{
  "company_name": ["Company \"Gogle\" does not exist. Ingest the company first."]
}
```

### 6.2 Bulk Upsert Entities

**`POST /api/v1/ingest/entities/bulk/`**

**Request Body:**

```json
{
  "entities": [
    {
      "company_name": "Google",
      "display_name": "Google India",
      "operating_country": "India",
      "is_indian_entity": true
    },
    {
      "company_name": "Google",
      "display_name": "Google US",
      "operating_country": "United States",
      "is_headquarters": true
    }
  ]
}
```

**Response `201 Created`:**

```json
{
  "created_or_updated": [
    { "display_name": "Google India", "id": "b2c3d4e5-..." },
    { "display_name": "Google US", "id": "c3d4e5f6-..." }
  ],
  "errors": []
}
```

### 6.3 List Entities

**`GET /api/v1/ingest/entities/`**

**Query Parameters:**

| Param     | Type   | Description                          |
|-----------|--------|--------------------------------------|
| `company` | string | Filter by company name (case-insensitive) |

**Example:**

```
GET /api/v1/ingest/entities/?company=Google
```

**Response `200 OK`:**

```json
[
  {
    "id": "b2c3d4e5-...",
    "company": "a1b2c3d4-...",
    "company_name": "Google",
    "display_name": "Google India",
    "operating_country": "India",
    "career_pages": [
      {
        "id": "...",
        "url": "https://careers.google.com/locations/bangalore/",
        "label": "Engineering",
        "country": "India",
        "crawl_frequency": "weekly",
        "is_active": true,
        "last_crawled_at": null
      }
    ],
    ...
  }
]
```

---

## 7. Career Page Ingest

### Upsert a Career Page

**`POST /api/v1/ingest/career-pages/`**

Creates or updates a career page keyed on `(entity, url)`.

> **Prerequisite:** The parent `CompanyEntity` must already exist.

**Request Body:**

```json
{
  "company_name": "Google",
  "entity_display_name": "Google India",
  "entity_country": "India",
  "url": "https://careers.google.com/jobs/results/?location=Bangalore",
  "label": "Engineering",
  "country": "India",
  "crawl_frequency": "daily"
}
```

| Field                  | Type   | Required | Notes                                            |
|------------------------|--------|----------|--------------------------------------------------|
| `company_name`         | string | **Yes**  | Parent company name.                             |
| `entity_display_name`  | string | **Yes**  | Entity display name.                             |
| `entity_country`       | string | **Yes**  | Entity operating country.                        |
| `url`                  | URL    | **Yes**  | Career page URL. **Upsert key** (with entity).  |
| `label`                | string | No       | e.g., "Engineering", "All Roles", "Campus".      |
| `country`              | string | No       | Target country (may differ from entity country). |
| `crawl_frequency`      | string | No       | `daily` or `weekly` (default: `weekly`).         |
| `is_active`            | boolean| No       | Default `true`.                                  |

**Response `201 Created`:**

```json
{
  "id": "d4e5f6a7-...",
  "url": "https://careers.google.com/jobs/results/?location=Bangalore",
  "label": "Engineering"
}
```

---

## 8. Job Ingest

### 8.1 Upsert a Single Job

**`POST /api/v1/ingest/jobs/`**

Creates or updates a `DiscoveredJob` keyed on `(source, external_id)`.

**curl:**

```bash
curl -X POST https://<backend>.up.railway.app/api/v1/ingest/jobs/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "firecrawl",
    "external_id": "google-swe-123456",
    "url": "https://careers.google.com/jobs/123456/",
    "title": "Senior Software Engineer",
    "company": "Google",
    "location": "Bangalore, India",
    "skills_required": ["Python", "Go", "Kubernetes"],
    "seniority_level": "senior",
    "employment_type": "full_time",
    "remote_policy": "hybrid"
  }'
```

**Request Body:**

```json
{
  "source": "firecrawl",
  "external_id": "google-swe-123456",
  "url": "https://careers.google.com/jobs/results/123456/",
  "source_page_url": "https://careers.google.com/jobs/results/?location=Bangalore",
  "title": "Senior Software Engineer, Cloud Infrastructure",
  "company": "Google",
  "location": "Bangalore, India",
  "salary_range": "₹30L - ₹50L per annum",
  "description_snippet": "Design and build scalable cloud infrastructure services...",
  "skills_required": ["Python", "Go", "Kubernetes", "GCP", "Distributed Systems"],
  "skills_nice_to_have": ["Terraform", "Rust"],
  "experience_years_min": 5,
  "experience_years_max": 12,
  "employment_type": "full_time",
  "remote_policy": "hybrid",
  "seniority_level": "senior",
  "industry": "Technology",
  "education_required": "bachelor",
  "salary_min_usd": 36000,
  "salary_max_usd": 60000,
  "posted_at": "2026-02-28T00:00:00Z",
  "company_entity_display_name": "Google India",
  "company_entity_country": "India",
  "raw_data": { "full_html": "..." }
}
```

| Field                          | Type     | Required | Notes                                                    |
|--------------------------------|----------|----------|----------------------------------------------------------|
| `source`                       | string   | **Yes**  | Currently only `firecrawl`. Part of the upsert key.      |
| `external_id`                  | string   | **Yes**  | Unique ID from the source. Part of the upsert key.       |
| `url`                          | URL      | **Yes**  | Direct link to the job posting / apply page.             |
| `source_page_url`              | URL      | No       | The crawl page URL this was found on.                    |
| `title`                        | string   | No       | Job title.                                               |
| `company`                      | string   | No       | Company name (free text).                                |
| `location`                     | string   | No       | Job location.                                            |
| `salary_range`                 | string   | No       | Raw salary text from listing.                            |
| `description_snippet`          | string   | No       | Short excerpt of the JD.                                 |
| `skills_required`              | string[] | No       | Required skills extracted by LLM.                        |
| `skills_nice_to_have`          | string[] | No       | Nice-to-have/preferred skills.                           |
| `experience_years_min`         | integer  | No       | Minimum years of experience.                             |
| `experience_years_max`         | integer  | No       | Maximum years of experience.                             |
| `employment_type`              | string   | No       | One of: `full_time`, `part_time`, `contract`, `internship`, `freelance`. |
| `remote_policy`                | string   | No       | One of: `onsite`, `hybrid`, `remote`.                    |
| `seniority_level`              | string   | No       | One of: `intern`, `junior`, `mid`, `senior`, `lead`, `manager`, `director`, `executive`. |
| `industry`                     | string   | No       | e.g., "Technology", "Finance".                           |
| `education_required`           | string   | No       | e.g., "bachelor", "master", "none".                      |
| `salary_min_usd`               | integer  | No       | LLM-normalised annual lower bound in USD.                |
| `salary_max_usd`               | integer  | No       | LLM-normalised annual upper bound in USD.                |
| `posted_at`                    | datetime | No       | When the job was posted (ISO 8601).                      |
| `raw_data`                     | object   | No       | Full raw API response for debugging.                     |
| `company_entity_display_name`  | string   | No       | Display name of `CompanyEntity` to link. Non-fatal if not found. |
| `company_entity_country`       | string   | No       | Operating country of the entity. Required if display_name given. |

**Response `201 Created`:**

```json
{
  "id": "e5f6a7b8-...",
  "source": "firecrawl",
  "external_id": "google-swe-123456",
  "title": "Senior Software Engineer, Cloud Infrastructure"
}
```

### 8.2 Bulk Upsert Jobs

**`POST /api/v1/ingest/jobs/bulk/`**

Ingest up to **500 jobs** in a single request.

**curl:**

```bash
curl -X POST https://<backend>.up.railway.app/api/v1/ingest/jobs/bulk/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [
      {
        "source": "firecrawl",
        "external_id": "google-swe-123",
        "url": "https://careers.google.com/123/",
        "title": "Senior SWE",
        "company": "Google",
        "skills_required": ["Python"]
      },
      {
        "source": "firecrawl",
        "external_id": "stripe-be-456",
        "url": "https://stripe.com/jobs/456",
        "title": "Backend Engineer",
        "company": "Stripe",
        "skills_required": ["Ruby"]
      }
    ]
  }'
```

**Request Body:**

```json
{
  "jobs": [
    {
      "source": "firecrawl",
      "external_id": "google-swe-123456",
      "url": "https://careers.google.com/jobs/results/123456/",
      "title": "Senior Software Engineer",
      "company": "Google",
      "location": "Bangalore, India",
      "skills_required": ["Python", "Go"],
      "seniority_level": "senior",
      "employment_type": "full_time",
      "remote_policy": "hybrid"
    },
    {
      "source": "firecrawl",
      "external_id": "stripe-be-789012",
      "url": "https://stripe.com/jobs/listing/789012",
      "title": "Backend Engineer",
      "company": "Stripe",
      "location": "Remote",
      "skills_required": ["Ruby", "PostgreSQL"],
      "seniority_level": "mid",
      "employment_type": "full_time",
      "remote_policy": "remote"
    }
  ]
}
```

**Response `201 Created`:**

```json
{
  "ingested": 2,
  "failed": 0,
  "results": [
    { "id": "e5f6a7b8-...", "external_id": "google-swe-123456", "title": "Senior Software Engineer" },
    { "id": "f6a7b8c9-...", "external_id": "stripe-be-789012", "title": "Backend Engineer" }
  ],
  "errors": []
}
```

**Response with partial failures:**

```json
{
  "ingested": 1,
  "failed": 1,
  "results": [
    { "id": "e5f6a7b8-...", "external_id": "google-swe-123456", "title": "Senior Software Engineer" }
  ],
  "errors": [
    {
      "index": 1,
      "errors": { "url": ["Enter a valid URL."] }
    }
  ]
}
```

**Limits:**

| Constraint       | Value |
|------------------|-------|
| Max jobs per bulk | 500   |

---

## 9. Crawl Sources

Crawl sources are managed via Django Admin. The crawler reads them to know which URLs to crawl.

### 9.1 List Active Crawl Sources

**`GET /api/v1/ingest/crawl-sources/`**

Returns all active crawl sources, ordered by priority (lower = more important).

**Response `200 OK`:**

```json
[
  {
    "id": "f7a8b9c0-...",
    "name": "LinkedIn",
    "source_type": "job_board",
    "url_template": "https://www.linkedin.com/jobs/search/?keywords={query}&location={location}&f_TPR=r86400",
    "is_active": true,
    "priority": 1,
    "last_crawled_at": "2026-02-28T06:00:00Z"
  },
  {
    "id": "a8b9c0d1-...",
    "name": "Google Careers India",
    "source_type": "company",
    "url_template": "https://careers.google.com/jobs/results/?location=India",
    "is_active": true,
    "priority": 5,
    "last_crawled_at": null
  }
]
```

**Source types:**

| Type        | `url_template` format                                   |
|-------------|--------------------------------------------------------|
| `job_board` | Has `{query}` and `{location}` placeholders            |
| `company`   | Plain career page URL — no placeholders                |

For `job_board` sources, the crawler should replace `{query}` and `{location}` with values from the user's `JobSearchProfile`.

### 9.2 Update Crawl Source After Crawl

**`PATCH /api/v1/ingest/crawl-sources/<uuid:id>/`**

Report that a crawl source was successfully crawled.

**Request Body:**

```json
{
  "last_crawled_at": "2026-03-01T06:15:00Z"
}
```

**Response `200 OK`:**

```json
{
  "id": "f7a8b9c0-...",
  "name": "LinkedIn",
  "source_type": "job_board",
  "url_template": "...",
  "is_active": true,
  "priority": 1,
  "last_crawled_at": "2026-03-01T06:15:00Z"
}
```

---

## 10. Ingestion Order & Dependencies

The models have foreign key dependencies. **Always ingest in this order:**

```
 Step 1       Step 2              Step 3               Step 4
┌──────┐    ┌───────────┐    ┌──────────────┐    ┌──────────────┐
│Company│ ──►│CompanyEntity│ ──►│CompanyCareerPage│    │DiscoveredJob│
└──────┘    └───────────┘    └──────────────┘    └──────────────┘
                  │                                       ▲
                  └──────────────── optional FK ───────────┘
```

| Step | Endpoint                   | Depends On       | Notes                             |
|------|----------------------------|------------------|-----------------------------------|
| 1    | `POST /ingest/companies/`  | —                | Must be first                     |
| 2    | `POST /ingest/entities/`   | Company          | Requires `company_name`           |
| 3    | `POST /ingest/career-pages/`| CompanyEntity   | Requires entity + company names   |
| 4    | `POST /ingest/jobs/`       | (optional entity) | Can link to entity, but not required |

**Jobs can be ingested without company/entity data.** The `company` field on `DiscoveredJob` is a plain text string. The `company_entity` FK is optional — if `company_entity_display_name` doesn't match an existing entity, the job is still saved successfully.

### Recommended Crawl Pipeline

```python
async def run_crawl_pipeline(client: IngestClient):
    # 1. Get crawl sources
    sources = client.get_crawl_sources()

    for source in sources:
        # 2. Crawl the URL
        raw_jobs = crawl_url(source['url_template'])

        # 3. Extract unique companies
        companies = extract_companies(raw_jobs)
        if companies:
            client.ingest_companies_bulk(companies)

        # 4. Extract entities (if available)
        entities = extract_entities(raw_jobs)
        if entities:
            client.ingest_entities_bulk(entities)

        # 5. Ingest jobs in batches of 100
        for batch in chunk(raw_jobs, 100):
            client.ingest_jobs_bulk(batch)

        # 6. Mark source as crawled
        client.update_crawl_source(
            source['id'],
            datetime.utcnow().isoformat() + 'Z',
        )
```

---

## 11. Error Handling

### HTTP Status Codes

| Status | Meaning                                        |
|--------|------------------------------------------------|
| `200`  | Success (GET, PATCH)                           |
| `201`  | Created / upserted (POST)                      |
| `400`  | Validation error — check `errors` in response  |
| `401`  | Missing `X-Crawler-Key` header                 |
| `403`  | Invalid `X-Crawler-Key`                        |
| `404`  | Resource not found (e.g., CrawlSource ID)      |
| `429`  | Rate limited — retry after backoff             |
| `500`  | Server error — retry with exponential backoff  |

### Validation Error Format

All validation errors follow DRF's standard format:

```json
{
  "field_name": ["Error message 1.", "Error message 2."],
  "other_field": ["Error message."]
}
```

### Retry Strategy

```python
import time

def ingest_with_retry(client, method, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return method(*args, **kwargs)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code in (429, 500, 502, 503):
                wait = 2 ** attempt  # 1, 2, 4 seconds
                time.sleep(wait)
                continue
            raise
    raise Exception(f"Failed after {max_retries} retries")
```

---

## 12. Rate Limiting

Ingest endpoints are **exempt from rate limiting** (`throttle_classes = []`). They are already protected by the `X-Crawler-Key` secret, so no additional throttling is applied.

The crawler bot can make unlimited requests. However, for performance, prefer bulk endpoints over many single-item requests:

| Strategy | Recommendation |
|----------|---------------|
| Companies | Use `/companies/bulk/` for 2+ companies |
| Entities | Use `/entities/bulk/` for 2+ entities |
| Jobs | Use `/jobs/bulk/` (up to 500 per request) in batches of 100 |

---

## 13. Data Model Reference

For full field-level documentation of all models, see [job_company.md](job_company.md).

### Summary

| Model               | Table                           | Upsert Key                                  |
|----------------------|---------------------------------|---------------------------------------------|
| `Company`            | `analyzer_company`              | `name`                                      |
| `CompanyEntity`      | `analyzer_companyentity`        | `(company, display_name, operating_country)` |
| `CompanyCareerPage`  | `analyzer_companycareerpage`    | `(entity, url)`                             |
| `DiscoveredJob`      | `analyzer_discoveredjob`        | `(source, external_id)`                     |
| `CrawlSource`        | `analyzer_crawlsource`         | Admin-managed, read-only via API            |
| `UserCompanyFollow`  | `analyzer_usercompanyfollow`    | User-facing, not ingested by crawler        |

### Enum Reference

**`company_size` choices:**

| Value        | Label              |
|--------------|--------------------|
| `startup`    | Startup (1-50)     |
| `small`      | Small (51-200)     |
| `mid`        | Mid-size (201-1000)|
| `large`      | Large (1001-10000) |
| `enterprise` | Enterprise (10000+)|

**`employment_type` choices:**

| Value        | Label       |
|--------------|-------------|
| `full_time`  | Full Time   |
| `part_time`  | Part Time   |
| `contract`   | Contract    |
| `internship` | Internship  |
| `freelance`  | Freelance   |

**`remote_policy` choices:**

| Value    | Label    |
|----------|----------|
| `onsite` | On-site  |
| `hybrid` | Hybrid   |
| `remote` | Remote   |

**`seniority_level` choices:**

| Value       | Label      |
|-------------|------------|
| `intern`    | Intern     |
| `junior`    | Junior     |
| `mid`       | Mid-level  |
| `senior`    | Senior     |
| `lead`      | Lead       |
| `manager`   | Manager    |
| `director`  | Director   |
| `executive` | Executive  |

**`source` choices (DiscoveredJob):**

| Value       | Label     |
|-------------|-----------|
| `firecrawl` | Firecrawl |

**`crawl_frequency` choices:**

| Value    | Label   |
|----------|---------|
| `daily`  | Daily   |
| `weekly` | Weekly  |

**`source_type` choices (CrawlSource):**

| Value        | Label               |
|--------------|---------------------|
| `job_board`  | Job Board           |
| `company`    | Company Career Page |

---

## 14. Full Workflow Example

End-to-end example of a crawler bot ingesting company + job data:

```python
from datetime import datetime, timezone
from ingest_client import IngestClient  # Your client module

client = IngestClient(
    base_url="https://your-backend.up.railway.app/api/v1/ingest",
    api_key="your-strong-random-secret-here",
)

# 0. Verify connectivity
assert client.ping()["status"] == "ok"

# 1. Ingest companies
client.ingest_companies_bulk([
    {
        "name": "Google",
        "industry": "Technology",
        "company_size": "enterprise",
        "headquarters_country": "United States",
        "headquarters_city": "Mountain View",
        "tech_stack": ["Python", "Go", "Java", "C++"],
    },
    {
        "name": "Stripe",
        "industry": "Fintech",
        "company_size": "large",
        "headquarters_country": "United States",
        "headquarters_city": "San Francisco",
        "tech_stack": ["Ruby", "Go", "Scala"],
    },
])

# 2. Ingest entities
client.ingest_entities_bulk([
    {
        "company_name": "Google",
        "display_name": "Google India",
        "operating_country": "India",
        "operating_city": "Bangalore",
        "is_indian_entity": True,
    },
    {
        "company_name": "Stripe",
        "display_name": "Stripe India",
        "operating_country": "India",
        "operating_city": "Bangalore",
        "is_indian_entity": True,
    },
])

# 3. Ingest career pages
client.ingest_career_page({
    "company_name": "Google",
    "entity_display_name": "Google India",
    "entity_country": "India",
    "url": "https://careers.google.com/jobs/results/?location=India",
    "label": "All Roles",
    "crawl_frequency": "daily",
})

# 4. Get crawl sources and crawl
sources = client.get_crawl_sources()
for source in sources:
    jobs = crawl_source(source)  # Your crawl logic

    # 5. Bulk ingest jobs
    result = client.ingest_jobs_bulk([
        {
            "source": "firecrawl",
            "external_id": f"{job['id']}",
            "url": job["url"],
            "title": job["title"],
            "company": job["company_name"],
            "location": job["location"],
            "skills_required": job.get("skills", []),
            "seniority_level": job.get("seniority", ""),
            "employment_type": job.get("type", "full_time"),
            "remote_policy": job.get("remote", ""),
            "description_snippet": job.get("snippet", ""),
            "company_entity_display_name": job.get("entity_name", ""),
            "company_entity_country": job.get("entity_country", ""),
        }
        for job in jobs
    ])
    print(f"Ingested {result['ingested']} jobs, {result['failed']} failed")

    # 6. Update crawl source timestamp
    client.update_crawl_source(
        source["id"],
        datetime.now(timezone.utc).isoformat(),
    )
```

---

## 15. Environment Variables

### Backend (i-Luffy) — Required

| Variable          | Description                                | Example                          |
|-------------------|--------------------------------------------|----------------------------------|
| `CRAWLER_API_KEY` | Shared secret for `X-Crawler-Key` header   | `sk_crawl_a1b2c3d4e5f6...`      |

### Crawler Bot Service — Required

| Variable          | Description                                | Example                                                |
|-------------------|--------------------------------------------|--------------------------------------------------------|
| `CRAWLER_API_KEY` | Same shared secret as the backend          | `sk_crawl_a1b2c3d4e5f6...`                            |
| `INGEST_BASE_URL` | Full URL to the ingest API                 | `https://your-app.up.railway.app/api/v1/ingest`       |

### Generating a Secure Key

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## 16. Quick Reference — All Endpoints

| Method  | Endpoint                                   | Description                           | Auth            |
|---------|--------------------------------------------|---------------------------------------|-----------------|
| `GET`   | `/api/v1/ingest/ping/`                     | Auth check / health                   | `X-Crawler-Key` |
| `GET`   | `/api/v1/ingest/companies/`                | List active companies                 | `X-Crawler-Key` |
| `POST`  | `/api/v1/ingest/companies/`                | Upsert a single company               | `X-Crawler-Key` |
| `POST`  | `/api/v1/ingest/companies/bulk/`           | Bulk upsert companies                 | `X-Crawler-Key` |
| `GET`   | `/api/v1/ingest/entities/`                 | List entities (filter by `?company=`)  | `X-Crawler-Key` |
| `POST`  | `/api/v1/ingest/entities/`                 | Upsert a single entity                | `X-Crawler-Key` |
| `POST`  | `/api/v1/ingest/entities/bulk/`            | Bulk upsert entities                  | `X-Crawler-Key` |
| `POST`  | `/api/v1/ingest/career-pages/`             | Upsert a career page                  | `X-Crawler-Key` |
| `POST`  | `/api/v1/ingest/jobs/`                     | Upsert a single discovered job        | `X-Crawler-Key` |
| `POST`  | `/api/v1/ingest/jobs/bulk/`                | Bulk upsert jobs (max 500)            | `X-Crawler-Key` |
| `GET`   | `/api/v1/ingest/crawl-sources/`            | List active crawl sources             | `X-Crawler-Key` |
| `PATCH` | `/api/v1/ingest/crawl-sources/<uuid:id>/`  | Update `last_crawled_at`              | `X-Crawler-Key` |
