# Job & Company Related Models

All models live in `analyzer/models.py`.

---

## 1. `Company`

Top-level brand / parent company (e.g., Google, Infosys, Stripe).

| Field                  | Type                        | Constraints / Notes                                      |
|------------------------|-----------------------------|----------------------------------------------------------|
| `id`                   | `UUIDField` (PK)            | Auto-generated                                           |
| `name`                 | `CharField(255)`            | **Unique**. Brand / common name                          |
| `slug`                 | `SlugField(255)`            | **Unique**. URL-safe, auto-generated from name           |
| `description`          | `TextField`                 | Blank allowed. Brief company description                 |
| `logo`                 | `URLField(2048)`            | Blank allowed. URL to logo image                         |
| `industry`             | `CharField(100)`            | Blank allowed                                            |
| `founded_year`         | `PositiveSmallIntegerField`  | Nullable                                                 |
| `company_size`         | `CharField(12)`             | Choices: `startup`, `small`, `mid`, `large`, `enterprise`|
| `headquarters_country` | `CharField(100)`            | Blank allowed                                            |
| `headquarters_city`    | `CharField(100)`            | Blank allowed                                            |
| `linkedin_url`         | `URLField(2048)`            | Blank allowed                                            |
| `glassdoor_url`        | `URLField(2048)`            | Blank allowed                                            |
| `tech_stack`           | `JSONField` (list)          | e.g. `["Python", "Kubernetes"]`                          |
| `is_active`            | `BooleanField`              | Default `True`. Inactive = hidden from suggestions       |
| `created_at`           | `DateTimeField`             | Auto                                                     |
| `updated_at`           | `DateTimeField`             | Auto                                                     |

**Ordering:** `name`

---

## 2. `CompanyEntity`

A legal / operating entity of a Company in a specific country (e.g., "Stripe Inc" in US, "Stripe India Pvt Ltd" in India).

| Field               | Type                   | Constraints / Notes                                           |
|----------------------|------------------------|---------------------------------------------------------------|
| `id`                 | `UUIDField` (PK)       | Auto-generated                                                |
| `company`            | `FK → Company`         | `on_delete=CASCADE`, `related_name='entities'`                |
| `legal_name`         | `CharField(500)`       | Blank allowed. Registered legal name                          |
| `display_name`       | `CharField(255)`       | Short display name (e.g. "Google India")                      |
| `operating_country`  | `CharField(100)`       | Country this entity operates in                               |
| `operating_city`     | `CharField(100)`       | Blank allowed                                                 |
| `is_headquarters`    | `BooleanField`         | Whether this entity is the global HQ                          |
| `is_indian_entity`   | `BooleanField`         | Indexed. Quick filter for Indian entities                     |
| `website`            | `URLField(2048)`       | Blank allowed. Corporate website for this entity              |
| `is_active`          | `BooleanField`         | Default `True`                                                |
| `created_at`         | `DateTimeField`        | Auto                                                          |
| `updated_at`         | `DateTimeField`        | Auto                                                          |

**Unique constraint:** `(company, operating_country, display_name)`  
**Indexes:** `(company, operating_country)`, `(is_indian_entity)`  
**Ordering:** `company`, `operating_country`

---

## 3. `CompanyCareerPage`

Career page URL belonging to a `CompanyEntity`. One entity can have multiple career pages.

| Field              | Type                   | Constraints / Notes                                         |
|--------------------|------------------------|-------------------------------------------------------------|
| `id`               | `UUIDField` (PK)       | Auto-generated                                              |
| `entity`           | `FK → CompanyEntity`   | `on_delete=CASCADE`, `related_name='career_pages'`          |
| `url`              | `URLField(2048)`       | Career page URL                                             |
| `label`            | `CharField(100)`       | Blank allowed. e.g. "Engineering", "All Roles", "Campus"    |
| `country`          | `CharField(100)`       | Blank allowed. May differ from entity country                |
| `is_active`        | `BooleanField`         | Default `True`, indexed                                     |
| `last_crawled_at`  | `DateTimeField`        | Nullable                                                    |
| `crawl_frequency`  | `CharField(10)`        | Choices: `daily`, `weekly` (default: `weekly`)               |
| `created_at`       | `DateTimeField`        | Auto                                                        |
| `updated_at`       | `DateTimeField`        | Auto                                                        |

