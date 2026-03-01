# Crawler Bot — Ingest API Configuration Guide

> **Service:** `resume_ai_backend_job_bot` (Crawler Bot)
> **Last updated:** 2026-03-01
> **Purpose:** This document tells i-Luffy how to push company, career page, and job data **into** the Crawler Bot's ingest API.

---

## 1. Base URL

```
Development:  http://localhost:8000/api/ingest
Production:   https://<crawler-bot>.up.railway.app/api/ingest
```

All endpoints are prefixed with `/api/ingest/`.

---

## 2. Authentication

All ingest endpoints use a **shared secret** passed via the `X-Crawler-Key` HTTP header. No JWT or session auth is needed.

| Header           | Required | Description                                      |
|------------------|----------|--------------------------------------------------|
| `X-Crawler-Key`  | **Yes**  | Must match `CRAWLER_API_KEY` env var on both sides |
| `Content-Type`   | **Yes**  | Must be `application/json` for POST requests       |

### Setting the Key

Both services must share the same secret:

```env
# In the Crawler Bot (.env)
CRAWLER_API_KEY=your-strong-random-secret-here

# In i-Luffy (.env)
CRAWLER_API_KEY=your-strong-random-secret-here
```

Generate a key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Auth Error Responses

| Status | Meaning                          |
|--------|----------------------------------|
| `403`  | Missing or invalid `X-Crawler-Key` |

```json
{
  "detail": "Invalid X-Crawler-Key."
}
```

---

## 3. Quick Reference — All Endpoints

| Method | Endpoint                         | Description                     |
|--------|----------------------------------|---------------------------------|
| `GET`  | `/api/ingest/ping/`              | Auth check / health             |
| `GET`  | `/api/ingest/companies/`         | List all active companies       |
| `POST` | `/api/ingest/companies/`         | Upsert a single company         |
| `POST` | `/api/ingest/companies/bulk/`    | Bulk upsert companies           |
| `POST` | `/api/ingest/career-pages/`      | Upsert a single career page     |
| `GET`  | `/api/ingest/jobs/`              | List active jobs (latest 100)   |
| `POST` | `/api/ingest/jobs/`              | Upsert a single job             |
| `POST` | `/api/ingest/jobs/bulk/`         | Bulk upsert jobs (max 500)      |

**No rate limiting** — endpoints are exempt. The `X-Crawler-Key` auth is sufficient.

**All writes are idempotent** — re-sending the same data updates the existing record, no duplicates.

---

## 4. Ping / Health Check

### `GET /api/ingest/ping/`

Verify authentication is working.

```bash
curl -H "X-Crawler-Key: your-secret" \
  https://<crawler-bot>/api/ingest/ping/
```

**Response `200 OK`:**

```json
{
  "status": "ok",
  "service": "crawler-bot-ingest",
  "timestamp": "2026-03-01T10:30:00.000000+00:00"
}
```

---

## 5. Company Ingest

### 5.1 Upsert a Single Company

### `POST /api/ingest/companies/`

Creates or updates a company. **Upsert key:** `domain` (primary) or `name` (fallback), both case-insensitive.

```bash
curl -X POST https://<crawler-bot>/api/ingest/companies/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Google",
    "domain": "google.com",
    "industry": "Technology",
    "company_size": "enterprise",
    "headquarters_country": "United States",
    "headquarters_city": "Mountain View",
    "tech_stack": ["Python", "Go", "Java", "Kubernetes"]
  }'
```

#### Request Body — Company Fields

