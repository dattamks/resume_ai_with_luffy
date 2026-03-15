# Security Issues, Edge Cases & Bugs Report

**Project:** Resume AI (i-Luffy)
**Date:** 2026-03-15
**Scope:** Full codebase review of backend Django application

---

## 1. Security Issues

### 1.1 CRITICAL — Crawler API Key Comparison Not Timing-Safe

**File:** `analyzer/views_ingest.py:54`
**Severity:** Medium
**Description:** The `IsCrawlerAuthenticated` permission class compares the API key using `==` instead of `hmac.compare_digest()`. This is vulnerable to timing attacks where an attacker can infer the correct key character-by-character by measuring response times.

```python
# Current (vulnerable)
return provided == expected

# Fix
import hmac
return hmac.compare_digest(provided, expected)
```

### 1.2 MEDIUM — No Upper Bound on Bulk Ingest for Companies/Entities

**File:** `analyzer/views_ingest.py:93-115, 166-188`
**Severity:** Medium
**Description:** `CompanyBulkIngestView`, `CompanyEntityBulkIngestView` accept unbounded list sizes. While `JobBulkIngestView` caps at 500 and `NewsSnippetBulkIngestView` caps at 200, companies and entities have no limit. A malicious crawler (or compromised API key) could send thousands of items in a single request, causing memory exhaustion or DB write amplification.

### 1.3 MEDIUM — Avatar Upload Content-Type Spoofing

**File:** `accounts/views.py:1063`
**Severity:** Medium
**Description:** Avatar upload validates `f.content_type` which is client-provided and trivially spoofed. While `Image.open().verify()` provides secondary validation, a file could pass JPEG/PNG header checks but contain embedded malicious payloads (polyglot files). The file extension is also derived from the uploaded filename (`f.name`), not from actual content detection.

**Recommendation:** Use `python-magic` or `filetype` library to detect actual MIME type from file bytes, not the client-supplied header.

### 1.4 MEDIUM — CSV Injection in Wallet Transaction Export

**File:** `accounts/views.py:1019-1029`
**Severity:** Medium
**Description:** `WalletTransactionExportView` writes `tx.description` and `tx.reference_id` directly to CSV without sanitizing for CSV injection. If any description starts with `=`, `+`, `-`, or `@`, it could execute formulas when opened in Excel/Google Sheets.

**Recommendation:** Prefix values starting with those characters with a single quote or tab.

### 1.5 LOW — Username Enumeration via Registration

**File:** `accounts/serializers.py:135-137`
**Severity:** Low
**Description:** The registration email validation returns `'An account with this email already exists.'`, which confirms whether an email is registered. While `ForgotPasswordView` correctly returns a generic message, the registration endpoint leaks this information. This is a common trade-off (need to tell users why registration failed), but worth noting.

### 1.6 LOW — Email Verification Token Not Rate-Limited per Token

**File:** `accounts/views.py:140-189`
**Severity:** Low
**Description:** The `VerifyEmailView` endpoint has `AuthEndpointThrottle` but tokens could still be brute-forced within the rate limit window. The token is `secrets.token_urlsafe(48)` which is 64 chars — effectively unguessable, so this is theoretical only. No issue in practice.

### 1.7 LOW — Flower Dashboard Default Credentials

**File:** `entrypoint.sh:49`
**Severity:** Low (operational)
**Description:** Flower monitoring uses `admin:changeme` as default basic auth. If `FLOWER_USER` and `FLOWER_PASSWORD` env vars are not set in production, the monitoring dashboard is accessible with known credentials.

### 1.8 INFO — X-Forwarded-For IP Spoofing

**File:** `accounts/views.py:126-129`
**Severity:** Informational
**Description:** `_get_client_ip()` trusts the `X-Forwarded-For` header, which can be spoofed by clients. Since Railway terminates SSL at the proxy and sets this header, the first entry should be correct in production. However, if the app is ever deployed without a trusted reverse proxy, IP-based throttling and consent logging become unreliable.

---

## 2. Edge Cases

### 2.1 Race Condition in Job Ingest Debounce Queue

**File:** `analyzer/views_ingest.py:238-251`
**Severity:** Medium
**Description:** The debounce mechanism uses `cache.set()` with string concatenation to accumulate job IDs:
```python
cache.set(queue_key, cache.get(queue_key, '') + str(job.id) + ',', timeout=120)
```
This is not atomic. Under concurrent requests:
- Two requests can read the same value from `cache.get()`, both append their ID, and the second `set()` overwrites the first — **losing a job ID**.
- The string grows unbounded if the processing task is delayed.

**Fix:** Use Redis `LPUSH`/`RPUSH` for atomic list operations, or use Celery's `apply_async` with countdown per-job.

### 2.2 Wallet Balance Can Exceed `PositiveIntegerField` Max

**File:** `accounts/services.py:198`
**Severity:** Low
**Description:** `add_credits()` adds to wallet balance without checking an upper bound. While `PositiveIntegerField` supports up to 2^31-1 (~2.1B), and `grant_monthly_credits_for_user` has a cap, `add_credits()` used for admin adjustments and top-ups has no ceiling. An admin accidentally adding a huge amount could cause overflow at the DB level.

### 2.3 Google OAuth Race Condition on Registration