**Ordering:** `entity`, `label`

---

## 4. `CrawlSource`

Admin-managed crawl source — defines a job board or company career page for the daily crawl.

| Field              | Type                        | Constraints / Notes                                                 |
|--------------------|-----------------------------|---------------------------------------------------------------------|
| `id`               | `UUIDField` (PK)            | Auto-generated                                                      |
| `name`             | `CharField(100)`            | **Unique**. Display name                                            |
| `source_type`      | `CharField(20)`             | Choices: `job_board`, `company`                                     |
| `url_template`     | `CharField(2048)`           | URL template with `{query}` / `{location}` placeholders             |
| `is_active`        | `BooleanField`              | Default `True`, indexed                                             |
| `priority`         | `PositiveSmallIntegerField`  | Default `10`. Lower = crawled first                                 |
| `last_crawled_at`  | `DateTimeField`             | Nullable                                                            |
| `created_at`       | `DateTimeField`             | Auto                                                                |
| `updated_at`       | `DateTimeField`             | Auto                                                                |

**Ordering:** `priority`, `name`

---

## 5. `JobSearchProfile`

LLM-extracted job search criteria from a resume. One profile per resume.

| Field              | Type                        | Constraints / Notes                                           |
|--------------------|-----------------------------|---------------------------------------------------------------|
| `resume`           | `OneToOne → Resume` (PK)    | `on_delete=CASCADE`, `related_name='job_search_profile'`      |
| `titles`           | `JSONField` (list)          | Target job titles                                             |
| `skills`           | `JSONField` (list)          | Key skills extracted                                          |
| `seniority`        | `CharField(20)`             | Choices: `junior`, `mid`, `senior`, `lead`, `executive`       |
| `industries`       | `JSONField` (list)          | Target industries                                             |
| `locations`        | `JSONField` (list)          | Preferred work locations                                      |
| `experience_years` | `PositiveSmallIntegerField`  | Nullable. Years of experience inferred                        |
| `raw_extraction`   | `JSONField`                 | Nullable. Full LLM output for debugging                       |
| `embedding`        | `VectorField(1536)`         | Nullable. pgvector. Resume embedding for similarity matching  |
| `created_at`       | `DateTimeField`             | Auto                                                          |
| `updated_at`       | `DateTimeField`             | Auto                                                          |

**Ordering:** `-updated_at`

---

## 6. `JobAlert`

A user's job alert subscription linked to a specific resume.

| Field          | Type                   | Constraints / Notes                                                       |
|----------------|------------------------|---------------------------------------------------------------------------|
| `id`           | `UUIDField` (PK)       | Auto-generated                                                            |
| `user`         | `FK → User`            | `on_delete=CASCADE`, `related_name='job_alerts'`                          |
| `resume`       | `FK → Resume`          | `on_delete=PROTECT`, `related_name='job_alerts'`                          |
| `frequency`    | `CharField(10)`        | Choices: `daily`, `weekly` (default: `weekly`)                            |
| `is_active`    | `BooleanField`         | Default `True`, indexed                                                   |
| `preferences`  | `JSONField` (dict)     | Keys: `remote_ok`, `location`, `salary_min`, `excluded_companies`, `priority_companies` |
| `last_run_at`  | `DateTimeField`        | Nullable                                                                  |
| `next_run_at`  | `DateTimeField`        | Nullable, indexed                                                         |
| `created_at`   | `DateTimeField`        | Auto                                                                      |
| `updated_at`   | `DateTimeField`        | Auto                                                                      |