| Field                  | Type     | Required             | Notes                                                          |
|------------------------|----------|----------------------|----------------------------------------------------------------|
| `name`                 | string   | **Yes** (for create) | Company brand name. Case-insensitive upsert key.              |
| `domain`               | string   | Recommended          | Primary domain without protocol (e.g. `google.com`). Unique. Auto-generated from name if omitted. |
| `legal_name`           | string   | No                   | Registered legal entity name.                                  |
| `website`              | URL      | No                   | Full website URL (e.g. `https://google.com`).                  |
| `logo_url`             | URL      | No                   | URL to logo image. Also accepts `logo` as alias. Auto-set via Clearbit if blank. |
| `description`          | string   | No                   | Brief company description.                                     |
| `tagline`              | string   | No                   | Company tagline (max 500 chars).                               |
| `industry`             | string   | No                   | e.g. "Technology", "Finance", "Healthcare".                    |
| `sub_industry`         | string   | No                   | e.g. "Cloud Computing", "Payments".                            |
| `company_type`         | string   | No                   | One of: `product`, `service`, `product_and_service`, `consulting`, `startup`, `psu`, `government`. |
| `company_size`         | string   | No                   | One of: `startup`, `small`, `mid`, `large`, `enterprise`.      |
| `employee_count_raw`   | string   | No                   | Raw employee count text (e.g. "10,000+").                      |
| `founded_year`         | integer  | No                   | e.g. 1998.                                                     |
| `headquarters_city`    | string   | No                   | e.g. "Mountain View".                                          |
| `headquarters_state`   | string   | No                   | e.g. "California".                                             |
| `headquarters_country` | string   | No                   | e.g. "United States", "India".                                 |
| `is_indian_company`    | boolean  | No                   | Default `false`.                                               |
| `has_india_office`     | boolean  | No                   | Default `false`.                                               |
| `india_cities`         | string[] | No                   | Indian cities with offices (e.g. `["Bangalore", "Hyderabad"]`).|
| `linkedin_url`         | URL      | No                   | LinkedIn company page URL.                                     |
| `twitter_url`          | URL      | No                   | Twitter/X profile URL.                                         |
| `glassdoor_url`        | URL      | No                   | Glassdoor overview URL.                                        |
| `crunchbase_url`       | URL      | No                   | Crunchbase profile URL.                                        |
| `tech_stack`           | string[] | No                   | e.g. `["Python", "Kubernetes", "PostgreSQL"]`.                 |
| `products`             | string[] | No                   | e.g. `["Google Search", "Gmail", "GCP"]`.                      |
| `is_public`            | boolean  | No                   | Default `false`. Is the company publicly traded?               |
| `stock_ticker`         | string   | No                   | e.g. "GOOGL".                                                  |
| `stock_exchange`       | string   | No                   | e.g. "NASDAQ".                                                 |
| `funding_stage`        | string   | No                   | e.g. "Series C", "IPO", "Bootstrapped".                       |
| `is_active`            | boolean  | No                   | Default `true`. Set `false` to hide.                           |

**Response `201 Created`:**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Google",
  "slug": "google",
  "domain": "google.com",
  "industry": "Technology",
  "company_size": "enterprise",
  "headquarters_country": "United States",
  "headquarters_city": "Mountain View",
  "is_active": true,
  "created_at": "2026-03-01T10:30:00+00:00",
  "updated_at": "2026-03-01T10:30:00+00:00"
}
```

### 5.2 Bulk Upsert Companies

### `POST /api/ingest/companies/bulk/`

```bash
curl -X POST https://<crawler-bot>/api/ingest/companies/bulk/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "companies": [
      { "name": "Google", "domain": "google.com", "industry": "Technology" },
      { "name": "Stripe", "domain": "stripe.com", "industry": "Fintech" }
    ]
  }'
```

**Request Body:**

```json
{
  "companies": [
    { /* same fields as single company */ },
    { /* ... */ }
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
      "errors": { "name": ["This field is required."] }
    }
  ]
}
```

### 5.3 List Companies

### `GET /api/ingest/companies/`

Returns all active companies.

```bash
curl -H "X-Crawler-Key: your-secret" \
  https://<crawler-bot>/api/ingest/companies/