**File:** `accounts/views.py:908`
**Severity:** Low
**Description:** `GoogleCompleteView` checks `User.objects.filter(email__iexact=email).exists()` before creating the user, but this is not inside a transaction with the create. Two concurrent requests with the same temp_token could both pass the check. The `User.username` unique constraint would catch this at the DB level, but the email uniqueness relies on application-level check only (Django's User model does not enforce unique emails by default).

**Impact:** Could result in duplicate accounts with the same email if two requests arrive simultaneously.

### 2.4 Subscription Cancellation Immediately Downgrades

**File:** `accounts/razorpay_service.py:310-314`
**Severity:** Medium (business logic)
**Description:** `cancel_subscription()` calls `subscribe_plan(user, 'free')` immediately after cancelling on Razorpay with `cancel_at_cycle_end=1`. The `subscribe_plan` function should schedule the downgrade (since `plan_valid_until` is in the future), but if `plan_valid_until` is None or in the past, it will downgrade immediately — even though the user just cancelled at cycle end.

### 2.5 No Limit on Email Verification Tokens

**File:** `accounts/models.py:779-788`
**Severity:** Low
**Description:** `EmailVerificationToken.create_for_user()` creates new tokens without limiting how many unused tokens a user can have. `ResendVerificationEmailView` invalidates old tokens before creating new ones, but the `RegisterView` creates one without invalidating. If a user registers multiple times (using different usernames), tokens accumulate.

### 2.6 Stale Analysis Recovery May Double-Process

**File:** `analyzer/services/analyzer.py:89-95`
**Severity:** Low
**Description:** When resuming from a failed step, the analyzer re-runs the step that failed. If the step partially completed (e.g., LLM call succeeded but DB write failed), the re-run creates a new `LLMResponse` object even though one already exists, leading to duplicate LLM API calls and orphaned records.

### 2.7 Webhook Replay Protection Depends on Event ID Construction

**File:** `accounts/views_payments.py:228-236`
**Severity:** Low
**Description:** If Razorpay doesn't send an `event_id`, the code constructs one from `event_type:entity_id`. If the same entity gets the same event type twice (legitimate), the second delivery would be incorrectly rejected as a duplicate.

### 2.8 `plan_valid_until` Not Enforced on API Access

**Severity:** Medium (business logic)
**Description:** There is no middleware or check that automatically downgrades users when `plan_valid_until` passes. The `process_expired_plans()` function exists but must be called by a Celery beat task. If that task fails or is delayed, expired Pro users continue to access Pro features. The plan feature checks (`can_use_feature`) check the plan assignment but not the expiry date.

---

## 3. Bugs

### 3.1 `avatar_url` Field Allows Empty String but Declared as `URLField`

**File:** `accounts/models.py:75-79`, `accounts/serializers.py:173`
**Severity:** Low
**Description:** `UserProfile.avatar_url` is a `URLField` with `blank=True, default=''`. The `UserSerializer` declares it as `serializers.URLField(... read_only=True)`. When the avatar is removed (set to `''`), the URLField serializer may raise a validation error if the empty string passes through serialization. Currently it's read-only so it works, but any future write path through this serializer would break.

### 3.2 `_estimate_cost` Returns None for Exact Model Mismatches

**File:** `analyzer/services/analyzer.py:26-41`
**Severity:** Low
**Description:** The cost estimation uses substring matching (`if model in key or key in model`) which could match incorrectly. For example, `openai/gpt-4o` matches `openai/gpt-4o-mini` because `"openai/gpt-4o" in "openai/gpt-4o-mini"` is True. This could return wrong pricing for the cheaper model.

### 3.3 `topup_credits` Service Function Still Exists Unused

**File:** `accounts/services.py:230-282`
**Severity:** Informational
**Description:** `topup_credits()` is the old synchronous top-up function that was replaced by the Razorpay flow (`create_topup_order` → `verify_topup_payment` → `_fulfill_topup`). The endpoint `WalletTopUpView` now returns 402 redirecting to the payment flow. The old `topup_credits` function is dead code.

### 3.4 Missing `test_db.sqlite3` in `.gitignore`

**File:** `.gitignore`
**Severity:** Informational
**Description:** Settings creates `test_db.sqlite3` for test runs but `.gitignore` only excludes `db.sqlite3`. The test database could accidentally be committed.

### 3.5 `LoginView` Activity Tracking Parses Its Own Token

**File:** `accounts/views.py:241-249`
**Severity:** Low
**Description:** `LoginView.post()` decodes the just-generated access token to find the user ID, even though the serializer already validated the credentials and has the user. This is redundant and fragile — if the token structure ever changes, this breaks silently (caught by bare `except Exception: pass`).

### 3.6 Hard-Coded Country Default

**File:** `accounts/models.py:109-113`
**Severity:** Informational
**Description:** `UserProfile.country` defaults to `'India'`. International users who don't explicitly set their country will show as being from India in analytics and feed filtering.

---

## 4. Recommendations Summary

| Priority | Count | Category |
|----------|-------|----------|
| Critical | 0 | — |
| High | 2 | Timing-safe comparison, ingest rate limits |
| Medium | 5 | Race conditions, business logic gaps, CSV injection |
| Low | 7 | Edge cases, minor bugs |
| Info | 4 | Dead code, defaults, .gitignore |

### Top 5 Actions

1. **Use `hmac.compare_digest()` for crawler API key comparison** — Simple one-line fix, prevents timing attacks.
2. **Add size limits to company/entity bulk ingest endpoints** — Consistent with job/news limits.
3. **Fix job ingest debounce to use atomic Redis operations** — Prevents lost job IDs under concurrency.
4. **Add periodic plan expiry enforcement** — Ensure `process_expired_plans()` runs reliably, and add runtime checks in `can_use_feature()`.
5. **Sanitize CSV export fields** — Prevent CSV injection in wallet transaction exports.