**Indexes:** `(user, -created_at)`, `(is_active, next_run_at)`  
**Ordering:** `-created_at`  
**Method:** `set_next_run()` — computes `next_run_at` based on `frequency`

---

## 7. `DiscoveredJob`

A job posting discovered from an external source. Global (not per-user). Deduplicated by `(source, external_id)`.

| Field                  | Type                        | Constraints / Notes                                              |
|------------------------|-----------------------------|------------------------------------------------------------------|
| `id`                   | `UUIDField` (PK)            | Auto-generated                                                   |
| `source`               | `CharField(30)`             | Choices: `firecrawl`. Indexed                                    |
| `external_id`          | `CharField(255)`            | Unique job ID from the source API                                |
| `source_page_url`      | `URLField(2048)`            | Blank. Search/career page URL crawled                            |
| `url`                  | `URLField(2048)`            | Direct link to job posting / apply page                          |
| `title`                | `CharField(500)`            | Blank allowed                                                    |
| `company`              | `CharField(255)`            | Blank allowed. Company name string                               |
| `company_entity`       | `FK → CompanyEntity`        | Nullable. `on_delete=SET_NULL`, `related_name='discovered_jobs'` |
| `location`             | `CharField(255)`            | Blank allowed                                                    |
| `salary_range`         | `CharField(255)`            | Blank allowed                                                    |
| `description_snippet`  | `TextField`                 | Blank allowed. Short excerpt                                     |
| `skills_required`      | `JSONField` (list)          | Required skills extracted by LLM                                 |
| `skills_nice_to_have`  | `JSONField` (list)          | Nice-to-have / preferred skills                                  |
| `experience_years_min` | `PositiveSmallIntegerField`  | Nullable                                                         |
| `experience_years_max` | `PositiveSmallIntegerField`  | Nullable                                                         |
| `employment_type`      | `CharField(15)`             | Choices: `full_time`, `part_time`, `contract`, `internship`, `freelance` |
| `remote_policy`        | `CharField(10)`             | Choices: `onsite`, `hybrid`, `remote`                            |
| `seniority_level`      | `CharField(12)`             | Choices: `intern`, `junior`, `mid`, `senior`, `lead`, `manager`, `director`, `executive` |
| `industry`             | `CharField(100)`            | Blank, indexed                                                   |
| `education_required`   | `CharField(50)`             | Blank. e.g. "bachelor", "master", "none"                         |
| `salary_min_usd`       | `PositiveIntegerField`       | Nullable. LLM-normalised annual lower bound (USD)                |
| `salary_max_usd`       | `PositiveIntegerField`       | Nullable. LLM-normalised annual upper bound (USD)                |
| `posted_at`            | `DateTimeField`             | Nullable                                                         |
| `raw_data`             | `JSONField`                 | Nullable. Full raw API response                                  |
| `embedding`            | `VectorField(1536)`         | Nullable. pgvector. Job listing embedding                        |
| `created_at`           | `DateTimeField`             | Auto                                                             |

**Unique constraint:** `(source, external_id)`  
**Indexes:** `(source, external_id)`, `(-created_at)`  
**Ordering:** `-created_at`

---

## 8. `JobMatch`

Junction between `JobAlert` and `DiscoveredJob`. Stores LLM relevance score and user feedback.

| Field              | Type                   | Constraints / Notes                                        |
|--------------------|------------------------|------------------------------------------------------------|
| `id`               | `UUIDField` (PK)       | Auto-generated                                             |
| `job_alert`        | `FK → JobAlert`        | `on_delete=CASCADE`, `related_name='matches'`              |
| `discovered_job`   | `FK → DiscoveredJob`   | `on_delete=CASCADE`, `related_name='matches'`              |
| `relevance_score`  | `PositiveSmallIntegerField` | 0–100                                                 |
| `match_reason`     | `TextField`            | Blank. LLM-generated explanation                           |
| `user_feedback`    | `CharField(15)`        | Choices: `pending`, `relevant`, `irrelevant`, `applied`, `dismissed`. Default: `pending` |
| `feedback_reason`  | `TextField`            | Blank. User-provided reason (for learning loop)            |
| `created_at`       | `DateTimeField`        | Auto                                                       |