```

**Response `200 OK`:**

```json
[
  {
    "id": "a1b2c3d4-...",
    "name": "Google",
    "slug": "google",
    "domain": "google.com",
    "industry": "Technology",
    "company_size": "enterprise",
    "headquarters_country": "United States",
    "headquarters_city": "Mountain View",
    "is_active": true,
    "created_at": "2026-03-01T10:30:00+00:00",
    "updated_at": "2026-03-01T10:30:00+00:00"
  }
]
```

---

## 6. Career Page Ingest

### `POST /api/ingest/career-pages/`

Creates or updates a career page. **Upsert key:** `(company_name, url)`.

> **Prerequisite:** The parent Company must already exist.

```bash
curl -X POST https://<crawler-bot>/api/ingest/career-pages/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "Google",
    "url": "https://careers.google.com/jobs/results/?location=India",
    "label": "India Engineering",
    "country": "India",
    "region": "india",
    "crawl_frequency": "daily",
    "is_primary": true
  }'
```

#### Request Body — Career Page Fields

| Field               | Type    | Required | Notes                                                              |
|---------------------|---------|----------|--------------------------------------------------------------------|
| `company_name`      | string  | **Yes**  | Must match an existing Company `name` (case-insensitive).          |
| `url`               | URL     | **Yes**  | Career page URL. Part of the upsert key (with company).           |
| `label`             | string  | No       | Descriptive label (e.g. "Engineering", "India", "All Roles").      |
| `country`           | string  | No       | Target country for this page.                                      |
| `region`            | string  | No       | One of: `india`, `us`, `europe`, `global`. Default: `global`. Determines crawl window. |
| `is_primary`        | boolean | No       | Default `false`. Is this the main careers page?                    |
| `is_india_specific` | boolean | No       | Default `false`. Is this an India-specific careers page?           |
| `is_active`         | boolean | No       | Default `true`.                                                    |
| `crawl_frequency`   | string  | No       | Default `weekly`. Options: `hourly`, `every_6h`, `every_12h`, `daily`, `weekly`, `biweekly`, `monthly`. |
| `ats_platform`      | string  | No       | ATS platform name (e.g. "Greenhouse", "Lever", "Workday").        |

**Response `201 Created`:**

```json
{
  "id": "d4e5f6a7-...",
  "url": "https://careers.google.com/jobs/results/?location=India",
  "label": "India Engineering",
  "company": "Google"
}
```

**Error — company not found:**

```json
{
  "company_name": ["Company \"Gogle\" does not exist. Ingest the company first."]
}
```

---

## 7. Job Ingest

### 7.1 Upsert a Single Job

### `POST /api/ingest/jobs/`

Creates or updates a job. **Upsert key:** `job_url` (also accepts `url`).

If the company name doesn't match an existing record, a **skeleton company** is auto-created for later enrichment.

```bash
curl -X POST https://<crawler-bot>/api/ingest/jobs/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://careers.google.com/jobs/123456/",
    "title": "Senior Software Engineer",
    "company": "Google",
    "location": "Bangalore, India",
    "skills_required": ["Python", "Go", "Kubernetes"],
    "seniority_level": "senior",
    "employment_type": "full_time",
    "remote_policy": "hybrid",
    "experience_years_min": 5,
    "experience_years_max": 12,
    "salary_range": "₹30L - ₹50L per annum",
    "description_snippet": "Design and build scalable cloud infrastructure..."
  }'
