# Code Review — Resume AI with Luffy

> **Reviewed:** 2026-02-24
> **Scope:** Full backend + mobile codebase
> **Branch:** `claude/code-review-analysis-ZMaaA`

---

## Table of Contents

1. [Bugs](#1-bugs)
2. [Security Issues](#2-security-issues)
3. [Design & Architecture Issues](#3-design--architecture-issues)
4. [Minor Issues](#4-minor-issues)
5. [Missing / Unimplemented Features](#5-missing--unimplemented-features)

---

## 1. Bugs

---

### BUG-01 — `JDFetcher` always instantiated, breaking all analysis types when Firecrawl is unconfigured

| Field | Detail |
|---|---|
| **File** | `analyzer/services/analyzer.py` |
| **Line** | 38 |
| **Severity** | High |

**What it does now**

`ResumeAnalyzer.__init__` unconditionally creates a `JDFetcher` instance on every analysis run, regardless of which JD input type the user chose.

```python
def __init__(self):
    self.pdf_extractor = PDFExtractor()
    self.jd_fetcher = JDFetcher()   # ← always runs
    self.ai_provider = get_ai_provider()
```

**The issue**

`JDFetcher.__init__` (`jd_fetcher.py:19–21`) raises `ValueError('FIRECRAWL_API_KEY must be configured.')` if `FIRECRAWL_API_KEY` is absent from the environment. Since `ResumeAnalyzer()` is constructed inside the Celery task for every single analysis, **all analyses fail** — including those with `jd_input_type=text` or `jd_input_type=form` that never call Firecrawl at all — whenever the key is missing. The error is silently stored as the analysis error message, making it hard to diagnose.

**Possible fix**

Instantiate `JDFetcher` lazily inside `_step_jd_scrape`, only when `jd_input_type == JD_INPUT_URL`:

```python
def _step_jd_scrape(self, analysis, step_name):
    if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_URL:
        fetcher = JDFetcher()   # only now
        ...
```

Remove `self.jd_fetcher = JDFetcher()` from `__init__`.

---

### BUG-02 — `LogoutView` can return 500 if `refresh` token is missing from request body

| Field | Detail |
|---|---|
| **File** | `accounts/views.py` |
| **Lines** | 70–71 |
| **Severity** | Medium |

**What it does now**

```python
def post(self, request):
    try:
        refresh_token = request.data.get('refresh')
        token = RefreshToken(refresh_token)   # called with None if key absent
        token.blacklist()
        return Response({'detail': 'Successfully logged out.'}, ...)
    except TokenError:
        return Response({'detail': 'Invalid token.'}, status=400)
```

**The issue**

If a client sends `POST /api/auth/logout/` without a `refresh` key in the body, `request.data.get('refresh')` returns `None`. `RefreshToken(None)` may raise `TokenError` (which is caught) but depending on the simplejwt version it can also raise `TypeError` or `ValueError`, which are NOT caught, resulting in a 500 Internal Server Error.

**Possible fix**

Add an explicit check before instantiating the token:

```python
refresh_token = request.data.get('refresh')
if not refresh_token:
    return Response({'detail': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)
token = RefreshToken(refresh_token)
```

---

### BUG-03 — `save_user_profile` signal fires an extra DB write on every `User.save()`

| Field | Detail |
|---|---|
| **File** | `accounts/models.py` |
| **Lines** | 244–248 |
| **Severity** | Medium |

**What it does now**

```python
@receiver(post_save, sender=User)
def save_user_profile(sender, instance, created, **kwargs):
    """Ensure profile is saved whenever user is saved."""
    if hasattr(instance, 'profile'):
        instance.profile.save()
```

**The issue**

This signal fires on **every** `User.save()` call — password changes, token rotation, profile updates, admin edits — and unconditionally calls `instance.profile.save()`. This is:

- A redundant write on every user save
- A potential cascading loop if `UserProfile.save()` triggers its own signals
- Misleading: the docstring says "ensure profile is saved" but `create_user_profile` already handles creation; there is no scenario where this additional save is needed

**Possible fix**

Remove this signal entirely. `create_user_profile` (lines 234–241) already calls `get_or_create`, which covers the creation case. If specific profile sync is needed on user field changes, do it explicitly where those fields are changed (e.g., in the serializer `save()` method) rather than via a blanket signal.

---

### BUG-04 — Account deletion iterates analyses in a Python loop (N+1 DB operations)

| Field | Detail |
|---|---|
| **File** | `accounts/views.py` |
| **Lines** | 119–121 |
| **Severity** | Medium |

**What it does now**

```python
for analysis in ResumeAnalysis.objects.filter(user=user):
    analysis.soft_delete()
```

`soft_delete()` issues multiple sequential DB writes per analysis (clear fields, nullify FK relations, delete R2 file). For a user with 100 analyses this is 300+ sequential DB operations inside a single synchronous HTTP request.

**The issue**

The HTTP response is blocked until all soft-deletes complete. As the user grows, this endpoint becomes progressively slower and can eventually time out, leaving the account in a partially-deleted state.

**Possible fix**

Separate the bulk field-clearing (which can use `QuerySet.update()`) from the side-effect work (R2 file deletion, orphan cleanup):

```python
from django.utils import timezone

now = timezone.now()
analyses = ResumeAnalysis.objects.filter(user=user)

# Bulk clear heavy fields in one query
analyses.update(
    deleted_at=now,
    resume_text='',
    resolved_jd='',
    jd_text='',
)

# Handle R2 file cleanup and orphaned FK rows asynchronously
# e.g. dispatch a cleanup task: cleanup_user_files_task.delay(user_id)
```

---

### BUG-05 — `validate_ai_response` does not enforce that `quick_wins` contains exactly 3 items

| Field | Detail |
|---|---|
| **File** | `analyzer/services/ai_providers/base.py` |
| **Lines** | 167–172 |
| **Severity** | Low |

**What it does now**

```python
for i, qw in enumerate(data['quick_wins']):
    if not isinstance(qw, dict):
        raise ValueError(...)
    for k in ('priority', 'action'):
        if k not in qw:
            raise ValueError(...)
```

Only validates that each entry is a dict with `priority` and `action`. The count is never checked. Additionally, scores are validated with `isinstance(v, (int, float))` but the schema specifies integers.

**The issue**

The prompt instructs the LLM to return exactly 3 quick wins. If the model returns 0, 2, or 5, the validation passes silently. Score values like `72.5` (float) are stored instead of `72` (int), causing type inconsistency in the frontend.

**Possible fix**

```python
if len(data['quick_wins']) != 3:
    raise ValueError(
        f'AI response "quick_wins" must contain exactly 3 items, got {len(data["quick_wins"])}'
    )

# Coerce scores to int
for k in _REQUIRED_SCORES_FIELDS:
    scores[k] = int(round(scores[k]))
```

---

### BUG-06 — Idempotency lock is never explicitly released on Celery task failure

| Field | Detail |
|---|---|
| **File** | `analyzer/views.py` |
| **Lines** | 52–53, 60–74 |
| **Severity** | Low |

**What it does now**

```python
lock_key = f'analyze_lock:{request.user.id}'
if not cache.add(lock_key, 1, self.IDEMPOTENCY_LOCK_TTL):  # 30 seconds
    return Response({'detail': '...'}, status=409)

try:
    analysis = serializer.save(...)
    run_analysis_task.delay(...)
    return Response({'id': analysis.id, 'status': ...}, status=202)
except Exception:
    cache.delete(lock_key)   # released only on exception in the VIEW, not in the TASK
    raise
```

**The issue**

The lock is released if the view raises an exception, but NOT if the Celery task fails quickly (within the 30-second TTL). A user whose analysis fails in < 30 seconds receives a 409 Conflict on their next submission attempt, forcing them to wait for the TTL to expire before retrying.

**Possible fix**

Delete the lock key at the start of `run_analysis_task`:

```python
@shared_task(...)
def run_analysis_task(self, analysis_id, user_id):
    cache.delete(f'analyze_lock:{user_id}')   # release submission lock
    ...
```

---

## 2. Security Issues

---

### SEC-01 — `SharedAnalysisView` has no throttling

| Field | Detail |
|---|---|
| **File** | `analyzer/views.py` |
| **Lines** | 439–441 |
| **Severity** | High |

**What it does now**

```python
class SharedAnalysisView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = []  # comment says "uses default AnonRateThrottle from settings"
    authentication_classes = []
```

**The issue**

Setting `throttle_classes = []` **overrides and disables** the default `AnonRateThrottle` set in `REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES']`. The comment is incorrect — an explicit empty list is not the same as using the default. This endpoint is public (no auth), so it is completely open to enumeration and scraping of shared analysis data without any rate limiting.

**Possible fix**

Remove the `throttle_classes = []` line to inherit the default, or set it explicitly:

```python
from rest_framework.throttling import AnonRateThrottle

class SharedAnalysisView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    authentication_classes = []
```

---

### SEC-02 — Share URL returned as a relative path, not an absolute URL

| Field | Detail |
|---|---|
| **Files** | `analyzer/views.py:403`, `analyzer/serializers.py:219–222`, `analyzer/serializers.py:253–255` |
| **Severity** | Medium |

**What it does now**

```python
'share_url': f'/api/shared/{analysis.share_token}/'
```

**The issue**

The `share_url` in all API responses is a relative path. A recipient of a shared link who receives `/api/shared/<token>/` cannot use it without knowing the API server's base URL. It is also inconsistent with how most REST APIs return URIs — they should be absolute so clients do not need to reconstruct them.

**Possible fix**

Use Django's `request.build_absolute_uri()`:

```python
def get_share_url(self, obj):
    if obj.share_token:
        request = self.context.get('request')
        path = f'/api/shared/{obj.share_token}/'
        return request.build_absolute_uri(path) if request else path
    return None
```

Pass `context={'request': request}` when instantiating the serializer in the view (already done for create serializers; add for detail and list serializers too).

---

### SEC-03 — `ScrapeResult` cache lookup is cross-user

| Field | Detail |
|---|---|
| **File** | `analyzer/services/jd_fetcher.py` |
| **Lines** | 66–71 |
| **Severity** | Low |

**What it does now**

```python
if user:
    cached = ScrapeResult.find_cached(url)   # no user filter
```

`ScrapeResult.find_cached()` (models.py:107–116) filters only by `source_url` and `status`, not by `user`. A scrape result owned by User A will be returned as a cache hit for User B.

**The issue**

User B's `ResumeAnalysis.scrape_result` FK ends up pointing to a row owned by User A. If `ScrapeResult` rows are ever surfaced in user-facing admin views or per-user queries, User B would appear to own a scrape they didn't create. More importantly, if User A's scrape failed to extract key fields, User B silently inherits that bad data.

**Possible fix**

Either scope the cache lookup to the current user, or copy the `ScrapeResult` row for the new user rather than sharing the reference:

```python
cached = ScrapeResult.find_cached(url, user=user)
```

```python
@classmethod
def find_cached(cls, url, user=None, max_age_hours=24):
    qs = cls.objects.filter(source_url=url, status=cls.STATUS_DONE, created_at__gte=cutoff)
    if user:
        qs = qs.filter(user=user)
    return qs.order_by('-created_at').first()
```

---

### SEC-04 — `CORS_ALLOW_ALL_ORIGINS + CORS_ALLOW_CREDENTIALS` misconfiguration footgun

| Field | Detail |
|---|---|
| **File** | `resume_ai/settings.py` |
| **Lines** | 262–267 |
| **Severity** | Low |

**What it does now**

```python
if _cors_raw.strip() == '*':
    CORS_ALLOW_ALL_ORIGINS = True
# ...
CORS_ALLOW_CREDENTIALS = True   # always set, regardless
```

**The issue**

Per the CORS specification, a server cannot respond with both `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Credentials: true`. Browsers reject such responses for credentialed requests. If an operator sets `CORS_ALLOWED_ORIGINS=*` in production expecting it to work with JWT cookie/header auth, credentialed requests will be silently blocked by browsers with no clear error.

**Possible fix**

Guard `CORS_ALLOW_CREDENTIALS` so it is only enabled when specific origins are listed:

```python
if _cors_raw.strip() == '*':
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOW_CREDENTIALS = False  # cannot combine with wildcard
else:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_raw.split(',') if o.strip()]
    CORS_ALLOW_CREDENTIALS = True
```

---

### SEC-05 — No email verification on registration

| Field | Detail |
|---|---|
| **File** | `accounts/views.py` |
| **Lines** | 38–57 |
| **Severity** | Low |

**What it does now**

`RegisterView` creates the user, immediately issues JWT tokens, and sends a welcome email — all without verifying that the user owns the email address.

**The issue**

Users can register with any email address (including someone else's). This means:
- Notification emails and password reset links are sent to potentially unverified addresses
- Password reset flow can be triggered for accounts with incorrect email addresses
- No way to distinguish verified from unverified users downstream

**Possible fix**

After registration, send a verification email with a one-time token (similar to the existing `password-reset` template/flow) and require verification before allowing analysis submissions. The `EmailTemplate` and `send_templated_email` infrastructure already supports this — only the token generation and verification endpoint need to be added.

---

## 3. Design & Architecture Issues

---

### ARCH-01 — Plan quotas and feature flags are never enforced

| Field | Detail |
|---|---|
| **File** | `accounts/models.py:173–210`, all view files |
| **Severity** | High |

**What it does now**

The `Plan` model defines comprehensive limits:

```python
analyses_per_month  = models.IntegerField(default=0)
max_resumes_stored  = models.IntegerField(default=5)
max_resume_size_mb  = models.IntegerField(default=5)
pdf_export          = models.BooleanField(default=True)
share_analysis      = models.BooleanField(default=True)
job_tracking        = models.BooleanField(default=True)
priority_queue      = models.BooleanField(default=False)
email_support       = models.BooleanField(default=False)
```

**The issue**

None of these fields are checked anywhere in the application. Every user — regardless of plan — can submit unlimited analyses, store unlimited resumes, export PDFs, share results, and track jobs. The plan system is purely cosmetic infrastructure.

**Possible fix**

Add a plan enforcement layer in the view or serializer. Example for `AnalyzeResumeView`:

```python
def post(self, request):
    plan = getattr(request.user.profile, 'plan', None)
    if plan and plan.analyses_per_month > 0:
        # Count this month's analyses
        from django.utils import timezone
        start_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = ResumeAnalysis.objects.filter(
            user=request.user,
            created_at__gte=start_of_month,
        ).count()
        if used >= plan.analyses_per_month:
            return Response(
                {'detail': f'Monthly analysis limit ({plan.analyses_per_month}) reached.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
    ...
```

Similarly check `share_analysis` before `AnalysisShareView.post()`, `pdf_export` before `AnalysisPDFExportView.get()`, etc.

---

### ARCH-02 — `ResumeAnalysis` duplicates the resume file reference

| Field | Detail |
|---|---|
| **File** | `analyzer/models.py:195–200`, `analyzer/serializers.py:140–156` |
| **Severity** | Medium |

**What it does now**

`ResumeAnalysis` has both:

```python
resume_file = models.FileField(upload_to='resumes/')   # direct file reference
resume      = models.ForeignKey(Resume, ...)           # deduplicated Resume FK
```

When `resume_id` is provided (reuse path), the serializer sets:

```python
validated_data['resume_file'] = resume_obj.file.name   # string path, not a file object
```

**The issue**

Both `resume_file` and `resume.file` point to the same R2 object. The `resume_file` field is redundant once the `resume` FK exists. Storing a raw string path on a `FileField` (by assigning `resume_obj.file.name`) bypasses Django's file field upload machinery and is an undocumented behavior that could break across Django versions.

**Possible fix**

Long-term: remove `ResumeAnalysis.resume_file` and update `PDFExtractor.extract()` (and the pipeline) to use `analysis.resume.file` directly. A migration can backfill `resume` for any historical analyses where it is null. Short-term: document the string-path assignment pattern prominently in the serializer.

---

### ARCH-03 — `ats_score` is backward-compat technical debt

| Field | Detail |
|---|---|
| **File** | `analyzer/models.py:248`, `analyzer/services/analyzer.py:188` |
| **Severity** | Low |

**What it does now**

```python
# Kept for backward compat in dashboard stats (generic_ats score is copied here)
ats_score = models.PositiveSmallIntegerField(null=True, blank=True)
```

On every analysis, `generic_ats` from the `scores` JSONField is also written to `ats_score`:

```python
analysis.ats_score = scores.get('generic_ats')
```

**The issue**

`scores` already contains `generic_ats`. Having a separate denormalized field means two sources of truth can drift (e.g., if a retry partially updates one but not the other). Dashboard stats queries that use `ats_score` would need to be rewritten if the field is ever removed.

**Possible fix**

Add a `generic_ats` database-level expression index on `scores__generic_ats` for PostgreSQL JSONField queries, then update `DashboardStatsView` and `AnalysisStatusView` to query via the JSONField, and drop `ats_score` in a follow-up migration.

---

### ARCH-04 — Dashboard stats run 5 aggregate queries per request with no caching

| Field | Detail |
|---|---|
| **File** | `analyzer/views.py` |
| **Lines** | 322–374 |
| **Severity** | Medium |

**What it does now**

`DashboardStatsView.get()` runs these queries on every request:

1. `all_qs.count()` — total analyses
2. `active_qs.count()` — active analyses
3. `.aggregate(avg=Avg('ats_score'))` — average ATS score
4. `.order_by('-created_at')[:10].values(...)` — score trend
5. `.values('jd_role').annotate(count=Count('id')).order_by('-count')[:5]` — top roles
6. `.annotate(month=TruncMonth(...)).values('month').annotate(count=Count('id'))` — monthly

**The issue**

No caching. For a power user with thousands of analyses, the aggregate queries can take multiple seconds per request. The dashboard data changes infrequently (only when a new analysis completes).

**Possible fix**

Cache the full response with a short TTL:

```python
def get(self, request):
    cache_key = f'dashboard_stats:{request.user.id}'
    cached = cache.get(cache_key)
    if cached:
        return Response(cached)

    data = self._compute_stats(request.user)
    cache.set(cache_key, data, timeout=300)  # 5 minutes
    return Response(data)
```

Invalidate the cache when a new analysis completes by adding `cache.delete(f'dashboard_stats:{user_id}')` in `run_analysis_task`.

---

### ARCH-05 — Jobs list endpoint has no pagination

| Field | Detail |
|---|---|
| **File** | `analyzer/views.py` |
| **Lines** | 468–477 |
| **Severity** | Medium |

**What it does now**

```python
def get(self, request):
    qs = Job.objects.filter(user=request.user).select_related('resume')
    relevance = request.query_params.get('relevance')
    if relevance in dict(Job.RELEVANCE_CHOICES):
        qs = qs.filter(relevance=relevance)
    serializer = JobSerializer(qs, many=True)
    return Response(serializer.data)
```

All jobs are returned in a single response. The analysis list uses `ListAPIView` with `PageNumberPagination` (page size 20).

**The issue**

A user tracking hundreds of jobs receives the full list in one large payload. This is inconsistent with the analyses list and will degrade as the job list grows.

**Possible fix**

Convert to `ListAPIView` to inherit the default pagination:

```python
class JobListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = JobSerializer

    def get_queryset(self):
        qs = Job.objects.filter(user=self.request.user).select_related('resume')
        relevance = self.request.query_params.get('relevance')
        if relevance in dict(Job.RELEVANCE_CHOICES):
            qs = qs.filter(relevance=relevance)
        return qs
```

Handle the `POST` in a separate `JobCreateView` or split the class.

---

### ARCH-06 — `MeView.put()` uses `partial=True` but the HTTP method is `PUT`

| Field | Detail |
|---|---|
| **File** | `accounts/views.py` |
| **Lines** | 93–103 |
| **Severity** | Low |

**What it does now**

```python
def put(self, request):
    serializer = UpdateUserSerializer(
        request.user,
        data=request.data,
        partial=True,       # ← partial update semantics
        context={'request': request},
    )
```

**The issue**

REST convention: `PUT` replaces the entire resource (all fields required), `PATCH` applies partial updates (only provided fields changed). Using `partial=True` with a `PUT` handler means clients never need to send the full resource — but they also don't know that, because the HTTP method signals otherwise.

**Possible fix**

Add a `patch()` method alongside or instead of `put()`, and set `partial=True` only there:

```python
def patch(self, request):
    serializer = UpdateUserSerializer(
        request.user, data=request.data, partial=True, context={'request': request},
    )
    ...
```

Update the URL routing and `FRONTEND_API_GUIDE.md` accordingly.

---

### ARCH-07 — `LLMResponse.prompt_sent` stores full resume text, tripling storage

| Field | Detail |
|---|---|
| **File** | `analyzer/services/ai_providers/openrouter_provider.py` |
| **Lines** | 79–84 |
| **Severity** | Low |

**What it does now**

```python
return {
    'parsed': data,
    'raw': raw,
    'prompt': json.dumps(messages),   # full system prompt + resume text + JD text
    ...
}
```

`LLMResponse.prompt_sent` stores the entire serialized `messages` array, which contains both the full system prompt and the complete resume text embedded in the user message.

**The issue**

The resume text is already persisted in:
1. `Resume.file` — the original PDF in R2
2. `ResumeAnalysis.resume_text` — plain-text extracted form

Storing it a third time inside `LLMResponse.prompt_sent` triples storage consumption for the most expensive column. For a 5-page resume (≈5,000 words ≈ 35KB of text), this adds 35KB per analysis to the `LLMResponse` table.

**Possible fix**

Store only the prompt template reference and metadata (model, token counts, timestamps) in `prompt_sent`, not the full input text:

```python
'prompt': json.dumps({
    'model': self.model,
    'system_prompt_chars': len(SYSTEM_PROMPT),
    'resume_chars': len(resume_text),
    'jd_chars': len(job_description),
}),
```

If full prompt replay is needed for debugging, reconstruct it from `ResumeAnalysis.resume_text` + `ResumeAnalysis.resolved_jd` at query time.

---

### ARCH-08 — Mobile app has hardcoded development base URLs

| Field | Detail |
|---|---|
| **File** | `mobile/src/api/client.js` |
| **Severity** | Medium |

**What it does now**

The Axios client base URL is set to `10.0.2.2:8000` (Android emulator) or `localhost:8000` (iOS simulator) — hardcoded development addresses.

**The issue**

Building a production APK or IPA with this code will fail silently — the app ships pointing at developer machines. There is no Expo environment variable configuration to override this at build time.

**Possible fix**

Use Expo's `EXPO_PUBLIC_*` environment variable convention:

```javascript
const BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'http://10.0.2.2:8000';
```

Set `EXPO_PUBLIC_API_URL` in `.env.production` and `.env.development`. Expo's build system substitutes these at bundle time.

---

### ARCH-09 — `anthropic` SDK is listed in `requirements.txt` but never imported

| Field | Detail |
|---|---|
| **File** | `requirements.txt:31` |
| **Severity** | Low |

**What it does now**

```
anthropic==0.40.0
```

All AI calls go through `OpenRouterProvider` using the `openai` SDK. The `anthropic` package is a remnant from a planned or previous provider implementation. No file in the codebase imports from `anthropic`.

**The issue**

Dead dependency: increases Docker image size, adds an extra package to audit for CVEs, and creates confusion about which AI SDKs are actually in use.

**Possible fix**

Remove the line from `requirements.txt`. If a native Anthropic provider is planned, add it back when the `AnthropicProvider` class is implemented.

---

## 4. Minor Issues

| # | File | Lines | Description | Fix |
|---|------|-------|-------------|-----|
| **MIN-01** | `analyzer/views.py` | 191 | Raw string `'done'` used instead of the constant `ResumeAnalysis.STATUS_DONE` | Replace with `ResumeAnalysis.STATUS_DONE` for consistency |
| **MIN-02** | `analyzer/tasks.py` | 40, 104 | `autoretry_for=(ConnectionError, OSError, TimeoutError)` at the decorator AND manual re-raise on line 104 could trigger double-retry counting | Remove the manual re-raise on line 104; let the decorator handle it |
| **MIN-03** | `analyzer/tasks.py` | 89, 101 | `except Exception: pass` swallows all errors when trying to mark analysis as failed. If the DB is down, failure state is never recorded | At minimum log the exception: `logger.exception('Could not mark analysis as failed')` |
| **MIN-04** | `accounts/views.py` | 88–90 | `get_or_create` (a write) is called inside `MeView.get()` on every profile fetch for old users | Run this as a data migration or one-time management command instead |
| **MIN-05** | `analyzer/services/jd_fetcher.py` | 82 | `formats=['markdown', 'json', 'summary']` — the `'json'` format requires a Firecrawl schema; without one it returns null. The code handles null gracefully but the request is unnecessary overhead | Remove `'json'` from the formats list; keep `['markdown', 'summary']` |
| **MIN-06** | `requirements.txt` | all | Transitive dependencies are pinned (e.g. `h11`, `pydantic_core`, `asgiref`). This blocks automatic security patch uptake | Pin only direct dependencies; generate a `requirements.lock` with `pip-compile` for reproducible builds |
| **MIN-07** | `analyzer/models.py` | 195, 18 | `ResumeAnalysis.resume_file` and `Resume.file` both use `upload_to='resumes/'`. Files from both models are stored in the same R2 prefix, making them indistinguishable by prefix alone | Use distinct upload paths: `upload_to='resume_analyses/'` for the analysis field |
| **MIN-08** | `analyzer/views.py` | 209–222 | `AnalysisPDFExportView` catches all exceptions with bare `except Exception` and returns 503 without logging the specific cause | Log the exception before returning 503: `logger.exception(...)` |
| **MIN-09** | `analyzer/serializers.py` | 219–222 | `get_share_url` in list and detail serializers does not have access to `request` in context, so `build_absolute_uri` cannot be called | Pass `context={'request': request}` from all views that instantiate these serializers |
| **MIN-10** | `analyzer/tasks.py` | 164–182 | `cleanup_stale_analyses` uses `updated_at__lt=cutoff` but `updated_at` is `auto_now=True` and updates on every field write. If a task writes a field every 28 minutes it would never be cleaned up | Switch to `created_at__lt=cutoff` or add a dedicated `processing_started_at` field |

---

## 5. Missing / Unimplemented Features

These features are scaffolded in the data model or configuration but have no implementation.

| Feature | Where It's Scaffolded | What's Missing |
|---|---|---|
| **Plan quota enforcement** | `Plan.analyses_per_month`, `max_resumes_stored`, `max_resume_size_mb`, `priority_queue` | No view-level checks; no quota counter; no upgrade prompt |
| **Feature flag enforcement** | `Plan.pdf_export`, `share_analysis`, `job_tracking` | Flags exist in DB but are never read in views |
| **SMS / push notifications** | `NotificationPreference.job_alerts_mobile`, `feature_updates_mobile`, etc. | Fields defined; no SMS provider, no push notification sender |
| **Job matching & alerts** | `Job.relevance`, `Job.source`; `NotificationPreference.job_alerts_email` | No matching engine, no scraper, no alert sender |
| **Payment / subscription** | `Plan.price` (INR), `billing_cycle` choices (monthly/yearly/lifetime) | No Stripe/Razorpay integration; no upgrade/downgrade flow |
| **Email verification** | `RegisterView` sends welcome email | No verification token; no verified/unverified state on user |
| **Priority Celery queue** | `Plan.priority_queue = True` | No separate Celery queue defined; all tasks go to the default queue |
| **Multi-AI provider support** | `.env.example` documents `AI_PROVIDER`, `LUFFY_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Only `OpenRouterProvider` is implemented; factory only supports one provider |
| **Wallet / credit system** | `.env.example` mentions `AI_PROVIDER=luffy` with `LUFFY_API_URL` | No credit tracking, no top-up flow |

---

## Appendix: Severity Reference

| Level | Meaning |
|---|---|
| **High** | Causes data loss, outage, or security breach under reachable conditions |
| **Medium** | Degrades UX, correctness, or performance in common scenarios |
| **Low** | Edge-case, cosmetic, or future-risk issue that should be tracked |