**Unique constraint:** `(job_alert, discovered_job)`  
**Indexes:** `(job_alert, -relevance_score)`, `(job_alert, user_feedback)`  
**Ordering:** `-relevance_score`, `-created_at`

---

## 9. `JobAlertRun`

Audit log entry for each discovery + matching pipeline run for a `JobAlert`.

| Field                | Type                        | Constraints / Notes                                      |
|----------------------|-----------------------------|----------------------------------------------------------|
| `id`                 | `UUIDField` (PK)            | Auto-generated                                           |
| `job_alert`          | `FK → JobAlert`             | `on_delete=CASCADE`, `related_name='runs'`               |
| `jobs_discovered`    | `PositiveIntegerField`       | Default `0`                                              |
| `jobs_matched`       | `PositiveIntegerField`       | Default `0`                                              |
| `notification_sent`  | `BooleanField`              | Default `False`                                          |
| `credits_used`       | `PositiveSmallIntegerField`  | Default `0`                                              |
| `credits_deducted`   | `BooleanField`              | Default `False`. For idempotent refund                   |
| `error_message`      | `TextField`                 | Blank allowed                                            |
| `duration_seconds`   | `FloatField`                | Nullable                                                 |
| `created_at`         | `DateTimeField`             | Auto                                                     |

**Indexes:** `(job_alert, -created_at)`  
**Ordering:** `-created_at`

---

## 10. `SentAlert`

Deduplication log — prevents resending the same job to the same user on the same channel.

| Field            | Type                   | Constraints / Notes                                       |
|------------------|------------------------|-----------------------------------------------------------|
| `id`             | `UUIDField` (PK)       | Auto-generated                                            |
| `user`           | `FK → User`            | `on_delete=CASCADE`, `related_name='sent_alerts'`         |
| `discovered_job` | `FK → DiscoveredJob`   | `on_delete=CASCADE`, `related_name='sent_alerts'`         |
| `channel`        | `CharField(20)`        | Choices: `email`, `in_app`                                |
| `sent_at`        | `DateTimeField`        | Auto                                                      |

**Ordering:** `-sent_at`

---

## 11. `UserCompanyFollow`

Global per-user company preference (follow / block). Set once, applies across all job alerts.

| Field        | Type                   | Constraints / Notes                                    |
|--------------|------------------------|--------------------------------------------------------|
| `id`         | `UUIDField` (PK)       | Auto-generated                                         |
| `user`       | `FK → User`            | `on_delete=CASCADE`, `related_name='company_follows'`  |
| `company`    | `FK → Company`         | `on_delete=CASCADE`, `related_name='followers'`        |
| `relation`   | `CharField(10)`        | Choices: `follow`, `block`. Default: `follow`          |
| `created_at` | `DateTimeField`        | Auto                                                   |

**Unique constraint:** `(user, company)`  
**Indexes:** `(user, relation)`  
**Ordering:** `-created_at`

---

## Relationships Diagram

```
Company  1──*  CompanyEntity  1──*  CompanyCareerPage
   │                │
   │                │ (optional FK)
   │                ▼
   │          DiscoveredJob
   │                ▲
   │                │ (via JobMatch)
   └──*  UserCompanyFollow ──* User
                                │
User  1──*  JobAlert  *──*  DiscoveredJob
              │                  │
              │                  └──*  SentAlert ──* User
              ├──*  JobAlertRun
              └──1  Resume ──1  JobSearchProfile

CrawlSource (standalone, admin-managed)
```