```

#### Request Body — Job Fields

| Field                   | Type     | Required | Notes                                                            |
|-------------------------|----------|----------|------------------------------------------------------------------|
| `url` or `job_url`      | URL      | **Yes**  | Direct link to the job posting. **Upsert key** (unique).        |
| `title`                 | string   | **Yes**  | Job title. **Junk titles are auto-rejected** (see §9).          |
| `company` or `company_name` | string | **Yes** | Company name. Auto-creates skeleton if not found.               |
| `source_type`           | string   | No       | `career_page` or `job_listing_site`. Default: `career_page`.    |
| `external_id`           | string   | No       | Job ID from source (e.g. "REQ-12345").                          |
| `location`              | string   | No       | Location as text (e.g. "Bangalore, India"). Stored as JSON array. |
| `locations`             | array    | No       | Structured locations: `[{"city":"...","state":"...","country":"...","is_india":true}]`. Overrides `location` if both sent. |
| `remote_policy`         | string   | No       | One of: `onsite`, `hybrid`, `remote`.                           |
| `employment_type`       | string   | No       | One of: `full_time`, `part_time`, `contract`, `internship`, `freelance`. |
| `seniority_level`       | string   | No       | One of: `intern`, `junior`, `mid`, `senior`, `lead`, `manager`, `director`, `executive`. |
| `education_required`    | string   | No       | One of: `none`, `diploma`, `bachelor`, `master`, `phd`.         |
| `experience_years_min`  | integer  | No       | Minimum years of experience.                                     |
| `experience_years_max`  | integer  | No       | Maximum years of experience.                                     |
| `team_or_department`    | string   | No       | e.g. "Engineering", "Data Science".                              |
| `business_unit`         | string   | No       | e.g. "Google Cloud", "YouTube".                                  |
| `description_full`      | string   | No       | Full job description (plain text, HTML is stripped).             |
| `description_snippet`   | string   | No       | Short excerpt (max 500 chars).                                   |
| `responsibilities`      | string[] | No       | List of responsibility bullet points.                            |
| `skills_required`       | string[] | No       | Required skills (e.g. `["Python", "Django"]`).                  |
| `skills_nice_to_have`   | string[] | No       | Preferred skills.                                                |
| `tools_and_technologies`| string[] | No       | Specific tools/tech mentioned.                                   |
| `certifications_required` | string[] | No     | Required certifications.                                         |
| `salary_range` or `salary_range_raw` | string | No | Raw salary text (e.g. "₹30L-50L", "$120K-$160K").         |
| `salary_currency`       | string   | No       | e.g. "INR", "USD", "EUR".                                       |
| `salary_min_usd`        | number   | No       | Annual lower bound in USD.                                       |
| `salary_max_usd`        | number   | No       | Annual upper bound in USD.                                       |
| `industry`              | string   | No       | e.g. "Technology", "Finance".                                    |
| `functional_area`       | string   | No       | e.g. "Backend", "DevOps", "Data Engineering".                   |
| `posted_at`             | datetime | No       | ISO 8601 (e.g. `"2026-02-28T00:00:00Z"`).                       |
| `apply_url`             | URL      | No       | Direct application link (if different from `url`).              |
| `benefits`              | string[] | No       | e.g. `["Health Insurance", "RSU", "Relocation"]`.               |
| `visa_sponsorship`      | boolean  | No       | Does the company sponsor visas?                                  |
| `diversity_commitment`  | boolean  | No       | Does the posting mention diversity/inclusion?                    |
| `is_active`             | boolean  | No       | Default `true`. Set `false` to deactivate.                      |
| `source_page_url`       | URL      | No       | The career page URL this job was found on. Auto-links to CareerPage FK if matched. |
| `raw_data`              | object   | No       | Full raw extraction response for debugging/re-processing.       |

**Response `201 Created`:**

```json
{
  "id": "e5f6a7b8-...",
  "title": "Senior Software Engineer",
  "job_url": "https://careers.google.com/jobs/123456/",
  "company": "Google",
  "external_id": "",
  "is_active": true
}
```

### 7.2 Bulk Upsert Jobs

### `POST /api/ingest/jobs/bulk/`

Ingest up to **500 jobs** in a single request.

```bash
curl -X POST https://<crawler-bot>/api/ingest/jobs/bulk/ \
  -H "X-Crawler-Key: your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [
      {
        "url": "https://careers.google.com/123/",
        "title": "Senior SWE",
        "company": "Google",
        "skills_required": ["Python"]
      },
      {
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
    { /* same fields as single job */ },
    { /* ... */ }
  ]
}
```

**Response `201 Created`:**

```json
{
  "ingested": 2,
  "failed": 0,
  "results": [
    { "id": "e5f6a7b8-...", "external_id": "", "title": "Senior SWE" },
    { "id": "f6a7b8c9-...", "external_id": "", "title": "Backend Engineer" }
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
    { "id": "e5f6a7b8-...", "external_id": "", "title": "Senior SWE" }
  ],
  "errors": [
    {
      "index": 1,
      "errors": { "url": ["This field is required."] }
    }
  ]
}
```

| Constraint        | Value |
|-------------------|-------|
| Max jobs per bulk | 500   |

### 7.3 List Jobs

### `GET /api/ingest/jobs/`

Returns the latest 100 active jobs.

```bash
curl -H "X-Crawler-Key: your-secret" \
  https://<crawler-bot>/api/ingest/jobs/
```

**Response `200 OK`:**

```json
[
  {
    "id": "e5f6a7b8-...",
    "title": "Senior Software Engineer",
    "job_url": "https://careers.google.com/jobs/123456/",
    "company": "Google",
    "external_id": "",
    "is_active": true
  }
]
```

---

## 8. Ingestion Order & Dependencies

Companies must exist before career pages can reference them. Jobs auto-create skeleton companies if needed.

```
 Step 1          Step 2              Step 3
┌─────────┐    ┌──────────────┐    ┌──────────────┐
│ Company │ ──►│ Career Page  │    │    Job        │
└─────────┘    └──────────────┘    └──────────────┘
      │                                   ▲
      └────── auto-created if missing ────┘
```

| Step | Endpoint                       | Depends On | Notes                                           |
|------|--------------------------------|------------|-------------------------------------------------|
| 1    | `POST /api/ingest/companies/`  | —          | Should be first                                  |
| 2    | `POST /api/ingest/career-pages/` | Company  | Requires `company_name` matching existing company |
| 3    | `POST /api/ingest/jobs/`       | —          | Auto-creates skeleton Company if not found       |

**Recommended flow:**

```
1. Push companies   →  POST /api/ingest/companies/bulk/
2. Push career pages →  POST /api/ingest/career-pages/  (for each)
3. Push jobs         →  POST /api/ingest/jobs/bulk/
```

Jobs can be pushed independently without step 1-2 — the company will be auto-created as a skeleton entry.

---

## 9. Junk Title Filtering

Jobs with error/placeholder titles are **automatically rejected** at ingest time. This prevents crawl artefacts from empty/404 career pages (e.g. Fanduel, Grantstreet).

**Rejected title patterns include:**

| Pattern                              | Example                                     |
|--------------------------------------|---------------------------------------------|
| `sorry, we couldn't find`            | "Sorry, we couldn't find anything here"     |
| `page not found`                     | "Page Not Found"                            |
| `404`                                | "404 - Not Found"                           |
| `access denied`                      | "Access Denied"                             |
| `no results found`                   | "No Results Found"                          |
| `nothing here`                       | "Oops, nothing here"                        |
| `something went wrong`               | "Something went wrong"                      |
| `no positions available`             | "No positions available at this time"       |
| `job not found`                      | "Job Not Found"                             |
| `could not be found`                 | "This page could not be found"              |
| `no longer available`                | "This position is no longer available"      |
| Empty or < 3 characters              | `""`, `"ab"`                                |

**Response when a junk title is rejected (status `400`):**

```json
{
  "title": ["Junk title rejected: \"Sorry, we couldn't find anything here\""]
}
```

In bulk requests, junk titles cause that individual job to fail (counted in `failed`), but other jobs in the batch still succeed.

---

## 10. Enum Reference

### `company_size`

| Value        | Label              |
|--------------|--------------------|
| `startup`    | Startup (<50)      |
| `small`      | Small (50-200)     |
| `mid`        | Mid (200-1,000)    |
| `large`      | Large (1,000-5,000)|
| `enterprise` | Enterprise (5,000+)|

### `company_type`

| Value                  | Label              |
|------------------------|--------------------|
| `product`              | Product            |
| `service`              | Service            |
| `product_and_service`  | Product & Service  |
| `consulting`           | Consulting         |
| `startup`              | Startup            |
| `psu`                  | PSU                |
| `government`           | Government         |

### `employment_type`

| Value        | Label       |
|--------------|-------------|
| `full_time`  | Full-time   |
| `part_time`  | Part-time   |
| `contract`   | Contract    |
| `internship` | Internship  |
| `freelance`  | Freelance   |

### `remote_policy`

| Value    | Label   |
|----------|---------|
| `onsite` | Onsite  |
| `hybrid` | Hybrid  |
| `remote` | Remote  |

### `seniority_level`

| Value       | Label     |
|-------------|-----------|
| `intern`    | Intern    |
| `junior`    | Junior    |
| `mid`       | Mid       |
| `senior`    | Senior    |
| `lead`      | Lead      |
| `manager`   | Manager   |
| `director`  | Director  |
| `executive` | Executive |

### `education_required`

| Value     | Label    |
|-----------|----------|
| `none`    | None     |
| `diploma` | Diploma  |
| `bachelor`| Bachelor |
| `master`  | Master   |
| `phd`     | PhD      |

### `source_type`

| Value              | Label                |
|--------------------|----------------------|
| `career_page`      | Company Career Page  |
| `job_listing_site`  | Job Listing Site     |

### `region` (Career Page)

| Value    | Label           |
|----------|-----------------|
| `india`  | India           |
| `us`     | United States   |
| `europe` | Europe          |
| `global` | Global / Other  |

### `crawl_frequency`

| Value       | Interval    |
|-------------|-------------|
| `hourly`    | Every 1h    |
| `every_6h`  | Every 6h    |
| `every_12h` | Every 12h   |
| `daily`     | Every 24h   |
| `weekly`    | Every 7d    |
| `biweekly`  | Every 14d   |
| `monthly`   | Every 30d   |

---

## 11. Error Handling

### HTTP Status Codes

| Status | Meaning                                        |
|--------|------------------------------------------------|
| `200`  | Success (GET)                                  |
| `201`  | Created / upserted (POST)                      |
| `400`  | Validation error — check response body          |
| `403`  | Missing or invalid `X-Crawler-Key`              |
| `500`  | Server error — retry with exponential backoff  |

### Validation Error Format

All validation errors follow DRF standard format:

```json
{
  "field_name": ["Error message 1.", "Error message 2."],
  "other_field": ["Error message."]
}
```

### Retry Strategy

```python
import time
import requests

def ingest_with_retry(session, url, payload, max_retries=3):
    for attempt in range(max_retries):
        try:
            resp = session.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code in (429, 500, 502, 503):
                wait = 2 ** attempt  # 1, 2, 4 seconds
                time.sleep(wait)
                continue
            raise
    raise Exception(f"Failed after {max_retries} retries")
```

---

## 12. Python Client Example

```python
import requests

class CrawlerBotClient:
    """HTTP client for pushing data to the Crawler Bot ingest API."""

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

    def push_company(self, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}/companies/", json=data)
        resp.raise_for_status()
        return resp.json()

    def push_companies_bulk(self, companies: list[dict]) -> dict:
        resp = self.session.post(
            f"{self.base_url}/companies/bulk/",
            json={"companies": companies},
        )
        resp.raise_for_status()
        return resp.json()

    def push_career_page(self, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}/career-pages/", json=data)
        resp.raise_for_status()
        return resp.json()

    def push_job(self, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}/jobs/", json=data)
        resp.raise_for_status()
        return resp.json()

    def push_jobs_bulk(self, jobs: list[dict]) -> dict:
        resp = self.session.post(
            f"{self.base_url}/jobs/bulk/",
            json={"jobs": jobs},
        )
        resp.raise_for_status()
        return resp.json()

    def list_companies(self) -> list[dict]:
        resp = self.session.get(f"{self.base_url}/companies/")
        resp.raise_for_status()
        return resp.json()

    def list_jobs(self) -> list[dict]:
        resp = self.session.get(f"{self.base_url}/jobs/")
        resp.raise_for_status()
        return resp.json()
```

### Usage

```python
from datetime import datetime, timezone

client = CrawlerBotClient(
    base_url="https://<crawler-bot>.up.railway.app/api/ingest",
    api_key="your-strong-random-secret-here",
)

# 0. Verify connectivity
assert client.ping()["status"] == "ok"

# 1. Push companies
client.push_companies_bulk([
    {
        "name": "Google",
        "domain": "google.com",
        "industry": "Technology",
        "company_size": "enterprise",
        "headquarters_country": "United States",
        "headquarters_city": "Mountain View",
        "tech_stack": ["Python", "Go", "Java"],
        "is_indian_company": False,
        "has_india_office": True,
        "india_cities": ["Bangalore", "Hyderabad", "Gurgaon"],
    },
    {
        "name": "Stripe",
        "domain": "stripe.com",
        "industry": "Fintech",
        "company_size": "large",
        "headquarters_country": "United States",
    },
])

# 2. Push career pages
client.push_career_page({
    "company_name": "Google",
    "url": "https://careers.google.com/jobs/results/?location=India",
    "label": "India — All Roles",
    "country": "India",
    "region": "india",
    "crawl_frequency": "daily",
    "is_primary": True,
    "is_india_specific": True,
})

# 3. Push jobs in batches
result = client.push_jobs_bulk([
    {
        "url": "https://careers.google.com/jobs/123/",
        "title": "Senior Software Engineer, Cloud",
        "company": "Google",
        "location": "Bangalore, India",
        "skills_required": ["Python", "Go", "Kubernetes"],
        "seniority_level": "senior",
        "employment_type": "full_time",
        "remote_policy": "hybrid",
        "experience_years_min": 5,
        "experience_years_max": 12,
        "salary_range": "₹30L - ₹50L per annum",
        "description_snippet": "Design and build scalable cloud infrastructure...",
        "source_page_url": "https://careers.google.com/jobs/results/?location=India",
    },
    {
        "url": "https://stripe.com/jobs/456/",
        "title": "Backend Engineer",
        "company": "Stripe",
        "location": "Remote",
        "skills_required": ["Ruby", "PostgreSQL"],
        "seniority_level": "mid",
        "employment_type": "full_time",
        "remote_policy": "remote",
    },
])
print(f"Ingested {result['ingested']} jobs, {result['failed']} failed")
```

---

## 13. Environment Variables

### Crawler Bot — Required

| Variable           | Description                                 | Example                                                  |
|--------------------|---------------------------------------------|----------------------------------------------------------|
| `CRAWLER_API_KEY`  | Shared secret for `X-Crawler-Key` header    | `sk_crawl_a1b2c3d4e5f6...`                              |

### i-Luffy — Required

| Variable           | Description                                 | Example                                                  |
|--------------------|---------------------------------------------|----------------------------------------------------------|
| `CRAWLER_API_KEY`  | Same shared secret as the crawler bot       | `sk_crawl_a1b2c3d4e5f6...`                              |
| `CRAWLER_BOT_INGEST_URL` | Full URL to the crawler bot ingest API | `https://<crawler-bot>.up.railway.app/api/ingest`        |

---

## 14. Data Model Summary

| Model       | DB Table             | Upsert Key              | Primary Key |
|-------------|----------------------|--------------------------|-------------|
| `Company`   | `companies_company`  | `domain` or `name`       | UUID v4     |
| `CareerPage`| `companies_careerpage` | `(company, url)`       | UUID v4     |
| `Job`       | `jobs_job`           | `job_url`                | UUID v4     |

All models have:
- `id` — UUID v4 primary key (auto-generated)
- `created_at` — auto-set on creation
- `updated_at` — auto-set on every save

---

## 15. Important Notes

1. **Idempotent upserts** — Re-sending the same data just updates the existing record. No duplicates are created.

2. **Skeleton companies** — When a job references a company that doesn't exist, a minimal Company record is auto-created (`name` + auto-generated `domain`). The crawler bot will enrich it later.

3. **Junk title auto-rejection** — Jobs with error-page titles (404s, "Sorry, we couldn't find...", etc.) are rejected with HTTP 400. This is intentional — those are crawl artefacts, not real jobs.

4. **`last_seen_at` auto-set** — Every job upsert sets `last_seen_at` to now. Jobs whose `last_seen_at` goes stale (>30 days) are automatically deactivated by the crawler's `expire_stale_jobs` task.

5. **Career page linking** — If a job is pushed with a `source_page_url` that matches an existing CareerPage record, the FK relationship is auto-linked.

6. **No rate limiting** — Ingest endpoints have no throttle. Push as fast as you need.
