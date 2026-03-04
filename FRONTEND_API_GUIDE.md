# Frontend API Integration Guide

> **Last updated:** 2026-03-03 &nbsp;|&nbsp; **API version:** v0.37.0
> Comprehensive technical reference for frontend developers integrating with the i-Luffy backend.

---

## Table of Contents

1. [Base URL & Authentication](#1-base-url--authentication)
2. [API Client Setup](#2-api-client-setup)
3. [Auth Endpoints](#3-auth-endpoints)
4. [Analysis Endpoints](#4-analysis-endpoints)
5. [Resume Endpoints](#5-resume-endpoints)
6. [Dashboard Endpoints](#6-dashboard-endpoints)
7. [Share Endpoints](#7-share-endpoints)
8. [Health Check](#8-health-check)
9. [Response Schemas](#9-response-schemas)
10. [LLM Analysis Output Schema](#10-llm-analysis-output-schema)
11. [Pagination](#11-pagination)
12. [Rate Limiting](#12-rate-limiting)
13. [Polling for Analysis Status](#13-polling-for-analysis-status)
14. [Error Handling Reference](#14-error-handling-reference)
15. [TypeScript Type Definitions](#15-typescript-type-definitions)
16. [Frontend Integration Recipes](#16-frontend-integration-recipes)
17. [Plans & Wallet (Credits System)](#17-plans--wallet-credits-system)
18. [Email Templates (Admin)](#18-email-templates-admin)
19. [Resume Generation](#19-resume-generation)
20. [Smart Job Alerts](#20-smart-job-alerts)
21. [Razorpay Payments](#21-razorpay-payments)
22. [Landing Page Contact Form](#22-landing-page-contact-form)
23. [Email Verification](#23-email-verification)
24. [Bulk Analysis (Removed)](#24-bulk-analysis-removed)
25. [Interview Prep Generation](#25-interview-prep-generation)
26. [Cover Letter Generation](#26-cover-letter-generation)
27. [Resume Version History](#27-resume-version-history)
28. [Resume Templates (Template Marketplace)](#28-resume-templates-template-marketplace)
29. [Resume Chat — Text-Based Resume Builder](#29-resume-chat--text-based-resume-builder)
30. [Feed & Analytics Endpoints](#30-feed--analytics-endpoints)
31. [Database Table Reference — Job & Company Models](#31-database-table-reference--job--company-models)
32. [Quick Reference — All Endpoints](#32-quick-reference--all-endpoints)

---

## 1. Base URL & Authentication

### Base URL

```
Development:  http://localhost:8000/api/v1
Production:   https://<backend>.up.railway.app/api/v1
```

Configure via environment variable:

```env
# .env (Vite)
VITE_API_URL=http://localhost:8000/api/v1

# .env (React Native / Expo)
EXPO_PUBLIC_API_URL=http://localhost:8000/api/v1
```

> **API Versioning (v0.24.0):** All endpoints are now under `/api/v1/`. The old `/api/` prefix no longer works. Update your `API_URL` configuration accordingly.

### Authentication — JWT (Bearer Token)

All endpoints except `/api/v1/auth/register/`, `/api/v1/auth/login/`, `/api/v1/auth/token/refresh/`, and `/api/v1/health/` require a JWT access token.

```
Authorization: Bearer <access_token>
```

**Token lifetimes:**

| Token   | Lifetime | Notes                                   |
|---------|----------|-----------------------------------------|
| Access  | 1 hour   | Short-lived; attach to every API request |
| Refresh | 7 days   | Rotated on use; store securely           |

Refresh tokens are **rotated on use** — each refresh call returns a new refresh token and blacklists the old one. If the old refresh token is reused after rotation, authentication will fail (token replay protection).

**Refresh flow:**
```http
POST /api/v1/auth/token/refresh/
Content-Type: application/json

{ "refresh": "<refresh_token>" }
```

```json
{
  "access": "<new_access_token>",
  "refresh": "<new_refresh_token>"
}
```

### Storage Recommendations

| Platform | Access Token | Refresh Token |
|----------|-------------|---------------|
| Web (SPA) | In-memory (React state/context) | `httpOnly` cookie or `localStorage` |
| React Native | `SecureStore` / `Keychain` | `SecureStore` / `Keychain` |

> **Security note:** Never store tokens in `sessionStorage` for SPAs. Prefer in-memory for access tokens with automatic refresh on 401.

---

## 2. API Client Setup

### Axios Setup (Web)

```js
// src/api/v1/client.js
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// ── Request interceptor: attach access token ────────────────────────────
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token'); // or from context
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor: auto-refresh on 401 ──────────────────────────
let isRefreshing = false;
let failedQueue = [];

const processQueue = (error, token = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    error ? reject(error) : resolve(token);
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return api(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const refresh = localStorage.getItem('refresh_token');
        const { data } = await axios.post(`${API_URL}/auth/token/refresh/`, { refresh });

        localStorage.setItem('access_token', data.access);
        localStorage.setItem('refresh_token', data.refresh);

        processQueue(null, data.access);
        originalRequest.headers.Authorization = `Bearer ${data.access}`;
        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        // Redirect to login
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.href = '/login';
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default api;
```

> **Note:** The above shows `localStorage` for simplicity. In production, prefer storing the access token in React context/state (memory) and only the refresh token in `localStorage`.

---

## 3. Auth Endpoints

All prefixed with `/api/v1/auth/`.

### POST `/api/v1/auth/register/` — Create Account

🔓 Public — no auth required. **Throttled:** `auth` scope (20/hour per IP).

Creates a new user account and returns tokens immediately (auto-login).

**Request:**
```json
{
  "username": "john",
  "email": "john@example.com",
  "password": "SecurePass123!",
  "password2": "SecurePass123!",
  "agree_to_terms": true,
  "agree_to_data_usage": true,
  "marketing_opt_in": false
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | ✅ | Unique username (3–30 chars, letters/digits/underscore only, no reserved words — see below) |
| `email` | string | ✅ | Valid email address |
| `password` | string | ✅ | Min 8 chars, can't be too common/numeric |
| `password2` | string | ✅ | Must match `password` |
| `agree_to_terms` | boolean | ✅ | Must be `true` — Terms of Service & Privacy Policy |
| `agree_to_data_usage` | boolean | ✅ | Must be `true` — AI data processing & Data Usage Policy |
| `marketing_opt_in` | boolean | ❌ | Optional (default `false`) — marketing emails & newsletters |

> **Username rules (v0.26.0):** `username` must be **3–30 characters**, contain only **letters, digits, and underscores** (`^[a-zA-Z0-9_]+$`), and must **not** be a reserved word. Reserved words: `admin`, `root`, `superuser`, `api`, `system`, `support`, `help`, `info`, `null`, `undefined`, `iluffy`, `luffy`. The same rules apply to `POST /api/v1/auth/me/` (profile update) and `POST /api/v1/auth/google/complete/`.

**Response (201 Created):**
```json
{
  "user": {
    "id": 1,
    "username": "john",
    "email": "john@example.com",
    "first_name": "",
    "last_name": "",
    "date_joined": "2026-02-22T10:00:00Z",
    "country_code": "+91",
    "mobile_number": "",
    "country": "India",
    "state": "",
    "city": "",
    "auth_provider": "email",
    "avatar_url": "",
    "plan": {
      "id": 1,
      "name": "Free",
      "slug": "free",
      "description": "Get started with basic resume analysis.",
      "billing_cycle": "free",
      "price": "0.00",
      "credits_per_month": 2,
      "max_credits_balance": 10,
      "topup_credits_per_pack": 0,
      "topup_price": "0.00",
      "analyses_per_month": 0,
      "api_rate_per_hour": 200,
      "max_resume_size_mb": 5,
      "max_resumes_stored": 5,
      "job_notifications": false,
      "max_job_alerts": 0,
      "pdf_export": true,
      "share_analysis": true,
      "job_tracking": true,
      "priority_queue": false,
      "email_support": false
    },
    "wallet": {
      "balance": 2,
      "updated_at": "2026-02-22T10:00:00Z"
    },
    "plan_valid_until": null,
    "pending_plan": null,
    "agreed_to_terms": true,
    "agreed_to_data_usage": true,
    "marketing_opt_in": false
  },
  "access": "<jwt_access_token>",
  "refresh": "<jwt_refresh_token>"
}
```

**Errors (400):**
```json
{
  "detail": "A user with that username already exists.",
  "errors": {
    "username": ["A user with that username already exists."],
    "password": ["This password is too common."],
    "password2": ["Passwords do not match."],
    "agree_to_terms": ["You must agree to the Terms of Service and Privacy Policy."],
    "agree_to_data_usage": ["You must acknowledge the Data Usage & AI Disclaimer."]
  }
}
```

Username-specific validation errors that may appear in `errors.username`:
- `"Username must be at least 3 characters long."`
- `"Username must be at most 30 characters long."`
- `"Username may only contain letters, digits, and underscores."`
- `"This username is reserved."`
- `"A user with that username already exists."`

> **Consent audit:** Three `ConsentLog` entries are recorded per registration (terms, data usage, marketing) with the user's IP address, user agent, and timestamp. This log is immutable — used for GDPR/compliance auditing.
>
> **Newsletter sync:** When `marketing_opt_in` is `true`, the user's `NotificationPreference.newsletters_email` is automatically set to `true`.

> **Email verification (v0.24.0):** Registration now sends a **verification email** (template `email-verification`) instead of the welcome email. The response includes `email_verification_required: true`. The welcome email is only sent after the user verifies their email via `POST /api/v1/auth/verify-email/`. See [§23 Email Verification](#23-email-verification) for the full flow.

> **New response field:** `is_email_verified` (boolean) is included in the `user` object on registration, login, and `GET /api/v1/auth/me/`. Initially `false` until verified.

---

### POST `/api/v1/auth/login/` — Sign In

🔓 Public — no auth required. **Throttled:** `auth` scope (20/hour per IP).

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
    "first_name": "",
    "last_name": "",
    "date_joined": "2026-02-22T10:00:00Z",
    "country_code": "+91",
    "mobile_number": "",
    "country": "India",
    "state": "",
    "city": "",
    "auth_provider": "email",
    "avatar_url": "",
    "plan": { "id": 1, "name": "Free", "slug": "free", "...":  "..." },
    "wallet": { "balance": 2, "updated_at": "..." },
    "plan_valid_until": null,
    "pending_plan": null
  }
}
```

**Errors (401):**
```json
{ "detail": "No active account found with the given credentials" }
```

---

### POST `/api/v1/auth/logout/` — Sign Out

🔒 Requires auth. Blacklists the refresh token server-side.

**Request:**
```json
{
  "refresh": "<refresh_token>"
}
```

**Response (200):** `{ "detail": "Successfully logged out." }`

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Missing refresh token | `{ "detail": "Refresh token is required." }` |
| 400  | Invalid/blacklisted token | `{ "detail": "Invalid token." }` |

**Frontend action:** After calling logout, clear both tokens from storage and redirect to login.

---

### GET `/api/v1/auth/me/` — Current User Profile

🔒 Requires auth. Returns the currently authenticated user's profile including phone fields, geography, and plan.

**Response (200):**
```json
{
  "id": 1,
  "username": "john",
  "email": "john@example.com",
  "date_joined": "2026-02-22T10:00:00Z",
  "country_code": "+91",
  "mobile_number": "",
  "country": "India",
  "state": "",
  "city": "",
  "plan": {
    "id": 1,
    "name": "Free",
    "slug": "free",
    "description": "Get started with basic resume analysis.",
    "billing_cycle": "free",
    "price": "0.00",
    "original_price": "0.00",
    "credits_per_month": 2,
    "max_credits_balance": 10,
    "topup_credits_per_pack": 0,
    "topup_price": "0.00",
    "analyses_per_month": 0,
    "api_rate_per_hour": 200,
    "max_resume_size_mb": 5,
    "max_resumes_stored": 5,
    "job_notifications": false,
    "max_job_alerts": 0,
    "pdf_export": true,
    "share_analysis": true,
    "job_tracking": true,
    "priority_queue": false,
    "email_support": false
  },
  "wallet": {
    "balance": 2,
    "updated_at": "2026-02-22T10:00:00Z"
  },
  "plan_valid_until": null,
  "pending_plan": null
}
```

> **`plan`** is `null` if the user has no plan assigned (shouldn't happen — new users auto-get the "Free" plan).
>
> **`wallet`** is `null` if wallet hasn't been created yet (edge case for pre-migration users). Treat as `{ balance: 0 }`.
>
> **`plan_valid_until`** is set when user is on a paid plan (e.g., Pro). `null` for free plan.
>
> **`pending_plan`** is set when a downgrade is scheduled. Shows the plan the user will switch to after `plan_valid_until` expires.

Use this on app load to verify the stored token is still valid and hydrate user state.

---

### PUT `/api/v1/auth/me/` — Update Profile

🔒 Requires auth. Update the current user's profile. Partial updates are supported (send only the fields you want to change).

**Request (JSON):**
```json
{
  "username": "new_name",
  "email": "new@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "country_code": "+1",
  "mobile_number": "5551234567",
  "country": "United States",
  "state": "California",
  "city": "San Francisco",
  "website_url": "https://johndoe.dev",
  "github_url": "https://github.com/johndoe",
  "linkedin_url": "https://linkedin.com/in/johndoe",
  "avatar_url": "https://example.com/photo.jpg"
}
```

**Writable fields:**

| Field          | Type   | Notes |
|----------------|--------|-------|
| `username`     | string | Must be unique |
| `email`        | string | Must be unique |
| `first_name`   | string | User's first name |
| `last_name`    | string | User's last name |
| `country_code` | string | e.g. `"+1"` |
| `mobile_number`| string | e.g. `"5551234567"` |
| `country`      | string | Country of residence (default `"India"`). Used as base for geo-scoped feed & analytics |
| `state`        | string | State / province / region (blank to clear) |
| `city`         | string | City of residence (blank to clear) |
| `website_url`  | URL    | Personal website (blank to clear) |
| `github_url`   | URL    | GitHub profile (blank to clear) |
| `linkedin_url` | URL    | LinkedIn profile (blank to clear) |
| `avatar_url`   | URL    | Profile picture URL (prefer using `POST /api/v1/auth/avatar/` for uploads) |

**Response (200):**
```json
{
  "id": 1,
  "username": "new_name",
  "email": "new@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "date_joined": "2026-02-22T10:00:00Z",
  "country_code": "+1",
  "mobile_number": "5551234567",
  "country": "United States",
  "state": "California",
  "city": "San Francisco",
  "website_url": "https://johndoe.dev",
  "github_url": "https://github.com/johndoe",
  "linkedin_url": "https://linkedin.com/in/johndoe",
  "avatar_url": "https://cdn.example.com/avatars/photo.jpg",
  "plan": { "id": 1, "name": "Free", "slug": "free", "...": "..." },
  "wallet": { "balance": 2, "updated_at": "..." },
  "plan_valid_until": null,
  "pending_plan": null
}
```

**Errors:**

| Code | Condition | Example Response |
|------|-----------|-----------------|
| 400  | Duplicate username | `{ "username": ["This username is already taken."] }` |
| 400  | Duplicate email | `{ "email": ["This email is already in use."] }` |
| 401  | Not authenticated | `{ "detail": "Authentication credentials were not provided." }` |

---

### DELETE `/api/v1/auth/me/` — Delete Account

🔒 Requires auth. **Permanently** deletes the authenticated user's account and all associated data.

> ⚠️ **Breaking change (v0.14.0):** Password confirmation is now **required**. Send a JSON body with the `password` field.

**Request (JSON):**
```json
{
  "password": "CurrentPassword123!"
}
```

**What happens on delete:**
1. Password is verified against the authenticated user.
2. Any active Razorpay subscription is cancelled.
3. All outstanding JWT tokens are blacklisted.
4. All active analyses are soft-deleted (heavy data cleared, metadata kept).
5. User row is hard-deleted (cascades to Resume, ScrapeResult, LLMResponse, Job rows).

**Response (204 No Content):**
```json
{ "detail": "Account permanently deleted." }
```

**Errors:**

| Code | Condition | Example Response |
|------|-----------|------------------|
| 400  | Missing password | `{ "password": ["This field is required."] }` |
| 400  | Wrong password | `{ "password": ["Password is incorrect."] }` |
| 401  | Not authenticated | `{ "detail": "Authentication credentials were not provided." }` |

> ⚠️ **This action is irreversible.** Show a confirmation dialog that collects the user's password before calling.

---

### POST `/api/v1/auth/avatar/` — Upload Avatar

🔒 Requires auth. Upload a profile picture. Accepts JPEG, PNG, or WebP images up to **2 MB**. The image is validated server-side using Pillow. Stored in R2 storage and the URL is set on `avatar_url`.

**Request:** `multipart/form-data` with field `avatar`.

```js
const formData = new FormData();
formData.append('avatar', fileInput.files[0]);
const { data } = await api.post('/auth/avatar/', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
});
// data.avatar_url → "https://cdn.example.com/avatars/abc123.png"
```

**Response (200):**
```json
{
  "avatar_url": "https://cdn.example.com/avatars/abc123.png"
}
```

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | No file provided | `{ "detail": "No file provided." }` |
| 400  | Invalid file type | `{ "detail": "Invalid file type. Allowed: JPEG, PNG, WebP." }` |
| 400  | File too large | `{ "detail": "File too large. Maximum size is 2 MB." }` |
| 400  | Corrupt image | `{ "detail": "Invalid image file." }` |

---

### DELETE `/api/v1/auth/avatar/` — Remove Avatar

🔒 Requires auth. Removes the user's avatar (deletes file from storage and clears `avatar_url`).

**Response (204):** No content.

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 404  | No avatar set | `{ "detail": "No avatar to delete." }` |

---

### POST `/api/v1/auth/change-password/` — Change Password

🔒 Requires auth. Changes the authenticated user's password.

**Request (JSON):**
```json
{
  "current_password": "OldPass123!",
  "new_password": "NewStrong456!"
}
```

**Response (200):**
```json
{ "detail": "Password updated successfully." }
```

**Errors:**

| Code | Condition | Example Response |
|------|-----------|-----------------|
| 400  | Wrong current password | `{ "current_password": ["Current password is incorrect."] }` |
| 400  | Weak new password | `{ "new_password": ["This password is too common."] }` |
| 401  | Not authenticated | `{ "detail": "Authentication credentials were not provided." }` |

> **Note (v0.14.0):** After changing password, **all existing JWT tokens are blacklisted**. The frontend must re-authenticate the user (redirect to login or use the refresh token from the current session, which will fail). Store the new credentials and re-login automatically.
> **Email:** A confirmation email (HTML template `password-changed`) is sent to the user after a successful password change.

---

### POST `/api/v1/auth/forgot-password/` — Request Password Reset

🔓 Public — no auth header required. **Throttled:** `auth` scope (20/hour per IP).

Sends a password reset email containing a one-time link with a `uid` and `token`. The link points to the frontend route `/reset-password?uid=<uid>&token=<token>`. **Always returns 200** — this is intentional; the API never reveals whether an email address is registered.

**Request (JSON):**
```json
{ "email": "john@example.com" }
```

**Response (200):**
```json
{ "detail": "If an account with that email exists, a reset link has been sent." }
```

**Errors:**

| Code | Condition | Example Response |
|------|-----------|------------------|
| 400  | Missing or invalid email | `{ "email": ["Enter a valid email address."] }` |
| 500  | Email delivery failure | `{ "detail": "Failed to send reset email. Please try again later." }` |

> **Reset link format:** `{FRONTEND_URL}/reset-password?uid={base64_uid}&token={token}` 
> **Token expiry:** 1 hour (configurable via `PASSWORD_RESET_TIMEOUT` setting).
> **Email:** Sends an HTML email using the `password-reset` template with a styled CTA button.

---

### POST `/api/v1/auth/reset-password/` — Set New Password

🔓 Public — no auth header required. **Throttled:** `auth` scope (20/hour per IP).

Validates the `uid` + `token` from the reset email and sets a new password. The frontend should extract `uid` and `token` from the URL query params and submit them here along with the new password.

**Request (JSON):**
```json
{
  "uid": "Mg",
  "token": "c4j5fx-abc1234567890def",
  "new_password": "NewStrong456!"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `uid` | `string` | Base64-encoded user ID (from the reset link `?uid=` param) |
| `token` | `string` | One-time reset token (from the reset link `?token=` param) |
| `new_password` | `string` | New password (must pass Django password validation) |

**Response (200):**
```json
{ "detail": "Password has been reset successfully. You can now log in." }
```

**Errors:**

| Code | Condition | Example Response |
|------|-----------|------------------|
| 400  | Invalid/expired uid | `{ "uid": ["Invalid or expired reset link."] }` |
| 400  | Invalid/expired token | `{ "token": ["Invalid or expired reset token."] }` |
| 400  | Weak new password | `{ "new_password": ["This password is too common."] }` |

> **After reset:** The user must log in again with the new password. No tokens are issued in this response.

---

### GET `/api/v1/auth/notifications/` — Get Notification Preferences

🔒 Requires auth. Returns the current user's notification preferences. Email notifications default to `true`; mobile notifications default to `false` (except policy changes).

**Response (200):**
```json
{
  "job_alerts_email": true,
  "job_alerts_mobile": false,
  "feature_updates_email": true,
  "feature_updates_mobile": false,
  "newsletters_email": true,
  "newsletters_mobile": false,
  "policy_changes_email": true,
  "policy_changes_mobile": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `job_alerts_email` | `boolean` | `true` | Receive job match alerts via email |
| `job_alerts_mobile` | `boolean` | `false` | Receive job match alerts via mobile |
| `feature_updates_email` | `boolean` | `true` | Feature update emails |
| `feature_updates_mobile` | `boolean` | `false` | Feature update mobile notifications |
| `newsletters_email` | `boolean` | `true` | Newsletter emails |
| `newsletters_mobile` | `boolean` | `false` | Newsletter mobile notifications |
| `policy_changes_email` | `boolean` | `true` | Policy change emails |
| `policy_changes_mobile` | `boolean` | `true` | Policy change mobile notifications |

---

### PUT `/api/v1/auth/notifications/` — Update Notification Preferences

🔒 Requires auth. Partial updates supported — send only the fields you want to change.

**Request (JSON):**
```json
{
  "newsletters_email": false,
  "newsletters_mobile": false
}
```

**Response (200):**
```json
{
  "job_alerts_email": true,
  "job_alerts_mobile": true,
  "feature_updates_email": true,
  "feature_updates_mobile": true,
  "newsletters_email": false,
  "newsletters_mobile": false,
  "policy_changes_email": true,
  "policy_changes_mobile": true
}
```

**Errors:**

| Code | Condition | Example Response |
|------|-----------|------------------|
| 400  | Invalid boolean value | `{ "newsletters_email": ["Must be a valid boolean."] }` |
| 401  | Not authenticated | `{ "detail": "Authentication credentials were not provided." }` |

---

### POST `/api/v1/auth/token/refresh/` — Refresh JWT

🔓 Public — no auth header required (the refresh token is in the body).

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

**Error (401):**
```json
{ "detail": "Token is blacklisted", "code": "token_not_valid" }
```

> **Important:** The old refresh token is blacklisted after this call. Always store the **new** refresh token returned.

---

### Google OAuth Login (Two-Step Flow)

Google Sign-In uses a **two-step flow** for new users (existing users get JWT tokens immediately):

```
Step 1:  Frontend gets Google ID token (Google Sign-In / One Tap)
         ↓
         POST /api/v1/auth/google/  { token: "<google_id_token>" }
         ↓
         Existing user? → JWT tokens returned (done!)
         New user?      → { needs_registration: true, temp_token, email, name, picture }

Step 2:  Frontend shows consent form + username/password fields
         ↓
         POST /api/v1/auth/google/complete/  { temp_token, username, password, consents... }
         ↓
         User created → JWT tokens returned (done!)
```

### POST `/api/v1/auth/google/` — Google Login (Step 1)

Verifies a Google ID token. For existing users, returns JWT tokens immediately (with smart profile sync). For new users, returns a temporary token to complete registration.

> **Profile sync on returning login:** When an existing user logs in via Google, the backend fills in any **blank** profile fields (`first_name`, `last_name`, `avatar_url`) from the Google account. Fields the user has manually set are **never overwritten**. `google_sub` is always updated, and `auth_provider` is upgraded from `"email"` to `"google"` if applicable.

**Request:**
```json
{
  "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6..."
}
```

**Response — Existing User (200):**
```json
{
  "user": {
    "id": 5,
    "username": "existinguser",
    "email": "user@gmail.com",
    "agreed_to_terms": true,
    "agreed_to_data_usage": true,
    "marketing_opt_in": false
  },
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOi...",
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOi..."
}
```

**Response — New User (200):**
```json
{
  "needs_registration": true,
  "temp_token": "eyJlbWFpbCI6InVzZXJAZ21haWwuY29tIi...",
  "email": "user@gmail.com",
  "name": "John Doe",
  "given_name": "John",
  "family_name": "Doe",
  "picture": "https://lh3.googleusercontent.com/..."
}
```

> **Note:** Use `given_name` and `family_name` to pre-fill the registration form. These come directly from the user's Google account.

> **Note:** The `temp_token` is valid for **10 minutes**. If it expires, the user must restart the Google Sign-In flow.

| Status | Condition | Body |
|--------|-----------|------|
| 200 | Existing user | JWT tokens + user object |
| 200 | New user | `needs_registration: true` + temp_token |
| 400 | Unverified email | `{ "detail": "Google account email is not verified." }` |
| 401 | Invalid/expired Google token | `{ "detail": "Invalid or expired Google token." }` |
| 503 | Google OAuth not configured | `{ "detail": "Google OAuth is not configured on this server." }` |

### POST `/api/v1/auth/google/complete/` — Complete Google Registration (Step 2)

Completes registration for a new Google user. Requires the `temp_token` from Step 1, a chosen username/password, and consent checkboxes.

**Request:**
```json
{
  "temp_token": "eyJlbWFpbCI6InVzZXJAZ21haWwuY29tIi...",
  "username": "johndoe",
  "password": "SecurePass123!",
  "agree_to_terms": true,
  "agree_to_data_usage": true,
  "marketing_opt_in": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `temp_token` | string | ✅ | Temporary token from Step 1 |
| `username` | string | ✅ | Chosen username (must be unique) |
| `password` | string | ✅ | Must meet Django password validation rules |
| `agree_to_terms` | boolean | ✅ | Must be `true` — Terms & Privacy Policy |
| `agree_to_data_usage` | boolean | ✅ | Must be `true` — Data Usage & AI Disclaimer |
| `marketing_opt_in` | boolean | ❌ | Default `false` — Marketing & Newsletter |

**Response (201):**
```json
{
  "user": {
    "id": 12,
    "username": "johndoe",
    "email": "user@gmail.com",
    "first_name": "John",
    "last_name": "Doe",
    "agreed_to_terms": true,
    "agreed_to_data_usage": true,
    "marketing_opt_in": false,
    "auth_provider": "google",
    "avatar_url": "https://lh3.googleusercontent.com/..."
  },
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOi...",
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOi..."
}
```

> **Note:** `first_name`, `last_name`, and `avatar_url` are automatically populated from the Google account. `auth_provider` is `"google"` for Google sign-ups and `"email"` for regular registrations.

| Status | Condition | Body |
|--------|-----------|------|
| 201 | User created | JWT tokens + user object |
| 400 | Invalid/expired temp token | `{ "detail": "Invalid or expired registration token. Please restart Google sign-in." }` |
| 400 | Validation errors | `{ "username": [...], "password": [...], ... }` |
| 400 | Consent not given | `{ "agree_to_terms": ["You must agree to the Terms & Privacy Policy."] }` |
| 409 | Email race condition | `{ "detail": "An account with this email already exists. Please log in instead." }` |

**TypeScript Types:**

```typescript
// Step 1 — Google Login
interface GoogleLoginRequest {
  token: string; // Google ID token from Google Sign-In SDK
}

type GoogleLoginResponse =
  | { user: UserProfile; access: string; refresh: string }               // existing user
  | { needs_registration: true; temp_token: string; email: string; name: string; given_name: string; family_name: string; picture: string }; // new user

// Step 2 — Complete Registration
interface GoogleCompleteRequest {
  temp_token: string;
  username: string;
  password: string;
  agree_to_terms: true;
  agree_to_data_usage: true;
  marketing_opt_in?: boolean;
}

interface GoogleCompleteResponse {
  user: UserProfile;
  access: string;
  refresh: string;
}
```

**Frontend Integration Example:**

```typescript
async function handleGoogleLogin(googleIdToken: string) {
  const res = await api.post('/api/v1/auth/google/', { token: googleIdToken });

  if ('needs_registration' in res.data) {
    // New user — show consent + username form, pre-fill email/name
    navigateToGoogleComplete(res.data);
  } else {
    // Existing user — store tokens, redirect to dashboard
    storeTokens(res.data.access, res.data.refresh);
    navigateToDashboard();
  }
}

async function completeGoogleRegistration(formData: GoogleCompleteRequest) {
  const res = await api.post('/api/v1/auth/google/complete/', formData);
  storeTokens(res.data.access, res.data.refresh);
  navigateToDashboard();
}
```

---

### POST `/api/v1/auth/logout-all/` — Logout All Devices

🔒 Requires auth. **Throttled:** `auth` scope (20/hour).

Invalidates **all** active JWT sessions for the authenticated user by blacklisting all outstanding tokens.

**Request body:** None.

**Response (200):**
```json
{
  "detail": "All sessions invalidated.",
  "invalidated": 3
}
```

| Field          | Type   | Description                         |
|----------------|--------|-------------------------------------|
| `detail`       | string | Human-readable status message       |
| `invalidated`  | int    | Number of tokens that were blacklisted |

**Frontend tip:** After calling this endpoint, clear all stored tokens and redirect to the login page.

```js
await api.post('/auth/logout-all/');
localStorage.removeItem('access_token');
localStorage.removeItem('refresh_token');
navigateToLogin();
```

---

## 4. Analysis Endpoints

All prefixed with `/api/v1/`.

### POST `/api/v1/analyze/` — Submit New Analysis

🔒 Requires auth. **Throttled:** 10/hour per user. Accepts **`multipart/form-data`** (file upload) or **`application/json`** (resume reuse).

Submits a resume + job description for async analysis. Returns immediately with a tracking ID. The analysis runs asynchronously via Celery background workers.

**Two ways to provide the resume — exactly one is required:**

1. **Upload a new PDF** → send `resume_file` via `multipart/form-data`.
2. **Reuse an existing resume** → send `resume_id` (UUID from `GET /api/v1/resumes/`) via JSON or form field.

**Idempotency guard:** A second submit within 30 seconds returns **409 Conflict**. The frontend should **disable the submit button** after the first click and show a loading state.

**Form / JSON fields:**

| Field                 | Type    | Required                    | Description                                              |
|-----------------------|---------|-----------------------------|----------------------------------------------------------|
| `resume_file`         | File    | ✅ unless `resume_id` sent  | PDF file, max 5 MB, must have `.pdf` extension and `%PDF` magic bytes |
| `resume_id`           | UUID    | ✅ unless `resume_file` sent | UUID of an existing Resume owned by the user (from `GET /api/v1/resumes/`) |
| `jd_input_type`       | String  | ✅                          | One of: `"text"`, `"url"`, `"form"`                      |
| `jd_text`             | String  | If type=`text`              | Raw job description text                                 |
| `jd_url`              | String  | If type=`url`               | URL to a job posting (scraped via Firecrawl)             |
| `jd_role`             | String  | If type=`form`              | Job title / role name                                    |
| `jd_company`          | String  | No                          | Company name (form mode)                                 |
| `jd_skills`           | String  | No                          | Comma-separated skills (form mode)                       |
| `jd_experience_years` | Integer | No                          | Required years of experience (form mode)                 |
| `jd_industry`         | String  | No                          | Industry/domain (form mode)                              |
| `jd_extra_details`    | String  | No                          | Free-text additional details (form mode)                 |

> ⚠️ Sending **both** `resume_file` and `resume_id` returns 400. Sending **neither** also returns 400.

**Resume deduplication:** When uploading via `resume_file`, the backend computes a SHA-256 hash of the PDF. If the same file was uploaded before by this user, the existing stored file is reused (no duplicate storage). This is transparent to the frontend.

**Response (202 Accepted):**
```json
{
  "id": 42,
  "status": "processing"
}
```

After receiving the `id`, begin [polling for status](#13-polling-for-analysis-status).

**Errors:**

| Code | Condition | Example Response |
|------|-----------|-----------------|
| 400  | Neither file nor id | `{ "non_field_errors": ["Either \"resume_file\" or \"resume_id\" is required."] }` |
| 400  | Both file and id | `{ "non_field_errors": ["Provide either \"resume_file\" or \"resume_id\", not both."] }` |
| 400  | Validation error | `{ "resume_file": ["Only PDF files are accepted."] }` |
| 400  | Bad PDF content | `{ "resume_file": ["File content does not appear to be a valid PDF."] }` |
| 400  | File too large | `{ "resume_file": ["Resume file must be under 5MB."] }` |
| 400  | Plan file size limit | `{ "detail": "Your plan limits resume files to X MB." }` |
| 400  | Invalid resume_id | `{ "resume_id": ["Resume not found or does not belong to you."] }` |
| 400  | Missing JD fields | `{ "jd_text": ["Job description text is required when input type is \"text\"."] }` |
| 403  | Monthly quota reached | `{ "detail": "Monthly analysis limit reached (X/X). Upgrade your plan.", "limit": X, "used": X }` |
| 403  | Max resumes stored | `{ "detail": "Resume storage limit reached (X). Delete old resumes or upgrade.", "limit": X, "stored": X }` |
| 409  | Duplicate submit | `{ "detail": "An analysis is already being submitted. Please wait." }` |
| 429  | Rate limited | `{ "detail": "Request was throttled. Expected available in 120 seconds." }` |

> **New:** The response on `202 Accepted` may include a `duplicate_resume_warning` field if the same resume was previously analyzed:
>
> ```json
> { "id": 42, "status": "processing", "duplicate_resume_warning": "This resume has been analyzed before." }
> ```

> **Backend sync (v0.30.0):** After a successful analysis, the backend automatically:
> 1. Saves the JD as a `DiscoveredJob` with `source = "user_analysis"` (upserted by URL or analysis ID).
> 2. Computes a pgvector embedding for the job so it appears in personalised feed results.
> 3. If the Crawler Bot integration is configured, pushes the company and job to the Crawler Bot DB so both databases stay in sync.
>
> This is entirely transparent to the frontend — **no request/response changes**. Jobs created this way appear in `/api/v1/feed/jobs/` alongside crawler-sourced jobs, identifiable by `source: "user_analysis"`.

**Example — New file upload (multipart/form-data):**
```js
const formData = new FormData();
formData.append('resume_file', fileInput.files[0]);
formData.append('jd_input_type', 'text');
formData.append('jd_text', 'We need a senior Python developer...');

const { data } = await api.post('/analyze/', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
});
// data = { id: 42, status: "processing", credits_used: 1, balance: 4 }
```

**Example — Reuse existing resume (JSON):**
```js
const { data } = await api.post('/analyze/', {
  resume_id: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',  // from GET /api/v1/resumes/
  jd_input_type: 'text',
  jd_text: 'We need a senior Python developer...',
});
// data = { id: 43, status: "processing", credits_used: 1, balance: 3 }
```

---

### GET `/api/v1/analyses/` — List Analyses (Paginated)

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Returns **paginated** list of the user's own analyses, newest first.

Only returns **active** (non-soft-deleted) analyses.

**Query parameters:**

| Param       | Default          | Description |
|-------------|------------------|-------------|
| `page`      | 1                | Page number (20 items per page) |
| `search`    | —                | Search by `jd_role`, `jd_company`, or `jd_industry` (case-insensitive contains) |
| `status`    | —                | Filter by status: `pending`, `processing`, `done`, `failed` |
| `score_min` | —                | Filter analyses with `ats_score >= score_min` |
| `score_max` | —                | Filter analyses with `ats_score <= score_max` |
| `ordering`  | `-created_at`    | Sort field. Prefix with `-` for descending. Options: `created_at`, `ats_score` |

**Examples:**
```
GET /api/v1/analyses/?search=backend&status=done&score_min=70&ordering=-ats_score
GET /api/v1/analyses/?search=google&ordering=created_at&page=2
```

**Response (200):**
```json
{
  "count": 47,
  "next": "http://localhost:8000/api/v1/analyses/?page=3",
  "previous": "http://localhost:8000/api/v1/analyses/?page=1",
  "results": [
    {
      "id": 42,
      "jd_role": "Backend Engineer",
      "jd_company": "Acme Corp",
      "status": "done",
      "pipeline_step": "done",
      "overall_grade": "B",
      "ats_score": 78,
      "ai_provider_used": "OpenRouterProvider",
      "report_pdf_url": "https://r2.example.com/reports/report_42.pdf",
      "share_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "share_url": "https://yourhost.com/api/v1/shared/a1b2c3d4-e5f6-7890-abcd-ef1234567890/",
      "created_at": "2026-02-22T14:30:00Z"
    }
  ]
}
```

**List item fields:**

| Field              | Type           | Description                                  |
|--------------------|----------------|----------------------------------------------|
| `id`               | int            | Analysis ID                                  |
| `jd_role`          | string         | Job title (may be empty if analysis pending) |
| `jd_company`       | string         | Company name                                 |
| `status`           | string         | `"pending"` / `"processing"` / `"done"` / `"failed"` |
| `pipeline_step`    | string         | Current step in the pipeline                  |
| `overall_grade`    | string         | Letter grade `"A"` through `"F"` (empty if not complete) |
| `ats_score`        | int \| null    | ATS score (null if not complete)             |
| `ai_provider_used` | string         | AI model that performed the analysis         |
| `report_pdf_url`   | string \| null | URL to pre-generated PDF report              |
| `share_token`      | UUID \| null   | Share token (null if not shared)             |
| `share_url`        | string \| null | Public share URL (null if not shared)        |
| `created_at`       | datetime       | When the analysis was submitted              |

---

### GET `/api/v1/analyses/<id>/` — Analysis Detail

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Returns the full analysis with all results, nested scrape result, and LLM response.

Returns 404 if the analysis is soft-deleted or belongs to another user.

**Response (200):** See [Detail Response Schema](#detail-response-schema) in section 9.

---

### GET `/api/v1/analyses/<id>/status/` — Poll Status (Lightweight)

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Ultra-fast polling endpoint — reads from Redis cache first, falls back to DB.

**Response (200):**
```json
{
  "status": "processing",
  "pipeline_step": "llm_call",
  "overall_grade": "",
  "ats_score": null,
  "error_message": ""
}
```

| Field           | Type          | Description                                          |
|-----------------|---------------|------------------------------------------------------|
| `status`        | string        | `"pending"` / `"processing"` / `"done"` / `"failed"` |
| `pipeline_step` | string        | Current pipeline step (see [Polling](#13-polling-for-analysis-status)) |
| `overall_grade` | string        | Letter grade `"A"`–`"F"` (empty string until done)    |
| `ats_score`     | int \| null   | Generic ATS score 0-100 (null until done)            |
| `error_message` | string        | Error details (empty on success / in-progress)       |

See [Polling for Analysis Status](#13-polling-for-analysis-status) for the full polling implementation guide.

---

### POST `/api/v1/analyses/<id>/retry/` — Retry Failed Analysis

🔒 Requires auth. **Throttled:** `analyze` scope (10/hour per user).

Retries a failed analysis from its last incomplete pipeline step. Does not require re-uploading the resume.

**Request:** Empty body (no payload needed).

**Response (202 Accepted):**
```json
{
  "id": 42,
  "status": "processing",
  "pipeline_step": "llm_call",
  "credits_used": 1,
  "balance": 3
}
```

| Field          | Type | Description                          |
|----------------|------|--------------------------------------|
| `credits_used` | int  | Credits consumed by the retry        |
| `balance`      | int  | Remaining wallet balance after deduction |

After receiving 202, begin [polling for status](#13-polling-for-analysis-status) again.

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Already complete | `{ "detail": "This analysis is already complete." }` |
| 402  | Insufficient credits | `{ "detail": "Insufficient credits.", "balance": 0, "cost": 1 }` |
| 404  | Not found / not owner | `{ "detail": "Analysis not found." }` |
| 409  | Already processing | `{ "detail": "This analysis is already being processed." }` |

---

### DELETE `/api/v1/analyses/<id>/delete/` — Soft-Delete Analysis

🔒 Requires auth. **Throttled:** `write` scope (60/hour).

Performs a **soft-delete** — the analysis row is preserved in the database with lightweight metadata for analytics, but is removed from all list/detail views.

**What happens on soft-delete:**
- `deleted_at` timestamp is set
- Heavy text fields cleared (`resume_text`, `resolved_jd`, `jd_text`)
- Report PDF deleted from R2 storage
- Orphaned `ScrapeResult` and `LLMResponse` rows cleaned up
- Lightweight metadata preserved: `ats_score`, `jd_role`, `jd_company`, `status`, `created_at`
- The analysis **no longer appears** in `GET /api/v1/analyses/` list or `GET /api/v1/analyses/<id>/` detail
- Soft-deleted analyses **are counted** in `GET /api/v1/dashboard/stats/` for audit trail

**Response (204):** No content.

**Error (404):** `{ "detail": "Not found." }` — Analysis doesn't exist, already soft-deleted, or belongs to another user.

**Frontend action:** Remove the analysis from local state/cache after a successful 204. No need to check `deleted_at` fields — the backend handles filtering automatically.

---

### GET `/api/v1/analyses/<id>/export-pdf/` — Download PDF Report

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour).

If a pre-generated PDF exists (stored in Cloudflare R2), returns a **302 redirect** to the signed URL. Otherwise generates on-the-fly and returns the PDF bytes directly.

**Response:**
- **302 Redirect** → R2 signed URL (when pre-generated PDF exists)
- **200** with `Content-Type: application/pdf` (on-the-fly fallback)
- **Content-Disposition:** `attachment; filename="resume_ai_<role>_<id>.pdf"`

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Analysis not complete | `{ "detail": "Analysis is not complete yet." }` |
| 404  | Not found | `{ "detail": "Not found." }` |

**Frontend tip:** Use `window.open()` or an `<a>` tag with the URL to trigger the browser's native download behavior. If using Axios, set `responseType: 'blob'`.

```js
// Option 1: Browser native download
window.open(`${API_URL}/analyses/${id}/export-pdf/`, '_blank');

// Option 2: Axios blob download
const response = await api.get(`/analyses/${id}/export-pdf/`, {
  responseType: 'blob',
});
const url = URL.createObjectURL(response.data);
const a = document.createElement('a');
a.href = url;
a.download = `resume_analysis_${id}.pdf`;
a.click();
URL.revokeObjectURL(url);
```

> **Plan feature flag:** If the user's plan has `pdf_export: false`, this endpoint returns `403 Forbidden` with `{ "detail": "PDF export requires a higher plan." }`.

---

### POST `/api/v1/analyses/<id>/cancel/` — Cancel Stuck Analysis

🔒 Requires auth. **Throttled:** `write` scope (30/hour).

Cancel a processing analysis. Revokes the Celery task, marks as failed, and refunds any deducted credits.

**Request body:** None.

**Response (200):**
```json
{
  "id": 42,
  "status": "failed",
  "detail": "Analysis cancelled and credits refunded."
}
```

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Not processing | `{ "detail": "Only processing analyses can be cancelled." }` |
| 404  | Not found | `{ "detail": "Not found." }` |

**Frontend tip:** Show a "Cancel" button on analyses that have been processing for more than 2-3 minutes.

```js
await api.post(`/analyses/${id}/cancel/`);
// Refresh analysis list or update local state
```

---

### POST `/api/v1/analyses/bulk-delete/` — Bulk Soft-Delete Analyses

🔒 Requires auth. **Throttled:** `write` scope (30/hour).

Soft-delete multiple analyses at once. Maximum 50 per request.

**Request body:**
```json
{ "ids": [1, 2, 3] }
```

**Response (200):**
```json
{
  "deleted": 3,
  "requested": 3
}
```

| Field       | Type | Description                                      |
|-------------|------|--------------------------------------------------|
| `deleted`   | int  | Number actually soft-deleted (owned by user)      |
| `requested` | int  | Number of IDs submitted                           |

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Empty/missing ids | `{ "detail": "Provide a non-empty list of analysis IDs in \"ids\"." }` |
| 400  | Over 50 ids | `{ "detail": "Cannot delete more than 50 analyses at once." }` |

```js
const { data } = await api.post('/analyses/bulk-delete/', {
  ids: selectedAnalysisIds,
});
// data.deleted = number actually removed
```

---

### GET `/api/v1/analyses/<id>/export-json/` — Download Analysis as JSON

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour).

Download the full analysis data as a JSON file attachment.

**Response (200):**
- `Content-Type: application/json`
- `Content-Disposition: attachment; filename="analysis_<role>_<id>.json"`

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Not complete | `{ "detail": "Analysis must be complete to export." }` |
| 404  | Not found | `{ "detail": "Not found." }` |

```js
const response = await api.get(`/analyses/${id}/export-json/`, {
  responseType: 'blob',
});
const url = URL.createObjectURL(response.data);
const a = document.createElement('a');
a.href = url;
a.download = `analysis_${id}.json`;
a.click();
URL.revokeObjectURL(url);
```

---

### GET `/api/v1/account/export/` — GDPR Data Export

🔒 Requires auth. **Throttled:** `write` scope (30/hour).

Download all user data as a JSON file (GDPR compliance). Includes profile, analyses, resumes, wallet, consent logs, notifications.

**Response (200):**
- `Content-Type: application/json`
- `Content-Disposition: attachment; filename="i-luffy-data-export-<username>.json"`

**Response structure:**
```json
{
  "export_date": "2026-02-27T15:00:00.000Z",
  "profile": { "username": "...", "email": "...", "plan": "Free", ... },
  "analyses": [{ "id": 1, "jd_role": "...", "ats_score": 78, ... }],
  "resumes": [{ "id": "uuid", "original_filename": "resume.pdf", ... }],
  "wallet": { "balance": 5, "transactions": [...] },
  "consent_logs": [{ "consent_type": "terms_privacy", "agreed": true, ... }],
  "notifications": [{ "title": "...", "body": "...", "is_read": false, ... }]
}
```

**Frontend tip:** Add a "Download My Data" button in account settings.

```js
const response = await api.get('/account/export/', { responseType: 'blob' });
const url = URL.createObjectURL(response.data);
const a = document.createElement('a');
a.href = url;
a.download = 'my-data-export.json';
a.click();
URL.revokeObjectURL(url);
```

---

## 5. Resume Endpoints

All prefixed with `/api/v1/`.

Resume files are **deduplicated by SHA-256 hash per user** — uploading the same PDF for multiple analyses stores the file only once. Each unique file gets a `Resume` row with a UUID primary key.

### Default Resume Concept

Each user has exactly **one** default resume at a time. The default resume is the source of truth for all personalised surfaces:

- **Dashboard analytics** — score trend, grade distribution, keyword gaps, avg ATS score, industry benchmark percentile
- **Feed job matching** — pgvector embedding similarity uses the default resume's `JobSearchProfile`
- **Skill-gap & market-insights widgets** — skills comparison uses the default resume's extracted skills
- **Recommendations engine** — action cards like "Close your skill gaps" use the default resume's profile

**Behaviour rules:**
1. The **first resume uploaded** is automatically set as the default.
2. Subsequent uploads do **not** change the default — the user must explicitly switch.
3. Call `POST /api/v1/resumes/<uuid>/set-default/` to change the default.
4. If the default resume is **deleted**, the most recently uploaded remaining resume is auto-promoted.
5. If the last resume is deleted, `default_resume_id` becomes `null` in dashboard responses.
6. Only one resume can be default at a time (DB-enforced unique constraint).

---

### GET `/api/v1/resumes/` — List Resumes (Paginated)

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Returns **paginated** list of the user's deduplicated resume files, newest first.

**Query parameters:**

| Param      | Default | Description |
|------------|---------|-------------|
| `page`     | 1       | Page number (20 items per page) |
| `search`   | —       | Search by `original_filename` (case-insensitive contains) |
| `ordering` | `-uploaded_at` | Sort field. Prefix with `-` for descending. Options: `uploaded_at`, `original_filename`, `file_size` |

**Response (200):**
```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "original_filename": "my_resume_2026.pdf",
      "file_size_bytes": 245760,
      "uploaded_at": "2026-02-23T10:00:00Z",
      "active_analysis_count": 3,
      "file_url": "https://r2.example.com/resumes/my_resume_2026.pdf",
      "days_since_upload": 4,
      "last_analyzed_at": "2026-02-25T14:00:00Z",
      "is_default": true,
      "processing_status": "done",
      "parsed_content": { "contact": { "name": "John Doe", "..." : "..." }, "..." : "..." },
      "career_profile": { "target_roles": ["Backend Engineer"], "skills": ["Python", "Django"], "..." : "..." }
    }
  ]
}
```

**Response fields:**

| Field                  | Type     | Description                                                |
|------------------------|----------|------------------------------------------------------------|
| `id`                   | UUID     | Resume unique identifier                                   |
| `original_filename`    | string   | Original uploaded filename (e.g., `"my_resume.pdf"`)       |
| `file_size_bytes`      | int      | File size in bytes (use for display: `245760` → `"240 KB"`) |
| `uploaded_at`          | datetime | When first uploaded (ISO 8601)                             |
| `active_analysis_count`| int      | Number of active (non-soft-deleted) analyses using this resume |
| `file_url`             | string ǀ null | Full URL to download the resume PDF (from R2/storage)  |
| `days_since_upload`    | int      | Number of days since the resume was uploaded. Use for staleness indicators (e.g., "Resume not updated in 30 days") |
| `last_analyzed_at`     | datetime ǀ null | Timestamp of the most recent completed analysis using this resume; `null` if never analyzed |
| `is_default`           | bool     | `true` if this is the user's default resume powering dashboard/feed/skill-gap. Exactly one resume is `true` at a time. |
| `processing_status`    | string   | Upload-time processing status: `"pending"`, `"processing"`, `"done"`, or `"failed"`. Resume parsing and career profile extraction happen automatically on upload. |
| `parsed_content`       | object ǀ null | Structured resume data extracted at upload time (contact, summary, experience, education, skills, etc.). `null` until `processing_status` is `"done"`. See [Parsed Content Schema](#parsed-content-schema). |
| `career_profile`       | object ǀ null | Career profile extracted at upload time (target roles, skills, preferences, experience level). Used for job matching and feed personalisation. `null` until `processing_status` is `"done"`. |

**Frontend usage:** Use `active_analysis_count` to show how many analyses reference each resume, and to determine whether the delete button should show a warning.

> **v0.34.0 change:** Resume understanding (parsing + career profile extraction) now happens automatically at **upload time** instead of during each analysis. The `processing_status` field tracks this background task. When `processing_status` is `"done"`, `parsed_content` and `career_profile` are available immediately — no analysis is required.

---

### DELETE `/api/v1/resumes/<uuid:id>/` — Delete Resume

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Permanently deletes the resume file from R2 storage.

**Blocked if active analyses exist.** Only allowed when `active_analysis_count === 0` (no active, non-soft-deleted analyses reference this resume). If active analyses exist, returns **409 Conflict**.

**Response (204):** No content — resume and file permanently deleted.

**Default resume fallback:** If the deleted resume was the default, the most recently uploaded remaining resume is automatically promoted to default. If no resumes remain, `default_resume_id` becomes `null`.

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 404  | Not found / not owner | `{ "detail": "Not found." }` |
| 409  | Active analyses exist | `{ "detail": "Cannot delete: 2 active analysis(es) still reference this resume." }` |
| 409  | Active job alerts exist | `{ "detail": "Cannot delete: 1 active job alert(s) still reference this resume. Deactivate them first." }` |

**Frontend recommendation:**
```jsx
// Before calling delete, check active_analysis_count from the list
if (resume.active_analysis_count > 0) {
  alert(`This resume is used by ${resume.active_analysis_count} active analyses. ` +
        `Delete those analyses first.`);
  return;
}

try {
  await api.delete(`/resumes/${resume.id}/`);
  // Remove from local state
} catch (err) {
  if (err.response?.status === 409) {
    alert(err.response.data.detail);
  }
}
```

---

### POST `/api/v1/resumes/<uuid:id>/set-default/` — Set Default Resume

🔒 Requires auth. **Throttled:** `write` scope (60/hour). Sets the specified resume as the user's default resume.

The default resume powers all personalised surfaces (dashboard analytics, feed job matching, skill-gap, recommendations). Changing the default immediately busts the cached dashboard stats so the next dashboard request reflects the new resume.

**Request:** No body required — the resume is identified by the URL parameter.

**Response (200):**
```json
{
  "detail": "Default resume updated.",
  "resume_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "original_filename": "my_resume_2026.pdf"
}
```

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 404  | Not found / not owner | `{ "detail": "Not found." }` |
| 401  | Not authenticated | Standard 401 response |

**Frontend recommendation:**
```jsx
// "Set as default" button on resume list
const setDefault = async (resumeId) => {
  await api.post(`/resumes/${resumeId}/set-default/`);
  // Refresh resume list to update is_default flags
  // Invalidate dashboard cache on client side
};
```

---

### POST `/api/v1/resumes/bulk-delete/` — Bulk Delete Resumes

🔒 Requires auth. **Throttled:** `write` scope (60/hour). Delete up to 50 resumes in a single request. Resumes with active (processing/pending) analyses are **skipped** (not deleted).

**Request (JSON):**
```json
{
  "ids": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "b2c3d4e5-f6a7-8901-bcde-f12345678901"
  ]
}
```

**Response (200):**
```json
{
  "deleted": 1,
  "skipped": 1,
  "errors": [
    "Resume b2c3d4e5... skipped: has 1 active analysis(es)"
  ]
}
```

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Empty `ids` list | `{ "ids": ["This list may not be empty."] }` |
| 400  | Too many items | `{ "ids": ["Ensure this field has no more than 50 elements."] }` |

---

### GET `/api/v1/analyses/compare/` — Compare Analyses Side-by-Side

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Compare 2–5 analyses in a single response. All analyses must belong to the authenticated user.

**Query parameters:**

| Param | Required | Description |
|-------|----------|-------------|
| `ids` | ✅       | Comma-separated analysis IDs (2–5) |

**Example:** `GET /api/v1/analyses/compare/?ids=42,43,44`

**Response (200):**
```json
[
  {
    "id": 42,
    "jd_role": "Backend Engineer",
    "jd_company": "Acme Corp",
    "ats_score": 78,
    "overall_grade": "B",
    "created_at": "2026-02-22T14:30:00Z",
    "scores": { "generic_ats": 78, "workday_ats": 65, "greenhouse_ats": 70, "keyword_match_percent": 58 }
  },
  {
    "id": 43,
    "jd_role": "Full Stack Developer",
    "jd_company": "BigCo",
    "ats_score": 85,
    "overall_grade": "A",
    "created_at": "2026-02-23T10:00:00Z",
    "scores": { "generic_ats": 85, "workday_ats": 78, "greenhouse_ats": 80, "keyword_match_percent": 72 }
  }
]
```

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Missing `ids` | `{ "detail": "Provide 'ids' query parameter with comma-separated analysis IDs." }` |
| 400  | Fewer than 2 IDs | `{ "detail": "Provide at least 2 analysis IDs to compare." }` |
| 400  | More than 5 IDs | `{ "detail": "Maximum 5 analyses can be compared at once." }` |
| 404  | ID not found / not owner | `{ "detail": "One or more analyses not found." }` |

---

## 6. Dashboard Endpoints

### GET `/api/v1/dashboard/stats/` — User Dashboard Analytics

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Returns aggregated analytics. Overview counts (`total_analyses`, `resume_count`, etc.) cover **all** analyses. Personalised analytics (`average_ats_score`, `score_trend`, `grade_distribution`, `top_missing_keywords`, `keyword_match_trend`, `industry_benchmark_percentile`) are scoped to the **default resume's** analyses only (falls back to all analyses if no default is set).

**Response (200):**
```json
{
  "default_resume_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "total_analyses": 47,
  "active_analyses": 42,
  "deleted_analyses": 5,
  "average_ats_score": 76.3,
  "best_ats_score": 95,
  "worst_ats_score": 38,
  "score_trend": [
    {
      "ats_score": 85,
      "generic_ats": 85,
      "workday_ats": 78,
      "greenhouse_ats": 80,
      "keyword_match_percent": 72,
      "jd_role": "Senior Developer",
      "created_at": "2026-02-23T14:00:00Z"
    },
    {
      "ats_score": 72,
      "generic_ats": 72,
      "workday_ats": 65,
      "greenhouse_ats": 68,
      "keyword_match_percent": 58,
      "jd_role": "Backend Engineer",
      "created_at": "2026-02-22T10:00:00Z"
    }
  ],
  "grade_distribution": {
    "A": 5,
    "B": 18,
    "C": 12,
    "D": 5,
    "F": 2
  },
  "top_roles": [
    { "jd_role": "Backend Engineer", "count": 12 },
    { "jd_role": "Full Stack Developer", "count": 8 },
    { "jd_role": "DevOps Engineer", "count": 5 },
    { "jd_role": "ML Engineer", "count": 3 },
    { "jd_role": "Frontend Developer", "count": 2 }
  ],
  "top_industries": [
    { "jd_industry": "Technology", "count": 20 },
    { "jd_industry": "Finance", "count": 10 },
    { "jd_industry": "Healthcare", "count": 5 }
  ],
  "analyses_per_month": [
    { "month": "2025-09-01T00:00:00Z", "count": 3 },
    { "month": "2025-10-01T00:00:00Z", "count": 7 },
    { "month": "2025-11-01T00:00:00Z", "count": 10 },
    { "month": "2025-12-01T00:00:00Z", "count": 5 },
    { "month": "2026-01-01T00:00:00Z", "count": 15 },
    { "month": "2026-02-01T00:00:00Z", "count": 7 }
  ],
  "top_missing_keywords": [
    { "keyword": "kubernetes", "count": 8 },
    { "keyword": "docker", "count": 6 },
    { "keyword": "ci/cd", "count": 5 }
  ],
  "keyword_match_trend": [
    {
      "jd_role": "Senior Developer",
      "keyword_match_percent": 72,
      "created_at": "2026-02-23T14:00:00Z"
    },
    {
      "jd_role": "Backend Engineer",
      "keyword_match_percent": 58,
      "created_at": "2026-02-22T10:00:00Z"
    }
  ],
  "credit_usage": [
    { "month": "2026-01", "type": "debit", "subtype": "analysis", "count": 12, "total": 12 },
    { "month": "2026-01", "type": "credit", "subtype": "plan", "count": 1, "total": 50 },
    { "month": "2026-02", "type": "debit", "subtype": "analysis", "count": 5, "total": 5 },
    { "month": "2026-02", "type": "credit", "subtype": "topup", "count": 1, "total": 20 }
  ],
  "resume_count": 3,
  "generated_resumes_total": 18,
  "generated_resumes_done": 15,
  "interview_preps_total": 6,
  "interview_preps_done": 5,
  "cover_letters_total": 8,
  "cover_letters_done": 7,
  "chat_sessions_active": 1,
  "chat_sessions_completed": 4,
  "job_alerts_count": 3,
  "active_job_alerts": 2,
  "weekly_job_matches": 14,
  "total_job_matches": 87,
  "matches_applied": 5,
  "matches_relevant": 22,
  "matches_irrelevant": 8,
  "llm_calls": 142,
  "llm_tokens_used": 1843200,
  "llm_cost_usd": 3.24,
  "plan_usage": {
    "plan_name": "Pro",
    "analyses_this_month": 7,
    "analyses_limit": 30,
    "usage_percent": 23.3
  },
  "industry_benchmark_percentile": 72.5,
  "activity_streak": {
    "streak_days": 5,
    "actions_this_month": 23
  }
}
```

**Response fields:**

| Field                | Type           | Description                                                 |
|----------------------|----------------|-------------------------------------------------------------|
| `default_resume_id`  | UUID \| null   | ID of the resume powering personalised analytics; `null` if no default is set |
| `total_analyses`     | int            | All analyses ever created (including soft-deleted) — **user-wide** |
| `active_analyses`    | int            | Non-deleted analyses — **user-wide**                        |
| `deleted_analyses`   | int            | Soft-deleted analyses — **user-wide**                       |
| `average_ats_score`  | float \| null  | Average ATS score — **scoped to default resume** (fallback: all) |
| `best_ats_score`     | int \| null    | Highest ATS score — **scoped to default resume**             |
| `worst_ats_score`    | int \| null    | Lowest ATS score — **scoped to default resume**              |
| `score_trend`        | array          | Last **10** completed analyses — **scoped to default resume** (newest first) |
| `grade_distribution` | object         | Per-grade counts — **scoped to default resume** (e.g., `{"A": 5, "B": 18}`) |
| `top_roles`          | array          | Top **5** most-analyzed job roles with count                 |
| `top_industries`     | array          | Top **5** most-analyzed industries with count                |
| `analyses_per_month` | array          | Monthly analysis count for the last **6 months** (oldest first) |
| `top_missing_keywords` | array        | Top **10** missing keywords across the user's last 20 analyses (descending by count) |
| `keyword_match_trend` | array         | Keyword match % from last 10 completed analyses (newest first, parallel to `score_trend`) |
| `credit_usage`       | array          | Wallet transactions grouped by month and transaction type, each with `{month, type, subtype, count, total}` |
| `resume_count`       | int            | Total uploaded resumes                                       |
| `generated_resumes_total` | int       | Total generated resume jobs                                  |
| `generated_resumes_done`  | int       | Completed generated resumes                                  |
| `interview_preps_total` | int         | Total interview prep jobs                                    |
| `interview_preps_done`  | int         | Completed interview preps                                    |
| `cover_letters_total` | int           | Total cover letter jobs                                      |
| `cover_letters_done`  | int           | Completed cover letters                                      |
| `chat_sessions_active` | int          | Active resume chat builder sessions                          |
| `chat_sessions_completed` | int       | Completed resume chat builder sessions                       |
| `job_alerts_count`   | int            | Total job alerts created                                     |
| `active_job_alerts`  | int            | Currently active job alerts                                  |
| `weekly_job_matches` | int            | Job matches created in the last 7 days                       |
| `total_job_matches`  | int            | All-time job matches across all alerts                       |
| `matches_applied`    | int            | Job matches user marked as "applied"                         |
| `matches_relevant`   | int            | Job matches user marked as "relevant"                        |
| `matches_irrelevant` | int            | Job matches user marked as "irrelevant"                      |
| `llm_calls`          | int            | Total completed LLM API calls                                |
| `llm_tokens_used`    | int            | Total tokens consumed across all LLM calls                   |
| `llm_cost_usd`       | float          | Estimated total LLM cost in USD                              |
| `plan_usage`         | object \| null | Current plan usage breakdown; `null` if no plan or unlimited  |
| `industry_benchmark_percentile` | float \| null | User's ATS score percentile rank vs all platform users (0–100); `null` if no completed analyses |
| `activity_streak`    | object         | User's daily activity streak and current-month action count   |

**`score_trend` item:**

| Field            | Type         | Description                                   |
|------------------|--------------|-----------------------------------------------|
| `ats_score`      | int          | Overall ATS score (0-100)                     |
| `generic_ats`    | int \| null  | Generic ATS score from `scores` JSON          |
| `workday_ats`    | int \| null  | Workday ATS score from `scores` JSON          |
| `greenhouse_ats` | int \| null  | Greenhouse ATS score from `scores` JSON       |
| `keyword_match_percent` | int \| null | Keyword match percentage from `scores` JSON |
| `jd_role`        | string       | Job role analyzed                             |
| `created_at`     | datetime     | When analysis was submitted                   |

**`keyword_match_trend` item:**

| Field                  | Type     | Description                                   |
|------------------------|----------|-----------------------------------------------|
| `jd_role`              | string   | Job role analyzed                             |
| `keyword_match_percent`| int      | Keyword match percentage (0-100)              |
| `created_at`           | datetime | When analysis was submitted                   |

**`credit_usage` item (v0.29.0 — fixed data contract):**

| Field     | Type   | Description                                                        |
|-----------|--------|--------------------------------------------------------------------|
| `month`   | string | Month in `"YYYY-MM"` format (e.g., `"2026-01"`)                   |
| `type`    | string | `"debit"` or `"credit"` — direction of the transaction             |
| `subtype` | string | Specific kind: `"analysis"`, `"topup"`, `"plan"`, `"refund"`, `"upgrade_bonus"`, `"admin"` |
| `count`   | int    | Number of transactions in this group                               |
| `total`   | int    | Absolute sum of amounts (always positive)                          |

> **⚠ Breaking change (v0.29.0):** `credit_usage` items now include `subtype` and `count` fields. The `type` field maps from raw `transaction_type` (e.g., `analysis_debit` → `"debit"`, `topup` → `"credit"`). See migration notes below.

**`plan_usage` object:**

| Field               | Type   | Description                                    |
|----------------------|--------|------------------------------------------------|
| `plan_name`          | string | Name of the user's current plan                |
| `analyses_this_month`| int    | Analyses submitted this calendar month          |
| `analyses_limit`     | int    | Monthly analysis limit from plan                |
| `usage_percent`      | float  | `(analyses_this_month / analyses_limit) * 100`  |

**`activity_streak` object:**

| Field              | Type | Description                                           |
|--------------------|------|-------------------------------------------------------|
| `streak_days`      | int  | Consecutive days with at least one recorded action     |
| `actions_this_month` | int | Total actions recorded in the current calendar month |

**`top_roles` / `top_industries` item:**

| Field        | Type   | Description                |
|--------------|--------|----------------------------|
| `jd_role` / `jd_industry` | string | Role or industry name |
| `count`      | int    | Number of analyses         |

**`analyses_per_month` item:**

| Field   | Type     | Description                                    |
|---------|----------|------------------------------------------------|
| `month` | datetime | First day of the month (ISO 8601)              |
| `count` | int      | Total analyses submitted in that month          |

**Frontend usage suggestions:**

| Data Field               | UI Component             | Library Suggestion     |
|--------------------------|--------------------------|------------------------|
| `total/active/deleted`   | Summary stat cards       | Simple `<div>` cards   |
| `average_ats_score`      | Large gauge/number       | `ScoreGauge` component |
| `best/worst_ats_score`   | Min/max badges           | Simple `<span>` badges |
| `score_trend`            | Line chart               | Chart.js, Recharts     |
| `keyword_match_trend`    | Line chart (overlay)     | Chart.js, Recharts     |
| `top_roles`              | Horizontal bar chart     | Chart.js, Recharts     |
| `analyses_per_month`     | Bar/area chart           | Chart.js, Recharts     |
| `credit_usage`           | Stacked bar (by subtype) | Chart.js, Recharts     |
| `plan_usage`             | Progress bar / ring      | Custom component       |
| `activity_streak`        | Streak counter + fire 🔥 | Custom component       |
| `llm_calls/tokens/cost`  | Stats row                | Simple `<div>` cards   |
| Job match counters       | Summary cards / pie      | Chart.js, Recharts     |

---

## 7. Share Endpoints

Allow users to generate a public, read-only link for a completed analysis. Anyone with the link can view the results — no login required.

### POST `/api/v1/analyses/<id>/share/` — Generate Share Link

🔒 Requires auth. **Throttled:** `write` scope (60/hour). Only works on **completed** (`status: "done"`) analyses.

**Idempotent:** If a share token already exists, returns the existing token (200). Otherwise creates a new one (201).

**Request:** Empty body (no payload needed).

**Response (201 Created / 200 OK):**
```json
{
  "share_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "share_url": "https://yourhost.com/api/v1/shared/a1b2c3d4-e5f6-7890-abcd-ef1234567890/"
}
```

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Analysis not complete | `{ "detail": "Only completed analyses can be shared." }` |
| 403  | Plan restriction | `{ "detail": "Sharing analyses requires a higher plan." }` |
| 404  | Not found / not owner | `{ "detail": "Not found." }` |

**Frontend usage:**
```js
const { data } = await api.post(`/analyses/${id}/share/`);
const fullUrl = `${window.location.origin}/shared/${data.share_token}`;
navigator.clipboard.writeText(fullUrl);
showToast('Share link copied!');
```

---

### DELETE `/api/v1/analyses/<id>/share/` — Revoke Share Link

🔒 Requires auth. **Throttled:** `write` scope (60/hour). Immediately revokes the share token — the public link stops working.

**Request:** Empty body.

**Response (204):** No content.

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Not currently shared | `{ "detail": "This analysis is not currently shared." }` |
| 404  | Not found / not owner | `{ "detail": "Not found." }` |

---

### GET `/api/v1/shared/<token>/` — Public Shared Analysis

🔓 **Public — no auth required.** Returns a curated, read-only subset of the analysis results.

**Sensitive data excluded:** No resume file, no user info, no raw JD text, no celery task ID, no analysis ID.

**Response (200):**
```json
{
  "jd_role": "Backend Engineer",
  "jd_company": "Acme Corp",
  "jd_industry": "Technology/SaaS",
  "status": "done",
  "overall_grade": "B",
  "ats_score": 72,
  "scores": {
    "generic_ats": 72,
    "workday_ats": 61,
    "greenhouse_ats": 68,
    "keyword_match_percent": 58
  },
  "ats_disclaimers": {
    "workday": "Simulated score based on known Workday parsing behavior. Not affiliated with or endorsed by Workday Inc.",
    "greenhouse": "Simulated score based on known Greenhouse parsing behavior. Not affiliated with or endorsed by Greenhouse Software."
  },
  "keyword_analysis": {
    "matched_keywords": ["Python", "SQL", "data analysis"],
    "missing_keywords": ["Power BI", "ETL pipelines", "Agile"],
    "recommended_to_add": [
      "Add Power BI to skills section under tools",
      "Mention ETL pipelines in work experience"
    ]
  },
  "section_feedback": [
    {
      "section_name": "Work Experience",
      "score": 65,
      "feedback": [
        "Most bullets lack quantified impact",
        "Action verbs are weak — replace 'worked on' with owned, led, optimized"
      ],
      "ats_flags": ["Non-standard section title 'Professional Journey'"]
    }
  ],
  "sentence_suggestions": [
    {
      "original": "Worked on building dashboards for the sales team",
      "suggested": "Developed 5 sales performance dashboards using Python and Tableau, reducing reporting time by 40%",
      "reason": "Added specificity, quantified impact, and replaced weak verb"
    }
  ],
  "formatting_flags": [
    "Multi-column layout detected — Workday and many ATS systems parse left column only"
  ],
  "quick_wins": [
    { "priority": 1, "action": "Add missing keywords Power BI, ETL, and Agile" },
    { "priority": 2, "action": "Remove multi-column layout and convert to single column" },
    { "priority": 3, "action": "Quantify at least 5 bullet points with numbers" }
  ],
  "summary": "Strong backend profile with room for DevOps and keyword improvement.",
  "ai_provider_used": "OpenRouterProvider",
  "ai_response_time_seconds": 12.45,
  "created_at": "2026-02-23T14:30:00Z"
}
```

**Shared response fields:**

| Field                  | Type            | Description                                              |
|------------------------|-----------------|----------------------------------------------------------|
| `jd_role`              | string          | Job title                                                |
| `jd_company`           | string          | Company name                                             |
| `jd_industry`          | string          | Industry/domain                                          |
| `status`               | string          | Always `"done"` for shared analyses                      |
| `overall_grade`        | string          | Letter grade `"A"` through `"F"`                         |
| `ats_score`            | int             | Generic ATS score (0-100), same as `scores.generic_ats`  |
| `scores`               | object          | `{ generic_ats, workday_ats, greenhouse_ats, keyword_match_percent }` — all 0-100 |
| `ats_disclaimers`      | object          | `{ workday, greenhouse }` — legal disclaimer strings     |
| `keyword_analysis`     | object          | `{ matched_keywords[], missing_keywords[], recommended_to_add[] }` |
| `section_feedback`     | array           | `[{ section_name, score, feedback[], ats_flags[] }]`     |
| `sentence_suggestions` | array           | `[{ original, suggested, reason }]`                      |
| `formatting_flags`     | string[]        | ATS formatting issues found in the resume                |
| `quick_wins`           | array           | `[{ priority (1-3), action }]` — 1–3 items |
| `summary`              | string          | 2-3 sentence overall summary                             |
| `ai_provider_used`     | string          | AI model identifier                                      |
| `ai_response_time_seconds` | float \| null | Time taken by the LLM to generate the analysis (seconds) |
| `created_at`           | datetime        | When analysis was submitted                              |

**Error (404):**
```json
{ "detail": "Shared analysis not found or link has been revoked." }
```

> **Soft-deleted analyses** are not accessible via share links — the default manager automatically excludes them.

---

### GET `/api/v1/shared/<token>/summary/` — Shared Score Summary

🔓 **Public — no auth required.** Lightweight endpoint returning only score data for social card previews (OG meta tags, share widgets).

**Response (200):**
```json
{
  "ats_score": 72,
  "overall_grade": "B",
  "jd_role": "Backend Engineer",
  "jd_company": "Acme Corp"
}
```

**Error (404):**
```json
{ "detail": "Not found." }
```

---

## 8. Health Check

### GET `/api/v1/health/` — Health Check

🔓 Public (no auth required). Use this to verify backend connectivity before showing the login screen.

**Response (200):**
```json
{ "status": "ok" }
```

**Response (503 Service Unavailable):**
```json
{ "status": "error", "detail": "Database is not reachable" }
```

---

## 9. Response Schemas

### Detail Response Schema

Returned by `GET /api/v1/analyses/<id>/`. This is the full analysis payload with all results.

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
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "parsed_response": { "...see LLM schema in section 10..." },
    "model_used": "anthropic/claude-haiku-4.5",
    "status": "done",
    "error_message": "",
    "duration_seconds": 4.32,
    "created_at": "2026-02-22T14:30:05Z"
  },
  "status": "done",
  "pipeline_step": "done",
  "error_message": "",
  "overall_grade": "B",
  "ats_score": 72,
  "scores": {
    "generic_ats": 72,
    "workday_ats": 61,
    "greenhouse_ats": 68,
    "keyword_match_percent": 58
  },
  "ats_disclaimers": {
    "workday": "Simulated score based on known Workday parsing behavior. Not affiliated with or endorsed by Workday Inc.",
    "greenhouse": "Simulated score based on known Greenhouse parsing behavior. Not affiliated with or endorsed by Greenhouse Software."
  },
  "keyword_analysis": {
    "matched_keywords": ["Python", "Django", "PostgreSQL"],
    "missing_keywords": ["Kubernetes", "Terraform", "CI/CD"],
    "recommended_to_add": [
      "Add Kubernetes to skills section",
      "Mention CI/CD experience in work experience bullets",
      "Add Terraform to infrastructure tools"
    ]
  },
  "section_feedback": [
    {
      "section_name": "Work Experience",
      "score": 65,
      "feedback": [
        "Bullets lack quantified impact — add numbers and percentages",
        "Action verbs are weak — replace 'worked on' with 'architected', 'led', 'optimized'",
        "JD mentions cloud infrastructure but resume does not reference any cloud work"
      ],
      "ats_flags": []
    },
    {
      "section_name": "Skills",
      "score": 70,
      "feedback": [
        "Skills are listed but not categorized",
        "Missing JD keywords: Kubernetes, Terraform, CI/CD"
      ],
      "ats_flags": []
    },
    {
      "section_name": "Summary",
      "score": 80,
      "feedback": [
        "Good keyword presence in summary",
        "Could be more specific to the target role"
      ],
      "ats_flags": []
    }
  ],
  "sentence_suggestions": [
    {
      "original": "Worked on backend services",
      "suggested": "Architected and maintained 12 Python/Django microservices serving 50K+ daily active users, reducing API latency by 40%",
      "reason": "Added specifics, metrics, and strong action verb"
    },
    {
      "original": "Helped with data cleaning tasks",
      "suggested": "Automated data cleaning pipelines using Pandas, processing 500K+ records weekly",
      "reason": "Replaced passive language with ownership verb and added scale"
    }
  ],
  "formatting_flags": [
    "Multi-column layout detected — Workday and many ATS systems parse left column only",
    "Table used in skills section — replace with plain comma-separated list"
  ],
  "quick_wins": [
    { "priority": 1, "action": "Add missing keywords Kubernetes, Terraform, and CI/CD" },
    { "priority": 2, "action": "Remove multi-column layout and convert to single column" },
    { "priority": 3, "action": "Quantify at least 5 bullet points with numbers, percentages, or scale" }
  ],
  "summary": "Strong Python background with relevant experience. Key gaps in DevOps/cloud skills. With targeted keyword additions and bullet point improvements, this resume has strong potential.",
  "parsed_content": {
    "contact": {
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+1-555-0100",
      "location": "San Francisco, CA",
      "linkedin": "https://linkedin.com/in/johndoe",
      "portfolio": "https://johndoe.dev"
    },
    "summary": "Senior software engineer with 8 years of experience.",
    "experience": [
      {
        "title": "Senior Software Engineer",
        "company": "TechCorp Inc.",
        "location": "San Francisco, CA",
        "start_date": "Jan 2020",
        "end_date": "Present",
        "bullets": [
          "Architected and maintained 12 Python/Django microservices",
          "Reduced API latency by 40%"
        ]
      }
    ],
    "education": [
      {
        "degree": "B.S. Computer Science",
        "institution": "Stanford University",
        "location": "Stanford, CA",
        "year": "2016",
        "gpa": "3.9"
      }
    ],
    "skills": {
      "technical": ["Python", "Django", "PostgreSQL", "JavaScript"],
      "tools": ["Docker", "AWS", "Git"],
      "soft": ["Leadership", "Communication"]
    },
    "certifications": [],
    "projects": []
  },
  "ai_provider_used": "OpenRouterProvider",
  "report_pdf_url": "https://r2.example.com/reports/report_42.pdf",
  "share_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "share_url": "https://yourhost.com/api/v1/shared/a1b2c3d4-e5f6-7890-abcd-ef1234567890/",
  "created_at": "2026-02-22T14:30:00Z",
  "updated_at": "2026-02-22T14:30:12Z"
}
```

**Detail field reference:**

| Field                  | Type            | Description                                              |
|------------------------|-----------------|----------------------------------------------------------|
| `id`                   | int             | Analysis ID                                              |
| `resume_file`          | string          | Relative storage path to the uploaded resume             |
| `resume_file_url`      | string \| null  | Full URL to download the resume PDF from R2              |
| `jd_input_type`        | string          | `"text"` / `"url"` / `"form"`                           |
| `jd_text`              | string          | Raw JD text (empty if type is url/form)                  |
| `jd_url`               | string          | JD source URL (empty if type is text/form)               |
| `jd_role`              | string          | Job title — always populated on completed analyses       |
| `jd_company`           | string          | Company name (may be empty)                              |
| `jd_skills`            | string          | Comma-separated skills from the JD                       |
| `jd_experience_years`  | int \| null     | Required experience years                                |
| `jd_industry`          | string          | Industry/domain                                          |
| `jd_extra_details`     | string          | Additional JD context extracted by LLM                   |
| `resolved_jd`          | string          | Final resolved JD text sent to the LLM                   |
| `scrape_result`        | object \| null  | Nested scrape result (only for `jd_input_type: "url"`)   |
| `llm_response`         | object \| null  | Nested LLM response (null until LLM step completes)      |
| `status`               | string          | `"pending"` / `"processing"` / `"done"` / `"failed"`    |
| `pipeline_step`        | string          | Current pipeline step (see polling section)              |
| `error_message`        | string          | Error details (empty on success)                         |
| `overall_grade`        | string          | Letter grade `"A"` through `"F"` (empty if not complete) |
| `ats_score`            | int \| null     | Generic ATS score 0-100 (same as `scores.generic_ats`)   |
| `scores`               | object \| null  | `{ generic_ats, workday_ats, greenhouse_ats, keyword_match_percent }` — all integers 0-100 |
| `ats_disclaimers`      | object \| null  | `{ workday, greenhouse }` — legal disclaimer strings for simulated ATS scores |
| `keyword_analysis`     | object \| null  | `{ matched_keywords[], missing_keywords[], recommended_to_add[] }` — full keyword breakdown |
| `section_feedback`     | array \| null   | `[{ section_name, score (0-100), feedback[], ats_flags[] }]` — per-section analysis |
| `sentence_suggestions` | array \| null   | `[{ original, suggested, reason }]` — up to 10 weak sentences flagged |
| `formatting_flags`     | string[] \| null| ATS formatting issues found (e.g., multi-column layout, tables) |
| `quick_wins`           | array \| null   | `[{ priority (1-3), action }]` — 1–3 items  |
| `summary`              | string          | 2-3 sentence overall summary of quality and fit          |
| `parsed_content`       | object \| null  | Structured resume data — sourced from the Resume model (upload-time extraction) with fallback to analysis-time extraction for older analyses. See [Parsed Content Schema](#parsed-content-schema) below. `null` if extraction failed or hasn't run yet. |
| `ai_provider_used`     | string          | AI model identifier (e.g., `"OpenRouterProvider"`)       |
| `report_pdf_url`       | string \| null  | URL to pre-generated PDF report in R2                    |
| `share_token`          | UUID \| null    | Share token (null if not shared)                         |
| `share_url`            | string \| null  | Public share URL (null if not shared)                    |
| `created_at`           | datetime        | When analysis was submitted                              |
| `updated_at`           | datetime        | Last modified timestamp                                  |

**How `jd_role`, `jd_company`, etc. are populated:**

| Input Type | Behavior |
|------------|----------|
| `form`     | User provides these fields directly → stored as-is |
| `text`     | LLM extracts `job_metadata` from the text and auto-populates any empty fields |
| `url`      | URL is scraped → LLM extracts metadata → auto-populates any empty fields |

This means the frontend can **always rely on `jd_role` being populated** on a completed analysis, regardless of input type.

---

### Parsed Content Schema

The `parsed_content` field contains structured personal data extracted from the uploaded resume PDF via LLM. As of v0.34.0, this extraction happens **at upload time** (stored on the `Resume` model) rather than during each analysis. The analysis detail endpoint returns `parsed_content` with a fallback chain: analysis-level data → Resume model data → `null`.

This enables features like:
- **Chat builder pre-fill** — automatically populates the conversational resume builder from any uploaded resume (no analysis needed)
- **Profile auto-population** — can be used to fill user profile fields
- **Resume data display** — show the user their extracted resume data immediately after upload

The schema matches the `resume_content` format used by Generated Resumes:

```typescript
interface ParsedContent {
  contact: {
    name: string;
    email: string;
    phone: string;
    location: string;
    linkedin: string;
    portfolio: string;
  };
  summary: string;
  experience: Array<{
    title: string;
    company: string;
    location: string;
    start_date: string;
    end_date: string;
    bullets: string[];
  }>;
  education: Array<{
    degree: string;
    institution: string;
    location: string;
    year: string;
    gpa: string;
  }>;
  skills: {
    technical: string[];
    tools: string[];
    soft: string[];
  };
  certifications: Array<{
    name: string;
    issuer: string;
    year: string;
  }>;
  projects: Array<{
    name: string;
    description: string;
    technologies: string[];
    url: string;
  }>;
}
```

**Notes:**
- `parsed_content` is available on the `Resume` model once `processing_status` reaches `"done"` (typically within seconds of upload)
- On the analysis detail, `parsed_content` falls back to the Resume model if the analysis itself doesn't have it (backward-compatible)
- Extraction is non-fatal — if the LLM can't parse the resume, `parsed_content` stays `null` and analyses still succeed
- Data is extracted as-is from the resume (no rewriting or enhancement)
- Empty sections are represented as empty arrays `[]` or empty strings `""`

---

### Scrape Result (nested, when `jd_input_type === "url"`)

```json
{
  "id": "uuid-string",
  "source_url": "https://jobs.example.com/posting/12345",
  "summary": "Senior Python Developer at TechCorp. 5+ years experience required. Skills: Python, Django, AWS...",
  "status": "done",
  "error_message": "",
  "created_at": "2026-02-22T14:30:02Z",
  "updated_at": "2026-02-22T14:30:03Z"
}
```

| Field           | Type     | Description                                    |
|-----------------|----------|------------------------------------------------|
| `id`            | UUID     | Scrape result identifier                        |
| `source_url`    | string   | The URL that was scraped                        |
| `summary`       | string   | Concise text summary extracted by Firecrawl     |
| `status`        | string   | `"pending"` / `"done"` / `"failed"`            |
| `error_message` | string   | Error details if scraping failed                |
| `created_at`    | datetime | When scraping started                           |
| `updated_at`    | datetime | When scraping completed                         |

> **Note:** `markdown` and `json_data` fields are **not exposed** in the API to reduce payload size. Only the `summary` field is returned.

---

### LLM Response (nested)

```json
{
  "id": "uuid-string",
  "parsed_response": { "...full LLM analysis output..." },
  "model_used": "anthropic/claude-haiku-4.5",
  "status": "done",
  "error_message": "",
  "duration_seconds": 4.32,
  "created_at": "2026-02-22T14:30:05Z"
}
```

| Field              | Type           | Description                                   |
|--------------------|----------------|-----------------------------------------------|
| `id`               | UUID           | LLM response identifier                       |
| `parsed_response`  | object \| null | Validated JSON result (see section 10)          |
| `model_used`       | string         | Model name (e.g., `"anthropic/claude-haiku-4.5"`) |
| `status`           | string         | `"pending"` / `"done"` / `"failed"`           |
| `error_message`    | string         | Error details if LLM call failed               |
| `duration_seconds` | float \| null  | How long the LLM call took                     |
| `created_at`       | datetime       | When the LLM was called                        |

> **Note:** `prompt_sent` and `raw_response` fields are **not exposed** in the API to reduce payload size (~160KB saved per response).

---

## 10. LLM Analysis Output Schema

The AI returns the following JSON structure. These fields are stored in `llm_response.parsed_response` **and also flattened** onto the top-level analysis object (so you can access them directly without nesting through `llm_response`).

> **Schema version:** This is the **new schema** introduced in migration `0009_new_llm_schema`. It replaces the old `ats_score_breakdown` / `keyword_gaps` / `section_suggestions` / `rewritten_bullets` / `overall_assessment` structure.

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
  "overall_grade": "B",
  "scores": {
    "generic_ats": 72,
    "workday_ats": 61,
    "greenhouse_ats": 68,
    "keyword_match_percent": 58
  },
  "ats_disclaimers": {
    "workday": "Simulated score based on known Workday parsing behavior. Not affiliated with or endorsed by Workday Inc.",
    "greenhouse": "Simulated score based on known Greenhouse parsing behavior. Not affiliated with or endorsed by Greenhouse Software."
  },
  "keyword_analysis": {
    "matched_keywords": ["Python", "SQL", "data analysis", "stakeholder reporting"],
    "missing_keywords": ["Power BI", "ETL pipelines", "Agile", "data modeling"],
    "recommended_to_add": [
      "Add Power BI to skills section under tools",
      "Mention ETL pipelines in work experience bullet under data engineering role",
      "Add Agile to work methodology in summary or experience"
    ]
  },
  "section_feedback": [
    {
      "section_name": "Work Experience",
      "score": 65,
      "feedback": [
        "Most bullets lack quantified impact — add numbers, percentages, or scale",
        "Action verbs are weak — replace 'worked on' and 'helped with' with owned, led, optimized",
        "JD mentions stakeholder reporting but resume does not reference any reporting work"
      ],
      "ats_flags": [
        "Non-standard section title 'Professional Journey' — rename to Work Experience for ATS compatibility"
      ]
    },
    {
      "section_name": "Skills",
      "score": 70,
      "feedback": [
        "Skills are listed but not categorized — group into Technical Skills, Tools, Soft Skills",
        "Several JD keywords like Power BI and ETL are missing entirely"
      ],
      "ats_flags": []
    },
    {
      "section_name": "Summary",
      "score": 80,
      "feedback": [
        "Good keyword presence in summary",
        "Could be more specific to the target role — mention data analytics explicitly"
      ],
      "ats_flags": []
    }
  ],
  "sentence_suggestions": [
    {
      "original": "Worked on building dashboards for the sales team",
      "suggested": "Developed 5 sales performance dashboards using Python and Tableau, reducing reporting time by 40%",
      "reason": "Added specificity, quantified impact, and replaced weak verb with action verb"
    },
    {
      "original": "Helped with data cleaning tasks",
      "suggested": "Automated data cleaning pipelines using Pandas, processing 500K+ records weekly",
      "reason": "Replaced passive language with ownership verb and added scale to demonstrate impact"
    }
  ],
  "formatting_flags": [
    "Multi-column layout detected — Workday and many ATS systems parse left column only",
    "Table used in skills section — replace with plain comma-separated list for ATS safety"
  ],
  "quick_wins": [
    {
      "priority": 1,
      "action": "Add missing keywords Power BI, ETL, and Agile — these appear 4+ times in the JD and are completely absent from your resume"
    },
    {
      "priority": 2,
      "action": "Remove multi-column layout and convert to single column — this is causing your Workday score to drop significantly"
    },
    {
      "priority": 3,
      "action": "Quantify at least 5 bullet points in Work Experience with numbers, percentages, or scale"
    }
  ],
  "summary": "The resume shows relevant experience for the data analytics role but lacks keyword alignment and quantified achievements that ATS systems and recruiters prioritize. Formatting issues including multi-column layout are significantly hurting ATS parseability. With targeted keyword additions and bullet point improvements, this resume has strong potential to rank higher."
}
```

### Field reference

| Field | Type | Description |
|-------|------|-------------|
| **`job_metadata`** | **object** | **Extracted metadata from the job description** |
| `job_metadata.job_title` | string | Job title extracted from JD by LLM |
| `job_metadata.company` | string | Company name (`""` if not found) |
| `job_metadata.skills` | string | Comma-separated key skills from JD |
| `job_metadata.experience_years` | int \| null | Required years of experience |
| `job_metadata.industry` | string | Industry/domain (`""` if unclear) |
| `job_metadata.extra_details` | string | 2-4 sentence summary of other JD details |
| **`overall_grade`** | **string** | **Letter grade `"A"`, `"B"`, `"C"`, `"D"`, or `"F"`** |
| **`scores`** | **object** | **Multi-ATS score breakdown** |
| `scores.generic_ats` | int (0-100) | General ATS compatibility score (also copied to top-level `ats_score`) |
| `scores.workday_ats` | int (0-100) | Simulated Workday ATS score based on Workday parsing behavior |
| `scores.greenhouse_ats` | int (0-100) | Simulated Greenhouse ATS score based on Greenhouse parsing behavior |
| `scores.keyword_match_percent` | int (0-100) | Percentage of JD keywords found in resume |
| **`ats_disclaimers`** | **object** | **Legal disclaimers for simulated ATS scores** |
| `ats_disclaimers.workday` | string | Disclaimer for Workday score (always present) |
| `ats_disclaimers.greenhouse` | string | Disclaimer for Greenhouse score (always present) |
| **`keyword_analysis`** | **object** | **Full keyword gap analysis** |
| `keyword_analysis.matched_keywords` | string[] | JD keywords found in resume |
| `keyword_analysis.missing_keywords` | string[] | Important JD keywords NOT found in resume |
| `keyword_analysis.recommended_to_add` | string[] | Actionable recommendations with context (e.g., `"Add SQL to skills section"`) |
| **`section_feedback`** | **array** | **Per-section analysis (covers every section in the resume)** |
| `section_feedback[].section_name` | string | Section name (e.g., `"Work Experience"`, `"Skills"`, `"Summary"`) |
| `section_feedback[].score` | int (0-100) | Section quality score |
| `section_feedback[].feedback` | string[] | 2-3 specific actionable feedback points |
| `section_feedback[].ats_flags` | string[] | ATS red flags in this section (empty array if none) |
| **`sentence_suggestions`** | **array** | **Weak sentences flagged with improvements (max 10)** |
| `sentence_suggestions[].original` | string | Exact original sentence from resume |
| `sentence_suggestions[].suggested` | string | Improved version of the sentence |
| `sentence_suggestions[].reason` | string | Explanation (e.g., `"Restructured to quantify impact and added action verb"`) |
| **`formatting_flags`** | **string[]** | **ATS formatting issues (e.g., multi-column, tables, images)** |
| **`quick_wins`** | **array** | **Top 1–3 priority actions** |
| `quick_wins[].priority` | int (1-3) | Priority level (1 = highest) |
| `quick_wins[].action` | string | Specific action to take |
| **`summary`** | **string** | **2-3 sentence overall summary of resume quality and fit** |

### How flattened fields map to the analysis model

The backend parses `llm_response.parsed_response` and flattens key fields onto the `ResumeAnalysis` model:

| LLM field | Analysis model field | Notes |
|-----------|---------------------|-------|
| `overall_grade` | `overall_grade` | Stored as `CharField(max_length=2)` |
| `scores` | `scores` | Stored as `JSONField` |
| `scores.generic_ats` | `ats_score` | Copied to legacy int field for dashboard stats |
| `ats_disclaimers` | `ats_disclaimers` | Stored as `JSONField` |
| `keyword_analysis` | `keyword_analysis` | Stored as `JSONField` |
| `section_feedback` | `section_feedback` | Stored as `JSONField` |
| `sentence_suggestions` | `sentence_suggestions` | Stored as `JSONField` |
| `formatting_flags` | `formatting_flags` | Stored as `JSONField` |
| `quick_wins` | `quick_wins` | Stored as `JSONField` |
| `summary` | `summary` | Stored as `TextField` |
| `job_metadata.job_title` | `jd_role` | Auto-populated if not already set |
| `job_metadata.company` | `jd_company` | Auto-populated if not already set |
| `job_metadata.skills` | `jd_skills` | Auto-populated if not already set |
| `job_metadata.experience_years` | `jd_experience_years` | Auto-populated if not already set |
| `job_metadata.industry` | `jd_industry` | Auto-populated if not already set |
| `job_metadata.extra_details` | `jd_extra_details` | Auto-populated if not already set |

### Mapping LLM output → UI components

| LLM Field | Suggested UI | Notes |
|-----------|-------------|-------|
| `overall_grade` | Large letter grade badge (A-F) | Color: A=green, B=blue, C=yellow, D=orange, F=red |
| `scores.generic_ats` | Primary circular gauge (0-100) | Color: red < 50, yellow < 75, green >= 75 |
| `scores.workday_ats` | Secondary gauge/bar | Show with Workday disclaimer |
| `scores.greenhouse_ats` | Secondary gauge/bar | Show with Greenhouse disclaimer |
| `scores.keyword_match_percent` | Percentage bar | Label "Keyword Match" |
| `ats_disclaimers.*` | Small italic text beneath ATS scores | Required for legal compliance |
| `keyword_analysis.matched_keywords` | Tag/chip list (green) | Show as "Matched Keywords" |
| `keyword_analysis.missing_keywords` | Tag/chip list (red/orange) | Show as "Missing Keywords" |
| `keyword_analysis.recommended_to_add` | Bullet list with context | Show as actionable checklist |
| `section_feedback` | Accordion panels per section | Each with score bar + feedback list + ATS flag badges |
| `sentence_suggestions` | Before/after card list | Show original → suggested with reason |
| `formatting_flags` | Warning badges/chips | Yellow/orange alert cards |
| `quick_wins` | Numbered priority list | Priority 1 = red, 2 = orange, 3 = yellow |
| `summary` | Summary paragraph at top | Use as the "AI Summary" hero text |
| `job_metadata.*` | Header/metadata card | Show role, company, industry as breadcrumb |

---

## 11. Pagination

All list endpoints (`GET /api/v1/analyses/`, `GET /api/v1/resumes/`, `GET /api/v1/generated-resumes/`, `GET /api/v1/job-alerts/`, `GET /api/v1/job-alerts/<id>/matches/`) return paginated responses.

| Setting     | Value                    |
|-------------|--------------------------|
| Page size   | 20 items per page        |
| Style       | `PageNumberPagination`   |
| Query param | `?page=N`               |

**Envelope format:**
```json
{
  "count": 47,
  "next": "http://localhost:8000/api/v1/analyses/?page=3",
  "previous": "http://localhost:8000/api/v1/analyses/?page=1",
  "results": [ ... ]
}
```

| Field      | Type           | Description                          |
|------------|----------------|--------------------------------------|
| `count`    | int            | Total number of items across all pages |
| `next`     | string \| null | Full URL of the next page (null if last page) |
| `previous` | string \| null | Full URL of the previous page (null if first page) |
| `results`  | array          | Array of items for the current page   |

**Frontend pagination helper:**
```js
// Generic paginated fetch
async function fetchPage(endpoint, page = 1) {
  const { data } = await api.get(`${endpoint}?page=${page}`);
  return {
    items: data.results,
    totalCount: data.count,
    hasNext: data.next !== null,
    hasPrevious: data.previous !== null,
    totalPages: Math.ceil(data.count / 20),
    currentPage: page,
  };
}

// Usage
const { items, totalPages, hasNext } = await fetchPage('/analyses/', 1);
```

---

## 12. Rate Limiting

Every endpoint is throttled. Six scopes exist, each overridable via environment variable:

| Scope | Default Limit | Env Var Override | Applied To |
|-------|---------------|------------------|------------|
| `anon` (IP-based) | 60 / hour | `ANON_THROTTLE_RATE` | All unauthenticated requests (global default) |
| `user` (per user) | 200 / hour | `USER_THROTTLE_RATE` | All authenticated requests (global default) |
| `auth` (IP-based) | 20 / hour | `AUTH_THROTTLE_RATE` | Register, Login, Forgot-password, Reset-password |
| `analyze` (per user) | 10 / hour | `ANALYZE_THROTTLE_RATE` | `POST /api/v1/analyze/`, `POST /api/v1/analyses/<id>/retry/` |
| `readonly` (per user) | 120 / hour | `READONLY_THROTTLE_RATE` | All authenticated read endpoints |
| `write` (per user) | 60 / hour | `WRITE_THROTTLE_RATE` | Analysis delete, share toggle |
| `payment` (per user) | 30 / hour | `PAYMENT_THROTTLE_RATE` | All Razorpay payment endpoints (subscribe, verify, cancel, topup, history) |

When rate-limited, the API returns:

```http
HTTP 429 Too Many Requests
Retry-After: 120
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1709120000

{
  "detail": "Request was throttled. Expected available in 120 seconds."
}
```

### Rate Limit Headers (v0.24.0)

All API responses now include rate-limit headers (when DRF throttling is active):

| Header | Description | Example |
|--------|-------------|---------|
| `X-RateLimit-Limit` | Max allowed requests in the current window | `200` |
| `X-RateLimit-Remaining` | Requests remaining before throttled | `187` |
| `X-RateLimit-Reset` | Unix timestamp when the window resets | `1709120000` |

The headers reflect the **most restrictive** throttle scope active on the endpoint. For example, `POST /api/v1/analyze/` has both `user` (200/hr) and `analyze` (10/hr) scopes — the headers will show whichever has fewer remaining requests.

**Frontend usage:**
```js
api.interceptors.response.use((response) => {
  const remaining = response.headers['x-ratelimit-remaining'];
  const limit = response.headers['x-ratelimit-limit'];
  if (remaining !== undefined && Number(remaining) < 5) {
    showToast(`${remaining}/${limit} API requests remaining`, 'warning');
  }
  return response;
});
```

**Exempt endpoints (no throttle applied):**
- `GET /api/v1/health/` — health check (must always respond)
- `GET /api/v1/shared/<token>/` — public shared analysis (uses default `anon` scope only)

**Frontend handling:**
```js
api.interceptors.response.use(null, (error) => {
  if (error.response?.status === 429) {
    const retryAfter = error.response.headers['retry-after'] || 60;
    // Show toast: "Too many requests. Try again in X seconds."
    showToast(`Rate limited. Try again in ${retryAfter}s.`, 'warning');
  }
  return Promise.reject(error);
});
```

---

## 13. Polling for Analysis Status

After submitting an analysis (`POST /api/v1/analyze/` → `{ id, status }`), poll the lightweight status endpoint until complete.

### Status flow

```
pending → processing → done
                    ↘ failed
```

### Pipeline step progression

| `pipeline_step` | Description | Suggested UI Text |
|-----------------|-------------|-------------------|
| `pending`       | Queued, waiting for Celery worker | "Queued..." |
| `pdf_extract`   | Extracting text from resume PDF | "Reading your resume..." |
| `jd_scrape`     | Resolving/scraping job description | "Fetching job description..." |
| `llm_call`      | Calling AI model for analysis | "AI is analyzing..." |
| `parse_result`  | Parsing and saving results | "Finalizing results..." |
| `done`          | Analysis complete | "Complete!" |
| `failed`        | An error occurred | "Analysis failed" |

> **v0.34.0 change:** The `resume_parse` step has been removed from the pipeline. Resume parsing now happens at **upload time** (before analysis begins) via a background task. The pipeline is now 4 steps instead of 5. The `resume_parse` value may still appear in older analyses but will not occur in new ones.

### Recommended polling implementation

```js
/**
 * Poll analysis status until done/failed.
 * @param {number} analysisId - The analysis ID from POST /api/v1/analyze/
 * @param {function} onUpdate - Callback called with each status response
 * @returns {Promise<object>} Final status object
 */
async function pollAnalysisStatus(analysisId, onUpdate) {
  const POLL_INTERVAL = 2000; // 2 seconds
  const MAX_POLLS = 150;      // 5 minutes max (150 × 2s)

  for (let i = 0; i < MAX_POLLS; i++) {
    const { data } = await api.get(`/analyses/${analysisId}/status/`);
    onUpdate(data);

    if (data.status === 'done') {
      return data; // Fetch full detail now
    }

    if (data.status === 'failed') {
      throw new Error(data.error_message || 'Analysis failed');
    }

    await new Promise(r => setTimeout(r, POLL_INTERVAL));
  }

  throw new Error('Polling timeout — analysis took too long');
}

// Usage in a React component
const handleSubmit = async (formData) => {
  setSubmitting(true);
  try {
    const { data } = await api.post('/analyze/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });

    await pollAnalysisStatus(data.id, (status) => {
      setPipelineStep(status.pipeline_step);  // Update progress UI
    });

    // Analysis complete — navigate to results
    navigate(`/results/${data.id}`);
  } catch (err) {
    if (err.response?.status === 409) {
      setError('Analysis already in progress. Please wait.');
    } else {
      setError(err.message);
    }
  } finally {
    setSubmitting(false);
  }
};
```

### Progress bar mapping

Map `pipeline_step` to a numeric percentage for a progress bar:

```js
const STEP_PROGRESS = {
  pending: 0,
  pdf_extract: 20,
  jd_scrape: 40,
  llm_call: 60,
  parse_result: 85,
  done: 100,
  failed: 0,
  // Legacy — kept for older analyses that may still report this step:
  resume_parse: 95,
};

// Usage: <ProgressBar value={STEP_PROGRESS[step]} />
```

---

## 14. Error Handling Reference

### HTTP Status Codes

| Code | Meaning              | When                                                    |
|------|----------------------|---------------------------------------------------------|
| 200  | OK                   | Successful GET/POST                                     |
| 201  | Created              | Successful registration                                 |
| 202  | Accepted             | Analysis submitted / retry started (async processing)   |
| 204  | No Content           | Successful DELETE (analysis or resume)                  |
| 302  | Redirect             | PDF export → R2 signed URL                              |
| 400  | Bad Request          | Validation error, invalid data, analysis already done   |
| 401  | Unauthorized         | Missing/expired/invalid JWT token                       |
| 402  | Payment Required     | Insufficient credits, or paid-plan upgrade required     |
| 403  | Forbidden            | Feature not available on user's plan                    |
| 404  | Not Found            | Resource doesn't exist, already soft-deleted, or not owned by user |
| 409  | Conflict             | Duplicate submission / analysis already processing / resume in use |
| 429  | Too Many Requests    | Rate limit exceeded                                     |
| 500  | Server Error         | Unexpected backend error                                |
| 503  | Service Unavailable  | Database unreachable (health check)                     |

### Error response formats

> **v0.39.0**: All error responses now follow a **standardized shape** via a custom DRF exception handler. The frontend only needs to check `response.data.detail` for the human-readable summary.

**Standard error shape (all endpoints, all status codes):**
```json
{
  "detail": "Human-readable error summary.",
  "errors": {
    "field_name": ["Specific field error message."]
  }
}
```

| Key | Type | Always present? | Description |
|-----|------|-----------------|-------------|
| `detail` | `string` | **Yes** | Single human-readable error message. Always a string. |
| `errors` | `object` | Only for 400 validation errors | Field-level errors: `{ field: [messages] }`. Absent for 401/403/404/409/500. |
| *(extra keys)* | varies | Only on specific endpoints | Some 402/403 responses include enrichment fields like `balance`, `cost`, `limit`, `used`. |

**Example — validation error (400):**
```json
{
  "detail": "Username must be at least 3 characters.",
  "errors": {
    "username": ["Username must be at least 3 characters."],
    "email": ["An account with this email already exists."]
  }
}
```

**Example — single error (401/403/404/409):**
```json
{
  "detail": "Analysis not found."
}
```

**Example — enriched error (402):**
```json
{
  "detail": "Insufficient credits.",
  "balance": 0,
  "cost": 1
}
```

**JWT errors (401):**
```json
{
  "detail": "Given token not valid for any token type",
  "code": "token_not_valid",
  "messages": [
    {
      "token_class": "AccessToken",
      "token_type": "access",
      "message": "Token is invalid or expired"
    }
  ]
}
```

### Comprehensive error handler

```js
function handleApiError(error) {
  if (!error.response) {
    // Network error (no response from server)
    return { type: 'network', message: 'Cannot reach the server. Check your connection.' };
  }

  const { status, data } = error.response;

  // `data.detail` is ALWAYS a string on error responses (standardized in v0.39.0)
  const message = data.detail || 'An unexpected error occurred.';

  // Field-level errors (only present on 400 validation errors)
  const fieldErrors = data.errors || null;  // { field: [msgs] } or null

  switch (status) {
    case 400:
      return { type: 'validation', message, fieldErrors };

    case 401:
      return { type: 'auth', message: 'Session expired. Please log in again.' };

    case 402:
      // May include `balance`, `cost` for credit errors
      return { type: 'payment', message, balance: data.balance, cost: data.cost };

    case 403:
      // May include `limit`, `used` for quota errors
      return { type: 'forbidden', message, limit: data.limit, used: data.used };

    case 404:
      return { type: 'not_found', message };

    case 409:
      return { type: 'conflict', message };

    case 429:
      const retryAfter = error.response.headers['retry-after'] || '60';
      return { type: 'rate_limit', message: `Too many requests. Try again in ${retryAfter}s.` };

    case 503:
      return { type: 'service', message: 'Service temporarily unavailable. Try again later.' };

    default:
      return { type: 'unknown', message };
  }
}
```

---

## 15. TypeScript Type Definitions

Use these types for type-safe API integration (copy into your project as `src/types/api.ts`):

```typescript
// ── Auth ─────────────────────────────────────────────────────────────────

interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;     // from Google given_name or empty for email signups
  last_name: string;      // from Google family_name or empty for email signups
  date_joined: string;    // ISO 8601
  country_code: string;   // e.g., "+91" (default)
  mobile_number: string;  // digits only, "" if not set
  auth_provider: 'email' | 'google';  // how the user signed up
  avatar_url: string;     // Google profile picture URL, or "" if none
  plan: Plan | null;      // null if no plan assigned (edge case)
  wallet: Wallet | null;  // null if wallet not yet created
  plan_valid_until: string | null;  // ISO 8601, null for free plan
  pending_plan: Plan | null;        // set when downgrade is scheduled
  agreed_to_terms: boolean;         // true after registration
  agreed_to_data_usage: boolean;    // true after registration
  marketing_opt_in: boolean;        // user's newsletter opt-in choice
}

interface Plan {
  id: number;
  name: string;
  slug: string;
  description: string;
  billing_cycle: 'free' | 'monthly' | 'yearly' | 'lifetime';
  price: string;          // decimal as string, e.g. "399.00"
  original_price: string; // original price for strikethrough, e.g. "599.00" ("0.00" = no discount)
  credits_per_month: number;
  max_credits_balance: number;
  topup_credits_per_pack: number;
  topup_price: string;    // decimal as string
  analyses_per_month: number;
  api_rate_per_hour: number;
  max_resume_size_mb: number;
  max_resumes_stored: number;
  job_notifications: boolean;
  max_job_alerts: number;
  pdf_export: boolean;
  share_analysis: boolean;
  job_tracking: boolean;
  priority_queue: boolean;
  email_support: boolean;
}

interface Wallet {
  balance: number;
  updated_at: string;     // ISO 8601
}

interface NotificationPreferences {
  job_alerts_email: boolean;
  job_alerts_mobile: boolean;
  feature_updates_email: boolean;
  feature_updates_mobile: boolean;
  newsletters_email: boolean;
  newsletters_mobile: boolean;
  policy_changes_email: boolean;
  policy_changes_mobile: boolean;
}

interface AuthTokens {
  access: string;
  refresh: string;
}

interface LoginResponse extends AuthTokens {
  user: User;
}

interface RegisterResponse {
  user: User;
  access: string;
  refresh: string;
}

// ── Pagination ───────────────────────────────────────────────────────────

interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// ── Resume ───────────────────────────────────────────────────────────────

interface Resume {
  id: string;                 // UUID
  original_filename: string;
  file_size_bytes: number;
  uploaded_at: string;        // ISO 8601
  active_analysis_count: number;
  file_url: string | null;    // Full URL to download the resume PDF
  days_since_upload: number;  // Days since upload (staleness)
  last_analyzed_at: string | null; // ISO 8601, null if never analyzed
  is_default: boolean;        // true if this is the user's default resume
}

// ── Job ──────────────────────────────────────────────────────────────────

type JobRelevance = 'pending' | 'relevant' | 'irrelevant';

interface Job {
  id: string;                 // UUID
  job_url: string;
  title: string;
  company: string;
  description: string;
  relevance: JobRelevance;
  source: string;
  resume: string | null;      // UUID of linked resume
  resume_filename: string | null;
  created_at: string;         // ISO 8601
  updated_at: string;         // ISO 8601
}

// ── Analysis ─────────────────────────────────────────────────────────────

type JdInputType = 'text' | 'url' | 'form';
type AnalysisStatus = 'pending' | 'processing' | 'done' | 'failed';
type PipelineStep = 'pending' | 'pdf_extract' | 'jd_scrape' | 'llm_call'
                  | 'parse_result' | 'done' | 'failed'
                  | 'resume_parse'; // legacy — no longer emitted in new analyses

interface AnalysisListItem {
  id: number;
  jd_role: string;
  jd_company: string;
  status: AnalysisStatus;
  pipeline_step: PipelineStep;
  overall_grade: string;        // "A" through "F" (empty if not complete)
  ats_score: number | null;
  ai_provider_used: string;
  report_pdf_url: string | null;
  share_token: string | null;   // UUID
  share_url: string | null;
  created_at: string;         // ISO 8601
}

// ── New LLM Schema Types ─────────────────────────────────────────────────

interface Scores {
  generic_ats: number;          // 0-100, general ATS compatibility
  workday_ats: number;          // 0-100, simulated Workday ATS score
  greenhouse_ats: number;       // 0-100, simulated Greenhouse ATS score
  keyword_match_percent: number; // 0-100, % of JD keywords in resume
}

interface ATSDisclaimers {
  workday: string;              // Legal disclaimer for Workday score
  greenhouse: string;           // Legal disclaimer for Greenhouse score
}

interface KeywordAnalysis {
  matched_keywords: string[];   // JD keywords found in resume
  missing_keywords: string[];   // JD keywords NOT found in resume
  recommended_to_add: string[]; // Actionable recs, e.g. "Add SQL to skills section"
}

interface SectionFeedbackItem {
  section_name: string;         // e.g. "Work Experience", "Skills", "Summary"
  score: number;                // 0-100
  feedback: string[];           // 2-3 specific actionable points
  ats_flags: string[];          // ATS red flags (empty array if none)
}

interface SentenceSuggestion {
  original: string;             // Exact original sentence from resume
  suggested: string;            // Improved version
  reason: string;               // Why the change was made
}

interface QuickWin {
  priority: number;             // 1 (highest), 2, or 3
  action: string;               // Specific action to take
}

interface ParsedContent {
  contact: {
    name: string;
    email: string;
    phone: string;
    location: string;
    linkedin: string;
    portfolio: string;
  };
  summary: string;
  experience: Array<{
    title: string;
    company: string;
    location: string;
    start_date: string;
    end_date: string;
    bullets: string[];
  }>;
  education: Array<{
    degree: string;
    institution: string;
    location: string;
    year: string;
    gpa: string;
  }>;
  skills: {
    technical: string[];
    tools: string[];
    soft: string[];
  };
  certifications: Array<{
    name: string;
    issuer: string;
    year: string;
  }>;
  projects: Array<{
    name: string;
    description: string;
    technologies: string[];
    url: string;
  }>;
}

interface ScrapeResult {
  id: string;                 // UUID
  source_url: string;
  summary: string;
  status: 'pending' | 'done' | 'failed';
  error_message: string;
  created_at: string;
  updated_at: string;
}

interface LLMResponse {
  id: string;                 // UUID
  parsed_response: LLMParsedResponse | null;
  model_used: string;
  status: 'pending' | 'done' | 'failed';
  error_message: string;
  duration_seconds: number | null;
  created_at: string;
}

interface LLMParsedResponse {
  job_metadata: {
    job_title: string;
    company: string;
    skills: string;
    experience_years: number | null;
    industry: string;
    extra_details: string;
  };
  overall_grade: string;                    // "A" through "F"
  scores: Scores;
  ats_disclaimers: ATSDisclaimers;
  keyword_analysis: KeywordAnalysis;
  section_feedback: SectionFeedbackItem[];
  sentence_suggestions: SentenceSuggestion[];  // max 10
  formatting_flags: string[];
  quick_wins: QuickWin[];                   // 1–3 items
  summary: string;                          // 2-3 sentence summary
}

interface AnalysisDetail {
  id: number;
  resume_file: string;
  resume_file_url: string | null;
  jd_input_type: JdInputType;
  jd_text: string;
  jd_url: string;
  jd_role: string;
  jd_company: string;
  jd_skills: string;
  jd_experience_years: number | null;
  jd_industry: string;
  jd_extra_details: string;
  resolved_jd: string;
  scrape_result: ScrapeResult | null;
  llm_response: LLMResponse | null;
  status: AnalysisStatus;
  pipeline_step: PipelineStep;
  error_message: string;
  overall_grade: string;                      // "A" through "F"
  ats_score: number | null;                   // same as scores.generic_ats
  scores: Scores | null;
  ats_disclaimers: ATSDisclaimers | null;
  keyword_analysis: KeywordAnalysis | null;
  section_feedback: SectionFeedbackItem[] | null;
  sentence_suggestions: SentenceSuggestion[] | null;
  formatting_flags: string[] | null;
  quick_wins: QuickWin[] | null;
  summary: string;
  parsed_content: ParsedContent | null;       // structured resume data extracted from PDF
  ai_provider_used: string;
  report_pdf_url: string | null;
  share_token: string | null;                 // UUID
  share_url: string | null;
  created_at: string;
  updated_at: string;
}

interface AnalysisStatusResponse {
  status: AnalysisStatus;
  pipeline_step: PipelineStep;
  overall_grade: string;        // "A"-"F" (empty until done)
  ats_score: number | null;
  error_message: string;
}

interface AnalysisSubmitResponse {
  id: number;
  status: 'processing';
  credits_used: number;
  balance: number;
}

interface RetryResponse {
  id: number;
  status: 'processing';
  pipeline_step: PipelineStep;
  credits_used: number;
  balance: number;
}

interface ShareResponse {
  share_token: string;          // UUID
  share_url: string;            // e.g., "https://yourhost.com/api/v1/shared/<uuid>/"
}

interface SharedAnalysis {
  jd_role: string;
  jd_company: string;
  jd_industry: string;
  status: 'done';
  overall_grade: string;                      // "A" through "F"
  ats_score: number;                          // same as scores.generic_ats
  scores: Scores;
  ats_disclaimers: ATSDisclaimers;
  keyword_analysis: KeywordAnalysis;
  section_feedback: SectionFeedbackItem[];
  sentence_suggestions: SentenceSuggestion[];
  formatting_flags: string[];
  quick_wins: QuickWin[];
  summary: string;
  ai_provider_used: string;
  created_at: string;
}

// ── Dashboard ────────────────────────────────────────────────────────────

interface ScoreTrendItem {
  ats_score: number;
  jd_role: string;
  created_at: string;
}

interface TopRoleItem {
  jd_role: string;
  count: number;
}

interface MonthlyCountItem {
  month: string;              // ISO 8601 (first day of month)
  count: number;
}

interface CreditUsageItem {
  month: string;            // "YYYY-MM"
  type: 'debit' | 'credit';
  subtype: 'analysis' | 'topup' | 'plan' | 'refund' | 'upgrade_bonus' | 'admin';
  count: number;
  total: number;            // absolute sum (always positive)
}

interface KeywordMatchTrendItem {
  jd_role: string;
  keyword_match_percent: number;
  created_at: string;
}

interface PlanUsage {
  plan_name: string;
  analyses_this_month: number;
  analyses_limit: number;
  usage_percent: number;
}

interface ActivityStreak {
  streak_days: number;
  actions_this_month: number;
}

interface DashboardStats {
  // Analyses
  total_analyses: number;
  active_analyses: number;
  deleted_analyses: number;
  average_ats_score: number | null;
  best_ats_score: number | null;
  worst_ats_score: number | null;
  score_trend: ScoreTrendItem[];
  grade_distribution: Record<string, number>;
  top_roles: TopRoleItem[];
  top_industries: { jd_industry: string; count: number }[];
  analyses_per_month: MonthlyCountItem[];
  top_missing_keywords: { keyword: string; count: number }[];
  keyword_match_trend: KeywordMatchTrendItem[];

  // Credits
  credit_usage: CreditUsageItem[];

  // Resumes
  resume_count: number;

  // Generated resumes
  generated_resumes_total: number;
  generated_resumes_done: number;

  // Interview preps
  interview_preps_total: number;
  interview_preps_done: number;

  // Cover letters
  cover_letters_total: number;
  cover_letters_done: number;

  // Chat builder
  chat_sessions_active: number;
  chat_sessions_completed: number;

  // Job alerts
  job_alerts_count: number;
  active_job_alerts: number;
  weekly_job_matches: number;
  total_job_matches: number;
  matches_applied: number;
  matches_relevant: number;
  matches_irrelevant: number;

  // LLM usage
  llm_calls: number;
  llm_tokens_used: number;
  llm_cost_usd: number;

  // Plan & benchmark
  plan_usage: PlanUsage | null;
  industry_benchmark_percentile: number | null;

  // Activity
  activity_streak: ActivityStreak;
}
```

---

## 16. Frontend Integration Recipes

### Recipe 1: Analysis Submit Flow (React)

```jsx
import { useState } from 'react';
import api from '../api/v1/client';

function AnalyzePage() {
  const [step, setStep] = useState(null);     // pipeline_step
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const formData = new FormData(e.target);

    try {
      // 1. Submit analysis
      const { data } = await api.post('/analyze/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      // 2. Poll for status
      const POLL_INTERVAL = 2000;
      while (true) {
        const { data: status } = await api.get(`/analyses/${data.id}/status/`);
        setStep(status.pipeline_step);

        if (status.status === 'done') {
          window.location.href = `/results/${data.id}`;
          return;
        }
        if (status.status === 'failed') {
          throw new Error(status.error_message || 'Analysis failed');
        }

        await new Promise(r => setTimeout(r, POLL_INTERVAL));
      }
    } catch (err) {
      if (err.response?.status === 409) {
        setError('Already submitting. Please wait.');
      } else if (err.response?.status === 429) {
        setError('Rate limit reached. Try again later.');
      } else {
        setError(err.message || 'Something went wrong');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input type="file" name="resume_file" accept=".pdf" required />
      <select name="jd_input_type">
        <option value="text">Paste Text</option>
        <option value="url">Job URL</option>
        <option value="form">Fill Form</option>
      </select>
      <textarea name="jd_text" placeholder="Paste job description..." />
      <button type="submit" disabled={submitting}>
        {submitting ? `Analyzing (${step || 'starting'})...` : 'Analyze Resume'}
      </button>
      {error && <p className="text-red-500">{error}</p>}
    </form>
  );
}
```

### Recipe 2: Dashboard Stats (React + Recharts)

```jsx
import { useEffect, useState } from 'react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts';
import api from '../api/v1/client';

function DashboardPage() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.get('/dashboard/stats/').then(({ data }) => setStats(data));
  }, []);

  if (!stats) return <Spinner />;

  return (
    <div>
      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total Analyses" value={stats.total_analyses} />
        <StatCard label="Active" value={stats.active_analyses} />
        <StatCard label="Avg ATS Score" value={stats.average_ats_score ?? '—'} />
      </div>

      {/* Score Trend Chart */}
      <LineChart width={600} height={300} data={[...stats.score_trend].reverse()}>
        <XAxis dataKey="jd_role" />
        <YAxis domain={[0, 100]} />
        <Tooltip />
        <Line type="monotone" dataKey="ats_score" stroke="#3b82f6" />
      </LineChart>

      {/* Monthly Activity Chart */}
      <BarChart width={600} height={300} data={stats.analyses_per_month}>
        <XAxis
          dataKey="month"
          tickFormatter={(m) => new Date(m).toLocaleDateString('en', { month: 'short' })}
        />
        <YAxis />
        <Tooltip />
        <Bar dataKey="count" fill="#10b981" />
      </BarChart>
    </div>
  );
}
```

### Recipe 3: Paginated Analysis History

```jsx
import { useEffect, useState } from 'react';
import api from '../api/v1/client';

function HistoryPage() {
  const [analyses, setAnalyses] = useState([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  useEffect(() => {
    api.get(`/analyses/?page=${page}`).then(({ data }) => {
      setAnalyses(data.results);
      setTotalPages(Math.ceil(data.count / 20));
    });
  }, [page]);

  const handleDelete = async (id) => {
    if (!confirm('Delete this analysis?')) return;
    await api.delete(`/analyses/${id}/delete/`);
    setAnalyses((prev) => prev.filter((a) => a.id !== id));
  };

  return (
    <div>
      {analyses.map((a) => (
        <div key={a.id} className="flex justify-between p-4 border-b">
          <div>
            <strong>{a.jd_role || 'Untitled'}</strong> — {a.jd_company}
            <span className="ml-2 text-sm text-gray-500">{a.status}</span>
          </div>
          <div>
            {a.overall_grade && (
              <span className="mr-2 font-bold text-lg">{a.overall_grade}</span>
            )}
            {a.ats_score && <span className="font-bold">{a.ats_score}/100</span>}
            <button onClick={() => handleDelete(a.id)} className="ml-4 text-red-500">
              Delete
            </button>
          </div>
        </div>
      ))}

      {/* Pagination */}
      <div className="flex gap-2 mt-4">
        <button disabled={page === 1} onClick={() => setPage(p => p - 1)}>
          ← Prev
        </button>
        <span>Page {page} of {totalPages}</span>
        <button disabled={page === totalPages} onClick={() => setPage(p => p + 1)}>
          Next →
        </button>
      </div>
    </div>
  );
}
```

### Recipe 4: Resume Management

```jsx
import { useEffect, useState } from 'react';
import api from '../api/v1/client';

function ResumesPage() {
  const [resumes, setResumes] = useState([]);

  useEffect(() => {
    api.get('/resumes/').then(({ data }) => setResumes(data.results));
  }, []);

  const handleDelete = async (resume) => {
    if (resume.active_analysis_count > 0) {
      alert(
        `Cannot delete: ${resume.active_analysis_count} active analyses use this resume. ` +
        `Delete those analyses first.`
      );
      return;
    }
    if (!confirm(`Delete "${resume.original_filename}"? This cannot be undone.`)) return;

    try {
      await api.delete(`/resumes/${resume.id}/`);
      setResumes((prev) => prev.filter((r) => r.id !== resume.id));
    } catch (err) {
      if (err.response?.status === 409) {
        alert(err.response.data.detail);
      }
    }
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div>
      <h2>My Resumes</h2>
      {resumes.map((r) => (
        <div key={r.id} className="flex justify-between p-3 border-b">
          <div>
            <strong>{r.original_filename}</strong>
            <span className="ml-2 text-sm text-gray-500">
              {formatSize(r.file_size_bytes)}
            </span>
            <span className="ml-2 text-sm">
              {r.active_analysis_count} analysis(es)
            </span>
          </div>
          <button
            onClick={() => handleDelete(r)}
            disabled={r.active_analysis_count > 0}
            className={
              r.active_analysis_count > 0 ? 'text-gray-400 cursor-not-allowed' : 'text-red-500'
            }
          >
            Delete
          </button>
        </div>
      ))}
    </div>
  );
}
```

---

## 17. Plans & Wallet (Credits System)

Plans define subscription tiers with quotas, rate limits, and feature flags. Each plan grants monthly credits used for resume analysis. Plans are managed via Django Admin and assigned to users via `UserProfile.plan` FK. New users auto-receive the **Free** plan on registration.

### Credit Economics

| Item | Value |
|------|-------|
| Resume analysis | **1 credit** |
| All other actions | **0 credits** (free) |
| Free plan monthly grant | **2 credits** |
| Pro plan monthly grant | **25 credits** |
| Monthly grant behavior | Accumulate with admin-configurable cap |
| Top-up | Pro users only, multi-pack, credits bypass cap |

### Credit Flow

```
POST /api/v1/analyze/ → balance ≥ 1? → NO → 402 "Insufficient credits"
                                   → YES → deduct 1 credit → dispatch task
                                                 ↓
                     Celery task → FAILED → refund 1 credit
                                → SUCCESS → credit stays deducted
```

### Plan Model Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | `int` | Primary key |
| `name` | `CharField(50)` | Display name (e.g., "Free", "Pro") |
| `slug` | `SlugField(50)` | Code identifier (e.g., `"free"`, `"pro"`) |
| `description` | `CharField(500)` | Short description shown to users |
| `billing_cycle` | `CharField(10)` | One of: `free`, `monthly`, `yearly`, `lifetime` |
| `price` | `DecimalField(8,2)` | Current/discounted price in INR (`0.00` for free tier) |
| `original_price` | `DecimalField(8,2)` | Original price before discount — use for strikethrough display (`0.00` if no discount) |
| `credits_per_month` | `int` | Credits granted each billing cycle |
| `max_credits_balance` | `int` | Max credits from monthly grants (`0` = no cap). Top-ups bypass this |
| `topup_credits_per_pack` | `int` | Credits per top-up pack (`0` = top-up not allowed) |
| `topup_price` | `DecimalField(8,2)` | Price per top-up pack in INR |
| `analyses_per_month` | `int` | Max analyses per month (`0` = unlimited) |
| `api_rate_per_hour` | `int` | Max general API requests per hour |
| `max_resume_size_mb` | `int` | Max resume file size in MB |
| `max_resumes_stored` | `int` | Max resumes stored at once (`0` = unlimited) |
| `job_notifications` | `bool` | Can receive job alert notifications |
| `max_job_alerts` | `int` | Maximum active job alerts allowed (`0` = no access). Pro = 5 |
| `pdf_export` | `bool` | Can export analysis as PDF |
| `share_analysis` | `bool` | Can generate public share links |
| `job_tracking` | `bool` | Can use job tracking features |
| `priority_queue` | `bool` | Analyses processed in priority Celery queue |
| `email_support` | `bool` | Has access to email support |
| `is_active` | `bool` | Inactive plans cannot be assigned to new users |
| `display_order` | `int` | Sort order on pricing page (lower = first) |

### Default Plans

Seeded via `python manage.py seed_plans` (idempotent — safe to re-run).

| Name | Slug | Price | Original Price | Billing | Credits/mo | Cap | Top-up | Job Alerts | Rate | Resumes |
|------|------|-------|---------------|---------|-----------|-----|--------|------------|------|---------|
| **Free** | `free` | ₹0 | ₹0 | free | 2 | 10 | ❌ | ❌ (0) | 200/hr | 5 stored, 5MB max |
| **Pro** | `pro` | ₹399/mo | ~~₹599~~ | monthly | 25 | 100 | 5 credits/₹49 | ✅ (max 5) | 500/hr | Unlimited, 10MB max |
| **Pro Yearly** | `pro-yearly` | ₹3,999/yr | ~~₹7,188~~ | yearly | 25 | 100 | 5 credits/₹49 | ✅ (max 5) | 500/hr | Unlimited, 10MB max |

### Plan in User Responses

The `plan`, `wallet`, `plan_valid_until`, and `pending_plan` objects are included in all user-facing responses (`register`, `login`, `GET /me/`, `PUT /me/`):

```json
{
  "id": 1,
  "username": "john",
  "email": "john@example.com",
  "date_joined": "2026-02-26T10:00:00Z",
  "country_code": "+91",
  "mobile_number": "",
  "country": "India",
  "state": "",
  "city": "",
  "plan": {
    "id": 1,
    "name": "Free",
    "slug": "free",
    "description": "Get started with basic resume analysis.",
    "billing_cycle": "free",
    "price": "0.00",
    "original_price": "0.00",
    "credits_per_month": 2,
    "max_credits_balance": 10,
    "topup_credits_per_pack": 0,
    "topup_price": "0.00",
    "analyses_per_month": 0,
    "api_rate_per_hour": 200,
    "max_resume_size_mb": 5,
    "max_resumes_stored": 5,
    "job_notifications": false,
    "max_job_alerts": 0,
    "pdf_export": true,
    "share_analysis": true,
    "job_tracking": true,
    "priority_queue": false,
    "email_support": false
  },
  "wallet": {
    "balance": 2,
    "updated_at": "2026-02-26T10:00:00Z"
  },
  "plan_valid_until": null,
  "pending_plan": null
}
```

> **`plan` is `null`** if no plan is assigned (edge case — all new users auto-get "Free"). Frontend should treat `null` as free tier defaults.
>
> **`wallet` is `null`** if wallet hasn't been created yet (edge case for pre-migration users). Frontend should treat `null` as `{ balance: 0 }`.
>
> **`plan_valid_until`** is set when user is on a paid plan (e.g., Pro). `null` for free plan.
>
> **`pending_plan`** is set when a downgrade is scheduled. Shows the plan the user will switch to after `plan_valid_until` expires.

### Wallet Endpoints

#### `GET /api/v1/auth/wallet/`

Returns wallet balance, plan credits info, and top-up availability.

**Response:**
```json
{
  "balance": 15,
  "updated_at": "2026-02-26T10:00:00Z",
  "plan_name": "Pro",
  "credits_per_month": 25,
  "can_topup": true,
  "topup_credits_per_pack": 5,
  "topup_price": 49.0,
  "plan_valid_until": "2026-03-28T10:00:00Z",
  "pending_downgrade": null
}
```

#### `GET /api/v1/auth/wallet/transactions/`

Paginated transaction history.

**Response:**
```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 5,
      "amount": -1,
      "balance_after": 14,
      "transaction_type": "analysis_debit",
      "description": "Resume analysis",
      "reference_id": "42",
      "created_at": "2026-02-26T12:00:00Z"
    },
    {
      "id": 4,
      "amount": 5,
      "balance_after": 15,
      "transaction_type": "topup",
      "description": "Top-up: 1 pack(s) × 5 credits = 5 credits",
      "reference_id": "",
      "created_at": "2026-02-26T11:00:00Z"
    }
  ]
}
```

**Transaction types:**

| Type | Description |
|------|-------------|
| `plan_credit` | Monthly plan credit grant |
| `topup` | Top-up purchase |
| `analysis_debit` | Credit deducted for analysis |
| `refund` | Credit refunded (analysis failed) |
| `admin_adjustment` | Admin-initiated adjustment |
| `upgrade_bonus` | Credits granted on plan upgrade |

#### `GET /api/v1/auth/wallet/transactions/export/` — Download Transactions CSV

🔒 Requires auth. Downloads all wallet transactions as a CSV file.

**Response (200):**
- `Content-Type: text/csv`
- `Content-Disposition: attachment; filename="wallet_transactions.csv"`

**CSV columns:** `date`, `type`, `amount`, `description`, `balance_after`

**Frontend usage:**
```js
const response = await api.get('/auth/wallet/transactions/export/', {
  responseType: 'blob',
});
const url = URL.createObjectURL(response.data);
const a = document.createElement('a');
a.href = url;
a.download = 'wallet_transactions.csv';
a.click();
URL.revokeObjectURL(url);
```

#### `POST /api/v1/auth/wallet/topup/` *(DEPRECATED)*

> **Deprecated in v0.13.1.** Credit top-ups now require payment via Razorpay.
> Use `POST /api/v1/auth/payments/topup/` instead (see [§ 21](#21-razorpay-payments)).

This endpoint now always returns **402 Payment Required**:

```json
{
  "detail": "Credit top-ups require payment. Use POST /api/v1/auth/payments/topup/ instead.",
  "payment_url": "/api/v1/auth/payments/topup/"
}
```

**Migration guide:** Replace direct top-up calls with the Razorpay checkout flow:
1. `POST /api/v1/auth/payments/topup/` → get `order_id` + `key_id`
2. Open Razorpay checkout with the returned params
3. `POST /api/v1/auth/payments/topup/verify/` → credits are added after payment verification

### Plan Endpoints

#### `GET /api/v1/auth/plans/`

List all active plans. **Public endpoint — no auth required.**

**Response:**
```json
[
  {
    "id": 1,
    "name": "Free",
    "slug": "free",
    "price": "0.00",
    "original_price": "0.00",
    "credits_per_month": 2,
    "topup_credits_per_pack": 0,
    "topup_price": "0.00",
    "job_notifications": false,
    "max_job_alerts": 0,
    "...": "..."
  },
  {
    "id": 2,
    "name": "Pro",
    "slug": "pro",
    "price": "399.00",
    "original_price": "599.00",
    "credits_per_month": 25,
    "topup_credits_per_pack": 5,
    "topup_price": "49.00",
    "job_notifications": true,
    "max_job_alerts": 0,
    "...": "..."
  },
  {
    "id": 3,
    "name": "Pro Yearly",
    "slug": "pro-yearly",
    "price": "3999.00",
    "original_price": "7188.00",
    "credits_per_month": 25,
    "topup_credits_per_pack": 5,
    "topup_price": "49.00",
    "job_notifications": true,
    "max_job_alerts": 0,
    "...": "..."
  }
]
```

#### `POST /api/v1/auth/plans/subscribe/`

Switch to a different plan. **Only allows downgrade to free plan.** Upgrading to a paid plan
requires payment via Razorpay (see [§ 21](#21-razorpay-payments)).

**Request:**
```json
{
  "plan_slug": "free"
}
```

**Paid Plan Upgrade Attempt (402):**
```json
{
  "detail": "Upgrading to a paid plan requires payment. Use POST /api/v1/auth/payments/subscribe/ instead.",
  "payment_url": "/api/v1/auth/payments/subscribe/"
}
```

> **Migration guide:** To upgrade to Pro, use the Razorpay subscription flow:
> 1. `POST /api/v1/auth/payments/subscribe/` with `{"plan_slug": "pro"}`
> 2. Open Razorpay checkout with the returned `subscription_id` + `key_id`
> 3. `POST /api/v1/auth/payments/subscribe/verify/` → plan is upgraded after payment

**Downgrade Response (200):**
```json
{
  "action": "downgrade_scheduled",
  "message": "Downgrade to Free scheduled. You will remain on Pro until March 28, 2026. Your credit balance carries forward.",
  "plan": "pro",
  "pending_plan": "free",
  "effective_date": "2026-03-28T10:00:00Z"
}
```

**Same Plan Response (200):**
```json
{
  "action": "none",
  "message": "Already on the Free plan.",
  "plan": "free"
}
```

### Analysis Submit Response Changes

`POST /api/v1/analyze/` and `POST /api/v1/analyses/<id>/retry/` now include credit info:

**Success (202):**
```json
{
  "id": 42,
  "status": "processing",
  "credits_used": 1,
  "balance": 14
}
```

**Insufficient Credits (402):**
```json
{
  "detail": "Insufficient credits.",
  "balance": 0,
  "cost": 1
}
```

### Frontend Handling

```js
// Handle 402 in your API interceptor
api.interceptors.response.use(null, (error) => {
  if (error.response?.status === 402) {
    const { balance, cost } = error.response.data;
    showUpgradeModal({
      message: `You need ${cost} credit(s) but have ${balance}. Upgrade or top up!`,
    });
  }
  return Promise.reject(error);
});

// Top-up flow
const handleTopUp = async (quantity = 1) => {
  try {
    const { data } = await api.post('/auth/wallet/topup/', { quantity });
    showToast(`${data.credits_added} credits added! Balance: ${data.balance}`);
  } catch (err) {
    showToast(err.response?.data?.detail || 'Top-up failed', 'error');
  }
};

// Subscribe flow
const handleSubscribe = async (planSlug) => {
  const { data } = await api.post('/auth/plans/subscribe/', { plan_slug: planSlug });
  showToast(data.message);
  refreshUser(); // Refetch /auth/me/ to update plan + wallet in context
};
```

### TypeScript Types

```typescript
// ── Wallet & Credits ─────────────────────────────────────────────────────

interface WalletInfo {
  balance: number;
  updated_at: string;        // ISO 8601
}

interface WalletTransaction {
  id: number;
  amount: number;            // positive = credit, negative = debit
  balance_after: number;
  transaction_type: 'plan_credit' | 'topup' | 'analysis_debit' | 'refund' | 'admin_adjustment' | 'upgrade_bonus';
  description: string;
  reference_id: string;
  created_at: string;        // ISO 8601
}

interface WalletDetail {
  balance: number;
  updated_at: string;
  plan_name: string;
  credits_per_month: number;
  can_topup: boolean;
  topup_credits_per_pack: number;
  topup_price: number;
  plan_valid_until: string | null;
  pending_downgrade: string | null;  // plan slug
}

interface TopUpRequest {
  quantity: number;           // number of packs (≥ 1)
}

interface TopUpResponse {
  detail: string;
  credits_added: number;
  balance: number;
  total_price: number;
}

interface PlanSubscribeRequest {
  plan_slug: string;
}

interface PlanSubscribeResponse {
  action: 'upgraded' | 'downgraded' | 'downgrade_scheduled' | 'none';
  message: string;
  plan: string;               // current plan slug
  pending_plan?: string;       // only for downgrade_scheduled
  plan_valid_until?: string;   // only for upgrade
  effective_date?: string;     // only for downgrade_scheduled
}

// Updated User interface (add these fields)
interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  date_joined: string;
  country_code: string;
  mobile_number: string;
  auth_provider: 'email' | 'google';
  avatar_url: string;
  plan: Plan | null;
  wallet: WalletInfo | null;
  plan_valid_until: string | null;
  pending_plan: Plan | null;
  agreed_to_terms: boolean;
  agreed_to_data_usage: boolean;
  marketing_opt_in: boolean;
}

// Updated Plan interface (add these fields)
interface Plan {
  id: number;
  name: string;
  slug: string;
  description: string;
  billing_cycle: string;
  price: string;
  credits_per_month: number;
  max_credits_balance: number;
  topup_credits_per_pack: number;
  topup_price: string;
  analyses_per_month: number;
  api_rate_per_hour: number;
  max_resume_size_mb: number;
  max_resumes_stored: number;
  job_notifications: boolean;
  pdf_export: boolean;
  share_analysis: boolean;
  job_tracking: boolean;
  priority_queue: boolean;
  email_support: boolean;
}

// Updated AnalysisSubmitResponse
interface AnalysisSubmitResponse {
  id: number;
  status: 'processing';
  credits_used: number;
  balance: number;
}

// Insufficient credits error (402)
interface InsufficientCreditsError {
  detail: string;
  balance: number;
  cost: number;
}
```

---

## 18. Email Templates (Admin)

Email templates are stored in the database (`EmailTemplate` model) and managed via Django Admin. They use **Django template syntax** for variable substitution.

### Model Fields

| Field | Type | Description |
|-------|------|-------------|
| `slug` | `SlugField` (unique) | Lookup key used in code (e.g., `"password-reset"`) |
| `name` | `CharField(200)` | Human-readable name (admin display) |
| `category` | `CharField(20)` | One of: `auth`, `notification`, `marketing`, `system` |
| `subject` | `CharField(255)` | Email subject line — supports `{{ variables }}` |
| `html_body` | `TextField` | HTML email body — supports `{{ variables }}` |
| `plain_text_body` | `TextField` | Plain-text fallback (auto-generated from HTML if blank) |
| `description` | `CharField(500)` | Internal note explaining when the template is used |
| `is_active` | `BooleanField` | Inactive templates cannot be sent |
| `created_at` | `DateTimeField` | Auto-set on creation |
| `updated_at` | `DateTimeField` | Auto-set on save |

### Default Templates

Seeded via `python manage.py seed_email_templates` (idempotent — safe to re-run).

| Slug | Category | Trigger | Template Variables |
|------|----------|---------|--------------------|
| `password-reset` | `auth` | `POST /api/v1/auth/forgot-password/` | `{{ username }}`, `{{ reset_link }}`, `{{ expiry_hours }}`, `{{ app_name }}` |
| `welcome` | `auth` | `POST /api/v1/auth/register/` | `{{ username }}`, `{{ frontend_url }}`, `{{ app_name }}` |
| `password-changed` | `auth` | `POST /api/v1/auth/change-password/` | `{{ username }}`, `{{ changed_at }}`, `{{ app_name }}` |

### Auto-injected Variables

These variables are available in **every** template without explicitly passing them:

| Variable | Source | Example |
|----------|--------|---------|
| `{{ app_name }}` | Hardcoded in `email_utils.py` | `"i-Luffy"` |
| `{{ frontend_url }}` | `FRONTEND_URL` setting | `"http://localhost:5173"` |
| `{{ support_email }}` | `DEFAULT_FROM_EMAIL` setting | `"luffy@invrsys.com"` |

### Usage in Code

```python
from accounts.email_utils import send_templated_email

send_templated_email(
    slug='password-reset',
    recipient='user@example.com',
    context={'username': 'john', 'reset_link': 'https://...', 'expiry_hours': '1'},
)
```

> **Adding new templates:** Create in Django Admin → use `send_templated_email(slug='your-slug', ...)` in views. Templates are editable without code deploys.

---

## 19. Resume Generation

Generate an AI-improved resume directly from a completed analysis report. The system uses the analysis findings (missing keywords, section scores, quick wins) as an improvement spec and rewrites the resume via LLM, then renders it to PDF or DOCX.

**Cost:** 1 credit per generation.

> **Auto-created Resume:** When a generated resume reaches `status: "done"`, the backend automatically creates a full **Resume** record from the output. This means every generated resume is immediately usable for new analyses, job alerts, feed, and embedding-based matching — no re-upload needed. The `resume` field in the response contains the UUID of this auto-created Resume. The frontend can use it to navigate to `/api/v1/resumes/<resume>/` or set it as the user's default resume.

### 19.1 Trigger Generation

```
POST /api/v1/analyses/<id>/generate-resume/
Authorization: Bearer <token>
Content-Type: application/json
```

**Request body (all fields optional):**

```json
{
  "template": "ats_classic",
  "format": "pdf"
}
```

| Field | Type | Default | Options | Description |
|-------|------|---------|---------|-------------|
| `template` | `string` | `"ats_classic"` | Any active template slug (see [§28](#28-resume-templates-template-marketplace)) | Resume layout template |
| `format` | `string` | `"pdf"` | `pdf`, `docx` | Output file format |

**Response — 202 Accepted:**

```json
{
  "id": "a1b2c3d4-...",
  "status": "pending",
  "template": "ats_classic",
  "format": "pdf",
  "credits_used": 1,
  "balance": 97
}
```

**Error responses:**

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Analysis not in `done` status | `{"detail": "Analysis must be complete before generating a resume."}` |
| 400 | Invalid template/format | `{"template": ["..."], ...}` |
| 403 | Premium template without paid plan | `{"detail": "Premium template requires a paid plan with premium templates enabled.", "template": "modern", "is_premium": true}` |
| 402 | Insufficient credits | `{"detail": "...", "balance": 0, "cost": 1}` |
| 404 | Analysis not found / not owned | Standard 404 |

### 19.2 Poll Generation Status

```
GET /api/v1/analyses/<id>/generated-resume/
Authorization: Bearer <token>
```

**Response — 200 OK:**

```json
{
  "id": "a1b2c3d4-...",
  "analysis": 42,
  "resume": "e5f6a7b8-...",
  "template": "ats_classic",
  "format": "pdf",
  "status": "done",
  "error_message": "",
  "file_url": "https://r2.example.com/generated_resumes/...",
  "created_at": "2026-02-26T12:00:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `resume` | UUID \| null | ID of the auto-created Resume record. `null` while `status` is `pending`/`processing`. Once `done`, the generated output is automatically saved as a full Resume that can be used for new analyses, job alerts, feed, etc. |

| `status` | Meaning |
|----------|---------|
| `pending` | Queued, not yet picked up by worker |
| `processing` | LLM rewrite + render in progress |
| `done` | File ready for download via `file_url` |
| `failed` | Generation failed — check `error_message`. Credits refunded automatically. |

**Polling recommendation:** Same pattern as analysis polling — start at 2s, back off to 5s.

### 19.3 Download Generated Resume

```
GET /api/v1/analyses/<id>/generated-resume/download/
Authorization: Bearer <token>
```

**Response — 302 Redirect** to signed R2 download URL (1-hour TTL).

| Status | Condition |
|--------|-----------|
| 302 | File ready — `Location` header contains signed URL |
| 404 | No generated resume, or generation not done yet |

### 19.4 List All Generated Resumes

```
GET /api/v1/generated-resumes/
Authorization: Bearer <token>
```

Returns a **paginated** list of all generated resumes for the authenticated user, newest first.

**Response — 200 OK:**

```json
{
  "count": 5,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "a1b2c3d4-...",
      "analysis": 42,
      "resume": "e5f6a7b8-...",
      "template": "ats_classic",
      "format": "pdf",
      "status": "done",
      "error_message": "",
      "file_url": "https://r2.example.com/generated_resumes/...",
      "created_at": "2026-02-26T12:00:00Z"
    }
  ]
}
```

Each item follows the same schema as 19.2. The `resume` field links to the auto-created Resume — use it to navigate to `/api/v1/resumes/<resume>/` for full resume details.

### 19.5 Delete Generated Resume

```
DELETE /api/v1/generated-resumes/<uuid:id>/
Authorization: Bearer <token>
```

Permanently deletes a generated resume (file removed from R2 storage, DB record deleted). Only the owner can delete.

**Response — 204 No Content.**

**Errors:**

| Status | Condition |
|--------|-----------|
| 404 | Not found or belongs to another user |

### 19.6 TypeScript Types

```typescript
// Template slugs are dynamic — fetch from GET /api/v1/templates/
// Default templates: 'ats_classic' | 'modern' | 'executive' | 'creative' | 'minimal'
type ResumeTemplateSlug = string;
type ResumeFormat = 'pdf' | 'docx';
type GeneratedResumeStatus = 'pending' | 'processing' | 'done' | 'failed';

interface GenerateResumeRequest {
  template?: ResumeTemplateSlug;
  format?: ResumeFormat;
}

interface GenerateResumeResponse {
  id: string;
  status: GeneratedResumeStatus;
  template: ResumeTemplateSlug;
  format: ResumeFormat;
  credits_used: number;
  balance: number;
}

interface GeneratedResume {
  id: string;
  analysis: number;
  resume: string | null;       // UUID of auto-created Resume (null while pending/processing)
  template: ResumeTemplateSlug;
  format: ResumeFormat;
  status: GeneratedResumeStatus;
  error_message: string;      // "" when no error, not null
  file_url: string | null;
  created_at: string;
}
```

### 19.7 Frontend Integration Recipe

```typescript
// 1. Trigger generation
const { data } = await api.post(`/analyses/${analysisId}/generate-resume/`, {
  template: 'ats_classic',
  format: 'pdf',
});
const generatedId = data.id;

// 2. Poll until done
const poll = setInterval(async () => {
  const { data: status } = await api.get(
    `/analyses/${analysisId}/generated-resume/`
  );
  if (status.status === 'done') {
    clearInterval(poll);
    // 3. Download
    window.open(status.file_url, '_blank');
  } else if (status.status === 'failed') {
    clearInterval(poll);
    showError(status.error_message);
  }
}, 3000);
```

---

## 20. Smart Job Alerts

Smart Job Alerts automatically discover job opportunities that match a user's resume. The system uses LLM-powered profile extraction and multi-source job searching with relevance scoring.

### Feature Gating

- **Plan requirement**: User must be on a plan with `job_notifications = true` (e.g. Pro)
- **Quota**: Maximum **5 active job alerts** per Pro plan (enforced by `max_job_alerts` on the Plan model). Free plan has **no access** to job alerts.
- **No credit cost**: Alert runs are free — no credits deducted per run.
- **Crawl schedule**: Admin-configurable via `django-celery-beat` (default: daily at 20:30 UTC). Crawl sources are managed in Django Admin via the `CrawlSource` model.
- **Matching**: Uses pgvector cosine-similarity against OpenAI embeddings, with a feedback learning loop that adjusts scores based on past user feedback.

### 20.1 List / Create Job Alerts

```
GET  /api/v1/job-alerts/
POST /api/v1/job-alerts/
```

**GET** returns a **paginated** list of active alerts for the authenticated user (20 per page, newest first).

**POST** creates a new job alert. Triggers async LLM profile extraction from the linked resume.

**Request body:**
```json
{
  "resume": "uuid",
  "frequency": "daily",           // "daily" | "weekly"
  "preferences": {                // optional
    "excluded_companies": ["Evil Corp"],
    "priority_companies": ["Google", "Stripe"],
    "remote_ok": true,
    "location": "San Francisco",
    "salary_min": 120000
  }
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "resume": "uuid",
  "resume_filename": "my_resume_2026.pdf",
  "frequency": "daily",
  "is_active": true,
  "preferences": { ... },
  "search_profile": null,         // populated async after LLM extraction
  "last_run": null,
  "last_run_at": null,
  "next_run_at": "2025-01-01T06:00:00Z",
  "created_at": "..."
}
```

**Errors:**
| Status | Reason |
|--------|--------|
| 403 | Plan doesn't support job alerts |
| 400 | Validation error (invalid resume, etc.) |

### 20.2 Job Alert Detail

```
GET    /api/v1/job-alerts/<uuid:id>/
PUT    /api/v1/job-alerts/<uuid:id>/
DELETE /api/v1/job-alerts/<uuid:id>/
```

**GET** returns the alert detail including nested `search_profile` and `last_run`.

**PUT** updates frequency, is_active, or preferences.

**Request body (PUT):**
```json
{
  "frequency": "weekly",
  "is_active": true,
  "preferences": {
    "excluded_companies": ["Acme"],
    "priority_companies": ["Meta"],
    "remote_ok": false,
    "location": "New York",
    "salary_min": 100000
  }
}
```

**DELETE** soft-deactivates the alert (`is_active = false`). Returns `200` with body:

```json
{ "detail": "Job alert deactivated." }
```

### 20.3 List Matches

```
GET /api/v1/job-alerts/<uuid:id>/matches/
```

Returns paginated job matches for an alert, ordered by relevance score (highest first).

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `feedback` | string | Filter by feedback: `pending`, `relevant`, `irrelevant`, `applied`, `dismissed` |
| `page` | int | Page number (default 1) |

**Response (200):**
```json
{
  "count": 42,
  "next": "http://localhost:8000/api/v1/job-alerts/.../matches/?page=3",
  "previous": "http://localhost:8000/api/v1/job-alerts/.../matches/?page=1",
  "results": [
    {
      "id": "uuid",
      "job": {
        "id": "uuid",
        "source": "firecrawl",
        "title": "Senior Python Developer",
        "company": "TechCorp",
        "company_entity": null,
        "location": "Remote",
        "url": "https://boards.greenhouse.io/techcorp/jobs/12345",
        "source_page_url": "https://boards.greenhouse.io/techcorp",
        "salary_range": "$120k-$160k",
        "description_snippet": "We're looking for...",
        "posted_at": "2025-01-01T00:00:00Z",
        "skills_required": ["Python", "Django", "PostgreSQL"],
        "skills_nice_to_have": ["Go", "Kubernetes"],
        "experience_years_min": 5,
        "experience_years_max": 8,
        "employment_type": "full_time",
        "remote_policy": "remote",
        "seniority_level": "senior",
        "industry": "Technology",
        "education_required": "bachelor",
        "salary_min_usd": 120000,
        "salary_max_usd": 160000,
        "created_at": "2025-01-01T00:00:00Z"
      },
      "relevance_score": 85,
      "match_reason": "Strong match on Python, Django skills...",
      "user_feedback": "pending",
      "created_at": "..."
    }
  ]
}
```

### 20.4 Submit Match Feedback

```
POST /api/v1/job-alerts/<uuid:id>/matches/<uuid:match_id>/feedback/
```

**Request body:**
```json
{
  "user_feedback": "relevant",   // "relevant" | "irrelevant" | "applied" | "dismissed"
  "feedback_reason": "Great match — love the tech stack"  // optional free-text
}
```

> **Feedback learning loop:** Submitting feedback trains the matching algorithm. Future matches for this alert will boost or penalise companies and keywords based on your feedback history.

**Response (200):**
```json
{
  "id": "uuid",
  "user_feedback": "relevant",
  "feedback_reason": "Great match — love the tech stack",
  "relevance_score": 85,
  "match_reason": "...",
  ...
}
```

### 20.5 Manual Run

```
POST /api/v1/job-alerts/<uuid:id>/run/
```

Triggers an immediate job discovery + matching run for the alert. Free — no credit cost.

> **Throttle:** `analyze` scope (10/hour per user) — same as analyze/retry.

**Response (202):**
```json
{
  "detail": "Job discovery started. Check matches in a few minutes.",
  "alert_id": "uuid"
}
```

**Errors:**
| Status | Reason |
|--------|--------|
| 400 | Alert is not active |
| 400 | Job search profile not yet extracted |

### 20.6 Search Profile (read-only)

The `search_profile` object is nested inside the alert detail response. It is extracted automatically by an LLM from the linked resume.

```json
{
  "titles": ["Senior Python Developer", "Backend Engineer"],
  "skills": ["Python", "Django", "PostgreSQL", "Docker"],
  "seniority": "senior",        // "junior"|"mid"|"senior"|"lead"|"executive"
  "industries": ["Technology", "SaaS"],
  "locations": ["Remote", "San Francisco"],
  "experience_years": 8,
  "updated_at": "..."
}
```

### 20.7 TypeScript Types

```typescript
// ── Job Alerts ──────────────────────────────────────────
interface JobAlertPreferences {
  excluded_companies?: string[];
  priority_companies?: string[];
  remote_ok?: boolean;
  location?: string;
  salary_min?: number;
}

interface JobSearchProfile {
  titles: string[];
  skills: string[];
  seniority: 'junior' | 'mid' | 'senior' | 'lead' | 'executive';
  industries: string[];
  locations: string[];
  experience_years: number | null;
  updated_at: string;
}

interface JobAlertRun {
  id: string;
  jobs_discovered: number;
  jobs_matched: number;
  notification_sent: boolean;
  credits_used: number;
  error_message: string | null;
  duration_seconds: number | null;
  created_at: string;
}

interface JobAlert {
  id: string;
  resume: string;
  resume_filename: string;
  frequency: 'daily' | 'weekly';
  is_active: boolean;
  preferences: JobAlertPreferences;
  search_profile: JobSearchProfile | null;
  last_run: JobAlertRun | null;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
}

interface DiscoveredJob {
  id: string;
  source: string;       // e.g. 'firecrawl'
  title: string;
  company: string;
  company_entity: string | null;  // UUID of matched CompanyEntity, if linked
  location: string;
  country: string;       // Normalised country (may be blank for legacy data)
  url: string;           // Direct link to the actual job posting / apply page
  source_page_url: string; // The search/career page URL we crawled
  salary_range: string;
  description_snippet: string;
  posted_at: string | null;

  // Enriched fields (LLM-extracted during crawl)
  skills_required: string[];       // ["Python", "AWS", "Kubernetes"]
  skills_nice_to_have: string[];   // ["Go", "Terraform"]
  experience_years_min: number | null;
  experience_years_max: number | null;
  employment_type: '' | 'full_time' | 'part_time' | 'contract' | 'internship' | 'freelance';
  remote_policy: '' | 'onsite' | 'hybrid' | 'remote';
  seniority_level: '' | 'intern' | 'junior' | 'mid' | 'senior' | 'lead' | 'manager' | 'director' | 'executive';
  industry: string;
  education_required: string;      // 'bachelor', 'master', 'none', etc.
  salary_min_usd: number | null;   // LLM-normalised annual USD
  salary_max_usd: number | null;   // LLM-normalised annual USD
}

type MatchFeedback = 'pending' | 'relevant' | 'irrelevant' | 'applied' | 'dismissed';

interface JobMatch {
  id: string;
  job: DiscoveredJob;
  relevance_score: number;       // 0–100
  match_reason: string;
  user_feedback: MatchFeedback;
  feedback_reason: string;       // user-provided free-text reason (may be empty)
  created_at: string;
}
```

### 20.8 Integration Recipe — Job Alerts Screen

```typescript
// Fetch user's job alerts (now paginated)
const fetchAlerts = async (page = 1): Promise<PaginatedResponse<JobAlert>> => {
  const { data } = await api.get('/api/v1/job-alerts/', { params: { page } });
  return data;  // paginated { count, next, previous, results }
};

// Create a new alert
const createAlert = async (resumeId: string, frequency: 'daily' | 'weekly') => {
  const { data } = await api.post('/api/v1/job-alerts/', {
    resume: resumeId,
    frequency,
  });
  return data;
};

// Fetch matches for an alert
const fetchMatches = async (alertId: string, page = 1, feedback?: string) => {
  const params: Record<string, string> = { page: String(page) };
  if (feedback) params.feedback = feedback;
  const { data } = await api.get(`/api/v1/job-alerts/${alertId}/matches/`, { params });
  return data;  // paginated { count, next, previous, results }
};

// Submit feedback on a match
const submitFeedback = async (alertId: string, matchId: string, feedback: MatchFeedback, reason?: string) => {
  const { data } = await api.post(
    `/api/v1/job-alerts/${alertId}/matches/${matchId}/feedback/`,
    { user_feedback: feedback, feedback_reason: reason }
  );
  return data;
};

// Trigger manual run
const triggerRun = async (alertId: string) => {
  const { data } = await api.post(`/api/v1/job-alerts/${alertId}/run/`);
  return data;
};
```

---

## 21. Razorpay Payments

Full Razorpay payment gateway integration for **plan subscriptions** (recurring) and **credit top-ups** (one-time).

> **Currency:** INR &nbsp;|&nbsp; **Amounts:** All amounts from the API are in **paise** (₹499 = 49900 paise).

### 21.1 Subscribe to a Plan

**Step 1 — Create subscription:**

🔒 Requires auth. **Throttled:** `payment` scope (30/hour per user).

```
POST /api/v1/auth/payments/subscribe/
Auth: Bearer token
Body: { "plan_slug": "pro" }
```

**Response (201):**
```json
{
  "subscription_id": "sub_Abc123",
  "razorpay_plan_id": "plan_pro_monthly",
  "short_url": "https://rzp.io/i/xyz",
  "status": "created",
  "key_id": "rzp_test_xxx",
  "plan_name": "Pro",
  "amount": 49900,
  "currency": "INR"
}
```

**Step 2 — Open Razorpay Checkout (frontend):**

```typescript
const options = {
  key: data.key_id,
  subscription_id: data.subscription_id,
  name: 'i-Luffy',
  description: `${data.plan_name} Plan Subscription`,
  handler: (response: RazorpayResponse) => {
    // Step 3: Verify payment
    verifySubscription(response);
  },
};
const rzp = new (window as any).Razorpay(options);
rzp.open();
```

**Step 3 — Verify subscription payment:**

```
POST /api/v1/auth/payments/subscribe/verify/
Auth: Bearer token
Body: {
  "razorpay_subscription_id": "sub_Abc123",
  "razorpay_payment_id": "pay_Xyz789",
  "razorpay_signature": "hex_signature_from_checkout"
}
```

**Response (200):**
```json
{
  "status": "activated",
  "message": "Subscription activated. Upgraded to Pro. 25 bonus credits added.",
  "plan": "pro",
  "payment_id": "pay_Xyz789",
  "subscription_id": "sub_Abc123"
}
```

### 21.2 Cancel Subscription

🔒 Requires auth. **Throttled:** `payment` scope (30/hour per user).

```
POST /api/v1/auth/payments/subscribe/cancel/
Auth: Bearer token
```

**Response (200):**
```json
{
  "status": "cancelled",
  "message": "Subscription cancelled. You will retain Pro access until the end of the billing cycle.",
  "effective_date": "2026-03-26T12:00:00Z",
  "downgrade_info": { "action": "downgrade_scheduled", "pending_plan": "free" }
}
```

### 21.3 Subscription Status

🔒 Requires auth. **Throttled:** `payment` scope (30/hour per user).

```
GET /api/v1/auth/payments/subscribe/status/
Auth: Bearer token
```

**Response (200):**
```json
{
  "has_subscription": true,
  "subscription_id": "sub_Abc123",
  "plan": "pro",
  "plan_name": "Pro",
  "status": "active",
  "is_active": true,
  "current_start": "2026-02-26T12:00:00Z",
  "current_end": "2026-03-26T12:00:00Z",
  "created_at": "2026-02-26T12:00:00Z"
}
```

### 21.4 Credit Top-Up (One-Time Purchase)

**Step 1 — Create top-up order:**

🔒 Requires auth. **Throttled:** `payment` scope (30/hour per user).

```
POST /api/v1/auth/payments/topup/
Auth: Bearer token
Body: { "quantity": 2 }   // default: 1
```

**Response (201):**
```json
{
  "order_id": "order_Abc123",
  "amount": 9800,
  "currency": "INR",
  "key_id": "rzp_test_xxx",
  "quantity": 2,
  "credits": 10,
  "total_price": 98.0
}
```

**Step 2 — Open Razorpay Checkout:**

```typescript
const options = {
  key: data.key_id,
  amount: data.amount,
  currency: data.currency,
  order_id: data.order_id,
  name: 'i-Luffy',
  description: `${data.credits} Credits Top-Up`,
  handler: (response: RazorpayResponse) => {
    verifyTopUp(response);
  },
};
const rzp = new (window as any).Razorpay(options);
rzp.open();
```

**Step 3 — Verify top-up payment:**

```
POST /api/v1/auth/payments/topup/verify/
Auth: Bearer token
Body: {
  "razorpay_order_id": "order_Abc123",
  "razorpay_payment_id": "pay_Xyz789",
  "razorpay_signature": "hex_signature_from_checkout"
}
```

**Response (200):**
```json
{
  "status": "success",
  "message": "10 credits added to your wallet.",
  "credits_added": 10,
  "balance": 35,
  "payment_id": "pay_Xyz789"
}
```

### 21.5 Payment History

🔒 Requires auth. **Throttled:** `payment` scope (30/hour per user).

```
GET /api/v1/auth/payments/history/?limit=20
Auth: Bearer token
```

**Query params:**

| Param   | Type | Default | Description |
|---------|------|---------|-------------|
| `limit` | int  | 20      | Number of records to return. Clamped to **1–100** server-side. |

**Response (200):**
```json
{
  "count": 3,
  "payments": [
    {
      "id": 1,
      "payment_type": "subscription",
      "razorpay_order_id": "",
      "razorpay_payment_id": "pay_Abc123",
      "amount": 49900,
      "amount_display": "₹499.00",
      "currency": "INR",
      "status": "captured",
      "notes": {},
      "created_at": "2026-02-26T12:00:00Z"
    }
  ]
}
```

### 21.6 Webhook Endpoint (Backend-Only)

```
POST /api/v1/auth/payments/webhook/
Auth: None (signature verification via X-Razorpay-Signature header)
```

> Configure this URL in your Razorpay Dashboard → Webhooks.
> Events handled: `payment.captured`, `payment.failed`, `subscription.activated`,
> `subscription.charged`, `subscription.cancelled`, `subscription.completed`, `subscription.halted`.

### 21.7 TypeScript Types

```typescript
interface RazorpayResponse {
  razorpay_payment_id: string;
  razorpay_order_id?: string;
  razorpay_subscription_id?: string;
  razorpay_signature: string;
}

interface CreateSubscriptionResponse {
  subscription_id: string;
  razorpay_plan_id: string;
  short_url: string;
  status: string;
  key_id: string;
  plan_name: string;
  amount: number;       // paise
  currency: string;
}

interface VerifySubscriptionResponse {
  status: 'activated' | 'already_processed';
  message: string;
  plan?: string;
  payment_id: string;
  subscription_id?: string;
}

interface SubscriptionStatus {
  has_subscription: boolean;
  subscription_id?: string;
  plan?: string;
  plan_name?: string;
  status?: 'created' | 'authenticated' | 'active' | 'pending' | 'halted' | 'cancelled' | 'completed' | 'expired';
  is_active: boolean;
  current_start?: string;
  current_end?: string;
  created_at?: string;
}

interface CreateTopUpResponse {
  order_id: string;
  amount: number;       // paise
  currency: string;
  key_id: string;
  quantity: number;
  credits: number;
  total_price: number;  // INR
}

interface VerifyTopUpResponse {
  status: 'success' | 'already_processed';
  message: string;
  credits_added?: number;
  balance?: number;
  payment_id: string;
}

interface PaymentHistoryEntry {
  id: number;
  payment_type: 'subscription' | 'topup';
  razorpay_order_id: string;
  razorpay_payment_id: string;
  amount: number;         // paise
  amount_display: string; // e.g. "₹499.00"
  currency: string;
  status: 'created' | 'authorized' | 'captured' | 'failed' | 'refunded';
  notes: Record<string, unknown>;
  created_at: string;
}
```

### 21.8 Integration Recipe — Payment Flow

```typescript
import { loadScript } from './utils'; // loads Razorpay checkout.js

// 1. Load Razorpay script once
await loadScript('https://checkout.razorpay.com/v1/checkout.js');

// 2. Subscribe to Pro plan
const subscribeToPro = async () => {
  const { data } = await api.post('/api/v1/auth/payments/subscribe/', {
    plan_slug: 'pro',
  });

  const options = {
    key: data.key_id,
    subscription_id: data.subscription_id,
    name: 'i-Luffy',
    description: `${data.plan_name} Plan`,
    handler: async (response: RazorpayResponse) => {
      const result = await api.post('/api/v1/auth/payments/subscribe/verify/', {
        razorpay_subscription_id: response.razorpay_subscription_id,
        razorpay_payment_id: response.razorpay_payment_id,
        razorpay_signature: response.razorpay_signature,
      });
      // Refresh user profile to reflect Pro plan
      await fetchMe();
      toast.success(result.data.message);
    },
  };

  const rzp = new (window as any).Razorpay(options);
  rzp.open();
};

// 3. Top up credits
const topUpCredits = async (quantity = 1) => {
  const { data } = await api.post('/api/v1/auth/payments/topup/', { quantity });

  const options = {
    key: data.key_id,
    amount: data.amount,
    currency: data.currency,
    order_id: data.order_id,
    name: 'i-Luffy',
    description: `${data.credits} Credits`,
    handler: async (response: RazorpayResponse) => {
      const result = await api.post('/api/v1/auth/payments/topup/verify/', {
        razorpay_order_id: response.razorpay_order_id,
        razorpay_payment_id: response.razorpay_payment_id,
        razorpay_signature: response.razorpay_signature,
      });
      await fetchWallet();
      toast.success(result.data.message);
    },
  };

  const rzp = new (window as any).Razorpay(options);
  rzp.open();
};

// 4. Check subscription status
const getSubscriptionStatus = async (): Promise<SubscriptionStatus> => {
  const { data } = await api.get('/api/v1/auth/payments/subscribe/status/');
  return data;
};

// 5. Cancel subscription
const cancelSubscription = async () => {
  const { data } = await api.post('/api/v1/auth/payments/subscribe/cancel/');
  await fetchMe();
  toast.info(data.message);
};
```

---

## 22. Landing Page Contact Form

Public endpoint for landing-page contact form submissions. No authentication required.

### `POST /api/v1/auth/contact/`

Submit a contact form enquiry. Rate-limited by IP (anonymous throttle).

**Request:**
```json
{
  "name": "Jane Doe",
  "email": "jane@example.com",
  "subject": "Pricing question",
  "message": "I'd like to know more about the Pro plan."
}
```

**Response (201):**
```json
{
  "detail": "Your message has been submitted successfully."
}
```

**Validation errors (400):**
```json
{
  "name": ["This field is required."],
  "email": ["Enter a valid email address."],
  "subject": ["This field is required."],
  "message": ["This field is required."]
}
```

**Field constraints:**
| Field | Type | Max Length | Required |
|-------|------|-----------|----------|
| `name` | string | 100 | ✅ |
| `email` | email | 254 | ✅ |
| `subject` | string | 200 | ✅ |
| `message` | text | unlimited | ✅ |

> Submissions are viewable in Django Admin (read-only). No email notification is sent by default.

---

## 23. Email Verification

New user accounts require email verification before the welcome email is sent. The registration flow now returns `email_verification_required: true`.

### Flow

```
Register → verification email sent → user clicks link → POST /verify-email/ → verified → welcome email sent
```

### `POST /api/v1/auth/verify-email/` — Verify Email

🔓 Public — no auth required. **Throttled:** `auth` scope (20/hour per IP).

**Request:**
```json
{
  "token": "abc123def456..."
}
```

**Response (200):**
```json
{
  "detail": "Email verified successfully.",
  "email": "user@example.com"
}
```

**Errors (400):**

| Condition | Message |
|-----------|---------|
| Missing token | `"Verification token is required."` |
| Invalid token | `"Invalid verification token."` |
| Already used | `"This token has already been used."` |
| Expired (24h) | `"This verification token has expired. Please request a new one."` |

### `POST /api/v1/auth/resend-verification/` — Resend Verification Email

🔒 Authenticated. **Throttled:** `auth` scope (20/hour per IP).

**Request:** None (empty body).

**Response (200):**
```json
{
  "detail": "Verification email sent."
}
```

**Errors (400):**
```json
{
  "detail": "Email is already verified."
}
```

### Frontend integration

```js
// After registration
if (response.data.email_verification_required) {
  navigate('/verify-email-pending');
}

// Verify email (from link in email)
const verifyEmail = async (token) => {
  const { data } = await api.post('/api/v1/auth/verify-email/', { token });
  showToast(data.detail, 'success');
  navigate('/login');
};

// Resend verification (authenticated)
const resendVerification = async () => {
  await api.post('/api/v1/auth/resend-verification/');
  showToast('Verification email sent!', 'info');
};
```

### `is_email_verified` field

The `user` object in login, register, and `GET /api/v1/auth/me/` responses now includes:

```json
{
  "is_email_verified": false
}
```

Use this to conditionally show a verification banner in the UI.

---

## 24. Bulk Analysis (Removed)

> **⚠ Removed in v0.34.0.** The `POST /api/v1/analyze/bulk/` endpoint has been removed. Use the single analysis endpoint (`POST /api/v1/analyze/`) for each resume–JD pair instead.
>
> **Migration:** If your frontend called `/api/v1/analyze/bulk/` with multiple JDs, convert to sequential or parallel calls to `POST /api/v1/analyze/` — one per JD. Each call still deducts 1 credit and returns a single analysis ID.

---

## 25. Interview Prep Generation

Generate interview questions customized to a specific resume + JD analysis. Questions are categorized (behavioral, technical, situational, role-specific, gap-based) with difficulty levels and sample answers.

> **v0.34.0 change:** Interview prep is now **instant** (DB-powered question bank) instead of async LLM generation. The POST endpoint returns `200 OK` with complete results immediately. Polling is no longer needed in most cases. Falls back to async LLM generation (202) only if the question bank is empty.

### `POST /api/v1/analyses/<id>/interview-prep/` — Generate Interview Prep

🔒 Authenticated. **Throttled:** `write` scope (60/hour). **Free — no credit cost.**

**Request:** Empty body (analysis ID from URL).

**Response — Instant (200 OK):** *(typical — when question bank is populated)*
```json
{
  "id": "uuid",
  "analysis": 42,
  "questions": [
    {
      "category": "technical",
      "question": "Can you explain how you would design a REST API for...",
      "why_asked": "Tests backend architecture knowledge mentioned in JD",
      "sample_answer": "I would start by...",
      "difficulty": "medium"
    }
  ],
  "tips": [
    "Research the company's tech stack before the interview",
    "Prepare examples of team collaboration from previous roles"
  ],
  "status": "done",
  "error_message": "",
  "created_at": "2026-03-02T10:00:00Z"
}
```

**Response — Async fallback (202 Accepted):** *(only when question bank is empty — falls back to LLM)*
```json
{
  "id": "uuid",
  "status": "processing"
}
```

**Idempotency:** If a completed interview prep already exists for this analysis, returns it with `200 OK`. If a pending/processing prep exists, also returns `200 OK`.

**Frontend handling:**
```js
const generateInterviewPrep = async (analysisId) => {
  const { data, status } = await api.post(`/api/v1/analyses/${analysisId}/interview-prep/`);
  
  if (status === 200) {
    // Instant result — use data.questions and data.tips directly
    return data;
  }
  
  // 202 fallback — poll for completion (rare)
  return new Promise((resolve, reject) => {
    const poll = setInterval(async () => {
      const { data: result } = await api.get(`/api/v1/analyses/${analysisId}/interview-prep/`);
      if (result.status === 'done') { clearInterval(poll); resolve(result); }
      if (result.status === 'failed') { clearInterval(poll); reject(new Error(result.error_message)); }
    }, 3000);
  });
};
```

**Errors:**

| Status | Condition | Body |
|--------|-----------|------|
| `400` | Analysis not `done` | `{ "detail": "Analysis must be complete before generating interview prep." }` |
| `404` | Analysis not found | `{ "detail": "Analysis not found." }` |

### `GET /api/v1/analyses/<id>/interview-prep/` — Get Interview Prep Status

🔒 Authenticated. Returns the latest interview prep for this analysis.

**Response (200):**
```json
{
  "id": "uuid",
  "analysis": 42,
  "questions": [
    {
      "category": "technical",
      "question": "Can you explain how you would design a REST API for...",
      "why_asked": "Tests backend architecture knowledge mentioned in JD",
      "sample_answer": "I would start by...",
      "difficulty": "medium"
    }
  ],
  "tips": [
    "Research the company's tech stack before the interview",
    "Prepare examples of team collaboration from previous roles"
  ],
  "status": "done",
  "error_message": "",
  "created_at": "2026-03-02T10:00:00Z"
}
```

**Error:** `404` if no interview prep exists for this analysis.

### `GET /api/v1/interview-preps/` — List All Interview Preps

🔒 Authenticated. **Throttled:** `readonly` scope (120/hour). **Paginated.**

Returns all interview preps for the authenticated user (newest first).

---

## 26. Cover Letter Generation

Generate an AI-powered cover letter tailored to a specific resume + JD analysis. Supports three tone options.

### `POST /api/v1/analyses/<id>/cover-letter/` — Generate Cover Letter

🔒 Authenticated. **Throttled:** `write` scope (60/hour). **Free — no credit cost.**

**Request:**
```json
{
  "tone": "professional"
}
```

| Field | Type | Required | Default | Options |
|-------|------|----------|---------|---------|
| `tone` | string | ❌ | `"professional"` | `"professional"`, `"conversational"`, `"enthusiastic"` |

**Response (202 Accepted):**
```json
{
  "id": "uuid",
  "status": "processing",
  "tone": "professional"
}
```

**Idempotency:** If a pending/processing cover letter with the same tone already exists, returns it with `200 OK`.

**Errors:**

| Status | Condition | Body |
|--------|-----------|------|
| `400` | Analysis not `done` | `{ "detail": "Analysis must be complete before generating a cover letter." }` |
| `400` | Invalid tone | Serializer validation errors |
| `404` | Analysis not found | `{ "detail": "Analysis not found." }` |

### `GET /api/v1/analyses/<id>/cover-letter/` — Get Cover Letter Status

🔒 Authenticated. Returns the latest cover letter for this analysis.

**Response (200):**
```json
{
  "id": "uuid",
  "analysis": 42,
  "tone": "professional",
  "content": "Dear Hiring Manager,\n\nI am writing to express my interest...",
  "content_html": "<p>Dear Hiring Manager,</p><p>I am writing to express my interest...</p>",
  "status": "done",
  "error_message": "",
  "file_url": null,
  "created_at": "2026-02-28T10:00:00Z"
}
```

**Error:** `404` if no cover letter exists for this analysis.

### `GET /api/v1/cover-letters/` — List All Cover Letters

🔒 Authenticated. **Throttled:** `readonly` scope (120/hour). **Paginated.**

Returns all cover letters for the authenticated user (newest first).

### Polling

```js
const generateCoverLetter = async (analysisId, tone = 'professional') => {
  const { data } = await api.post(`/api/v1/analyses/${analysisId}/cover-letter/`, { tone });
  const poll = setInterval(async () => {
    const { data: status } = await api.get(`/api/v1/analyses/${analysisId}/cover-letter/`);
    if (status.status === 'done' || status.status === 'failed') {
      clearInterval(poll);
      // Use status.content or status.content_html
    }
  }, 3000);
};
```

---

## 27. Resume Version History

Track how a resume evolves over time. When a user re-uploads a modified resume with the same filename, a version chain is created automatically.

### `GET /api/v1/resumes/<uuid:id>/versions/` — Get Version History

🔒 Authenticated. **Throttled:** `readonly` scope (120/hour).

**Response (200):**
```json
{
  "resume_id": "uuid",
  "filename": "my_resume.pdf",
  "total_versions": 3,
  "versions": [
    {
      "id": "uuid",
      "resume_id": "uuid",
      "resume_filename": "my_resume_v3.pdf",
      "previous_resume_id": "uuid-of-v2",
      "version_number": 3,
      "change_summary": "",
      "best_ats_score": 85,
      "best_grade": "B+",
      "created_at": "2026-02-28T10:00:00Z"
    },
    {
      "id": "uuid",
      "resume_id": "uuid",
      "resume_filename": "my_resume_v2.pdf",
      "previous_resume_id": "uuid-of-v1",
      "version_number": 2,
      "change_summary": "",
      "best_ats_score": 72,
      "best_grade": "C+",
      "created_at": "2026-02-25T10:00:00Z"
    }
  ]
}
```

`best_ats_score` and `best_grade` are computed from completed analyses linked to each version's resume. Use the version timeline to show score improvement across iterations.

**Error:** `404` if the resume doesn't exist or doesn't belong to the user.

---

## 28. Resume Templates (Template Marketplace)

Browse available resume templates. Each template renders resumes with a distinct visual style. Some templates are **premium** — only users on a plan with `premium_templates: true` can use them.

### 28.1 List Templates

```
GET /api/v1/templates/
Authorization: Bearer <token>
```

Returns all **active** templates, ordered by `sort_order` then `name`.

**Response — 200 OK:**

```json
{
  "count": 5,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "a1b2c3d4-...",
      "name": "ATS Classic",
      "slug": "ats_classic",
      "description": "Clean, ATS-friendly layout with clear section headings.",
      "category": "professional",
      "preview_image_url": null,
      "is_premium": false,
      "is_active": true,
      "sort_order": 0,
      "accessible": true
    },
    {
      "id": "e5f6g7h8-...",
      "name": "Modern",
      "slug": "modern",
      "description": "Contemporary design with teal color accents and clean typography.",
      "category": "professional",
      "preview_image_url": null,
      "is_premium": true,
      "is_active": true,
      "sort_order": 1,
      "accessible": false
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `uuid` | Template ID |
| `name` | `string` | Human-readable template name |
| `slug` | `string` | URL-safe identifier — pass this as `template` when generating a resume |
| `description` | `string` | Short description of the template style |
| `category` | `string` | One of: `professional`, `creative`, `academic`, `executive` |
| `preview_image_url` | `string\|null` | URL to a preview image (if uploaded by admin) |
| `is_premium` | `boolean` | Whether this template requires a premium plan |
| `is_active` | `boolean` | Always `true` in list responses (inactive templates are filtered out) |
| `sort_order` | `integer` | Display order (lower = first) |
| `accessible` | `boolean` | Whether the requesting user can use this template — based on plan **and** plan expiry (`plan_valid_until`). Expired Pro users see `false` for premium templates. |

### 28.2 Default Templates

| Slug | Name | Category | Premium | Description |
|------|------|----------|---------|-------------|
| `ats_classic` | ATS Classic | professional | ❌ | Clean ATS-friendly layout |
| `modern` | Modern | professional | ✅ | Teal accents, contemporary design |
| `executive` | Executive | executive | ✅ | Serif fonts, formal charcoal tones |
| `creative` | Creative | creative | ✅ | Purple accents, vibrant design |
| `minimal` | Minimal | professional | ✅ | Whitespace-heavy, distraction-free |

### 28.3 Plan Gating

- **Free templates** (`is_premium: false`): Available to all users.
- **Premium templates** (`is_premium: true`): Only available when the user's plan has `premium_templates: true` **and** the plan has not expired (`plan_valid_until` is in the future).
- When a user attempts to generate a resume with a premium template they don't have access to, the API returns **403**:

```json
{
  "detail": "Premium template requires a paid plan with premium templates enabled.",
  "template": "modern",
  "is_premium": true
}
```

### 28.4 TypeScript Types

```typescript
type TemplateCategory = 'professional' | 'creative' | 'academic' | 'executive';

interface ResumeTemplate {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: TemplateCategory;
  preview_image_url: string | null;
  is_premium: boolean;
  is_active: boolean;
  sort_order: number;
  accessible: boolean;
}
```

### 28.5 Frontend Integration Recipe

```typescript
// 1. Fetch available templates
const { data: templates } = await api.get('/templates/');

// 2. Display templates — use `accessible` to show lock icon on premium
templates.results.forEach(tmpl => {
  console.log(`${tmpl.name} ${tmpl.accessible ? '✓' : '🔒'}`);
});

// 3. Generate resume with chosen template
const { data } = await api.post(`/analyses/${analysisId}/generate-resume/`, {
  template: 'modern',  // slug from step 1
  format: 'pdf',
});

// 4. Handle 403 for premium templates
if (data.status === 403) {
  showUpgradeModal('Upgrade to Pro for premium templates');
}
```

---

## 29. Resume Chat — Text-Based Resume Builder

Build a resume through a **pure text conversation**. The frontend is just a chat box — no forms, no component rendering, no action routing. The user types naturally, the AI extracts structured data, asks follow-up questions, and builds the resume incrementally.

> **Markdown in messages:** All `content` fields in assistant messages use **Markdown formatting** (bold, bullet lists, inline code, blockquotes). Your frontend **must** render message content through a Markdown parser (e.g. `react-markdown`). User messages are plain text.
>
> ```tsx
> import ReactMarkdown from 'react-markdown';
>
> <div className="chat-bubble assistant">
>   <ReactMarkdown>{message.content}</ReactMarkdown>
> </div>
> ```

**3 starting paths** (all converge into the same text chat after the welcome):

| Path | Source | What happens |
|------|--------|--------------|
| **From Scratch** | `scratch` | AI asks everything from zero: name, email, experience, etc. |
| **From Existing Resume** | `previous` | Pre-loads data from selected resume's analysis. AI summarizes what it found, asks for updates. |
| **From Profile** | `profile` | Pulls profile info (name, email, phone, LinkedIn, skills). AI shows it, asks to confirm. |

**Cost:** 2 credits — charged only on finalize (PDF/DOCX generation). Chat messages are free (LLM cost is server-side).

### 29.1 Start a Session

```
POST /api/v1/resume-chat/start/
Authorization: Bearer <token>
Content-Type: application/json
```

**Request body:**

```json
{
  "source": "scratch"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source` | `string` | No | `scratch` | `scratch`, `profile`, or `previous` |
| `base_resume_id` | `uuid\|null` | Only if `source="previous"` | — | UUID of resume to use as base |

**Response — 201 Created:**

```json
{
  "id": "a1b2c3d4-...",
  "mode": "text",
  "source": "scratch",
  "current_step": "contact",
  "status": "active",
  "target_role": "",
  "target_company": "",
  "target_industry": "",
  "experience_level": "",
  "resume_data": { "contact": { "name": "", ... }, "experience": [], ... },
  "step_number": 2,
  "total_steps": 11,
  "generated_resume_url": null,
  "credits_deducted": false,
  "created_at": "2026-03-01T10:00:00Z",
  "updated_at": "2026-03-01T10:00:00Z",
  "messages": [
    {
      "id": "msg-uuid",
      "role": "assistant",
      "content": "Hi! I'll help you build your resume **from scratch** through a quick conversation.\n\nLet's start with the basics — what's your **full name**, **email**, and **phone number**?",
      "ui_spec": null,
      "extracted_data": null,
      "step": "contact",
      "created_at": "2026-03-01T10:00:00Z"
    }
  ]
}
```

**Welcome messages by source:**

- **`scratch`** — _"Hi! I'll help you build your resume **from scratch**... what's your **full name**, **email**, and **phone number**?"_
- **`profile`** — _"Hi John! I pulled this from your profile: **Name:** John Doe, **Email:** john@x.com... Does this look correct?"_
- **`previous`** — _"Hi John! I've loaded data from your resume. - **Contact:** John Doe. - **Experience:** 2 role(s)... Want to update anything?"_

> All welcome messages and AI responses use **Markdown**. Render with `react-markdown` or equivalent.

**Error — 400 (session limit):**

```json
{
  "detail": "Maximum 5 active resume chat sessions. Please complete or delete an existing session."
}
```

### 29.2 Send a Message

The core endpoint. User types anything → backend returns AI response + updated resume data.

```
POST /api/v1/resume-chat/<uuid:id>/message/
Authorization: Bearer <token>
Content-Type: application/json
```

**Request body:**

```json
{
  "text": "I'm a Senior Backend Developer at Acme Corp since Jan 2022. I built their microservices platform and reduced deploy times by 60%."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | `string` | Yes | User's message (max 5,000 chars) |

**Response — 200 OK:**

```json
{
  "user_message": {
    "id": "user-msg-uuid",
    "role": "user",
    "content": "I'm a Senior Backend Developer at Acme Corp since Jan 2022...",
    "ui_spec": null,
    "extracted_data": null,
    "step": "contact",
    "created_at": "2026-03-01T10:01:00Z"
  },
  "assistant_message": {
    "id": "asst-msg-uuid",
    "role": "assistant",
    "content": "Great! I've added your role as **Senior Backend Developer** at **Acme Corp**.\n\n- Built microservices platform, reducing deploy times by **60%**\n\nAny other positions, or shall we move on to education?",
    "ui_spec": null,
    "extracted_data": {
      "experience": [
        {
          "title": "Senior Backend Developer",
          "company": "Acme Corp",
          "start_date": "Jan 2022",
          "end_date": "Present",
          "bullets": ["Built microservices platform, reducing deploy times by 60%"]
        }
      ]
    },
    "step": "experience_input",
    "created_at": "2026-03-01T10:01:02Z"
  },
  "resume_data": {
    "contact": { "name": "", "email": "", ... },
    "experience": [ { "title": "Senior Backend Developer", ... } ],
    "education": [],
    "skills": { "technical": [], "tools": [], "soft": [] },
    "certifications": [],
    "projects": []
  },
  "progress": {
    "sections_with_data": ["experience"],
    "total_sections": 6,
    "ready_to_finalize": false,
    "current_focus": "contact"
  }
}
```

**Markdown in AI responses:**  
The assistant's `content` field uses **Markdown formatting** (bold, bullets, headers, etc.).  
Render it with a Markdown component (e.g. `react-markdown`) instead of plain text so the chat feels polished.

**Key fields in `progress`:**

| Field | Type | Description |
|-------|------|-------------|
| `sections_with_data` | `string[]` | Which sections have data: `contact`, `experience`, `education`, `skills`, `certifications`, `projects` |
| `total_sections` | `int` | Always 6 |
| `ready_to_finalize` | `bool` | `true` when user says "done" / "finish" / "I'm ready" |
| `current_focus` | `string` | Which section the AI is currently asking about |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 400 | Message limit reached (50 user messages per session) |
| 404 | Session not found or not active |
| 500 | LLM call failed (returns fallback "Sorry, try again" message) |

### 29.2.1 Submit Step Action (Guided Mode)

For sessions using **guided mode** (`mode: "guided"`), use this endpoint instead of `/message/`. Submits the user's action/answer for the current step.

```
POST /api/v1/resume-chat/<uuid:id>/submit/
Authorization: Bearer <token>
Content-Type: application/json
```

**Request body:**

```json
{
  "action": "continue",
  "payload": {
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "+91-9876543210"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | string | ✅ | Action type (e.g. `"continue"`, `"skip"`, `"back"`) |
| `payload` | object | ❌ | Step-specific data (fields vary per step). Omit or `{}` for actions like `"skip"`. |

**Response — 200 OK:**

```json
{
  "messages": [
    {
      "id": "msg-uuid",
      "role": "user",
      "content": "John Doe, john@example.com, +91-9876543210",
      "ui_spec": null,
      "extracted_data": { "name": "John Doe", "email": "john@example.com" },
      "step": "contact",
      "created_at": "2026-03-01T10:01:00Z"
    },
    {
      "id": "msg-uuid-2",
      "role": "assistant",
      "content": "Got it! Now let’s add your **work experience**...",
      "ui_spec": null,
      "extracted_data": null,
      "step": "experience",
      "created_at": "2026-03-01T10:01:01Z"
    }
  ],
  "current_step": "experience",
  "step_number": 3,
  "total_steps": 11,
  "status": "active"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `messages` | array | New messages created (user echo + assistant response) |
| `current_step` | string | The step the session is now on |
| `step_number` | int | Current step number (1-based) |
| `total_steps` | int | Total steps in the guided flow |
| `status` | string | `"active"` or `"completed"` |

**Error responses:**

| Status | Condition |
|--------|----------|
| 404 | Session not found or not active |
| 500 | Error processing step |

> **Text mode sessions** should use `POST /resume-chat/<id>/message/` (§29.2) instead. Calling `/submit/` on a text-mode session will still work but is not the intended flow.

### 29.3 List Sessions

```
GET /api/v1/resume-chat/
GET /api/v1/resume-chat/?status=active
Authorization: Bearer <token>
```

Returns up to 20 sessions, newest first. Optional `?status=` filter: `active`, `completed`, `abandoned`.

**Response — 200 OK:**

```json
[
  {
    "id": "a1b2c3d4-...",
    "mode": "text",
    "source": "profile",
    "current_step": "skills",
    "status": "active",
    "target_role": "Software Engineer",
    "step_number": 7,
    "total_steps": 11,
    "name": "John Doe",
    "created_at": "2026-03-01T10:00:00Z",
    "updated_at": "2026-03-01T10:30:00Z"
  }
]
```

### 29.4 Get Session Detail

```
GET /api/v1/resume-chat/<uuid:id>/
Authorization: Bearer <token>
```

Returns full session including all messages. Use this to restore chat on page reload.

**Response — 200 OK:** Same shape as start response (§29.1).

### 29.5 List Resumes for Base Selection

For `source="previous"` — get the user's resumes to pick from.

```
GET /api/v1/resume-chat/resumes/
Authorization: Bearer <token>
```

**Response — 200 OK:**

```json
{
  "resumes": [
    {
      "id": "resume-uuid",
      "type": "uploaded",
      "label": "my_resume.pdf",
      "date": "Feb 15, 2026"
    }
  ]
}
```

### 29.6 Finalize (Generate PDF/DOCX)

When `progress.ready_to_finalize` is `true`, the frontend shows a finalize button.

```
POST /api/v1/resume-chat/<uuid:id>/finalize/
Authorization: Bearer <token>
Content-Type: application/json
```

**Request body:**

```json
{
  "template": "ats_classic",
  "format": "pdf"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `template` | `string` | No | `ats_classic` | Template slug (from `GET /api/v1/templates/`) |
| `format` | `string` | No | `pdf` | `pdf` or `docx` |

**Response — 202 Accepted:**

```json
{
  "id": "gen-resume-uuid",
  "status": "pending",
  "template": "ats_classic",
  "format": "pdf",
  "credits_used": 2,
  "balance": 8
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| 400 | Invalid template or empty resume_data |
| 402 | Insufficient credits (returns `balance` and `cost`) |
| 403 | Premium template without premium plan |
| 404 | Session not found or not active |

> **Auto-created Resume:** Same as analysis-based generation (§19) — once the builder render completes, a full Resume record is auto-created. Poll the generated resume status endpoint (`GET /api/v1/generated-resumes/<id>/`) and use the `resume` field to access the new Resume.

### 29.7 Delete Session

```
DELETE /api/v1/resume-chat/<uuid:id>/
Authorization: Bearer <token>
```

**Response — 204 No Content.**

### 29.8 TypeScript Types

```typescript
type ChatSource = 'scratch' | 'profile' | 'previous';
type ChatStatus = 'active' | 'completed' | 'abandoned';
type MessageRole = 'user' | 'assistant' | 'system';

interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;                               // Markdown-formatted (assistant) or plain text (user)
  ui_spec: null;                                // always null in text mode
  extracted_data: Record<string, any> | null;   // data extracted from this turn
  step: string;
  created_at: string;
}

interface ResumeChat {
  id: string;
  mode: 'text';
  source: ChatSource;
  current_step: string;
  status: ChatStatus;
  target_role: string;
  target_company: string;
  target_industry: string;
  experience_level: string;
  resume_data: ResumeData;
  step_number: number;
  total_steps: number;
  generated_resume_url: string | null;
  credits_deducted: boolean;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
}

interface ResumeChatListItem {
  id: string;
  mode: 'text';
  source: ChatSource;
  current_step: string;
  status: ChatStatus;
  target_role: string;
  step_number: number;
  total_steps: number;
  name: string;
  created_at: string;
  updated_at: string;
}

interface ResumeData {
  contact: { name: string; email: string; phone: string; location: string; linkedin: string; portfolio: string };
  summary: string;
  experience: Array<{ title: string; company: string; location: string; start_date: string; end_date: string; bullets: string[] }>;
  education: Array<{ degree: string; institution: string; location: string; year: string; gpa: string }>;
  skills: { technical: string[]; tools: string[]; soft: string[] };
  certifications: Array<{ name: string; issuer: string; year: string }>;
  projects: Array<{ name: string; description: string; technologies: string[]; url: string }>;
}

interface ChatProgress {
  sections_with_data: string[];
  total_sections: number;
  ready_to_finalize: boolean;
  current_focus: string;
}

interface TextMessageResponse {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  resume_data: ResumeData;
  progress: ChatProgress;
}

interface FinalizeResponse {
  id: string;
  status: 'pending';
  template: string;
  format: 'pdf' | 'docx';
  credits_used: number;
  balance: number;
}

interface BaseResume {
  id: string;
  type: string;
  label: string;
  date: string;
}
```

### 29.9 Frontend Integration (Complete)

```typescript
// ── The entire resume builder frontend ──

// 1. Choose how to start
//    Option A: scratch
const { data: chat } = await api.post<ResumeChat>('/resume-chat/start/', {
  source: 'scratch',
});

//    Option B: from existing resume
const { data: { resumes } } = await api.get<{ resumes: BaseResume[] }>(
  '/resume-chat/resumes/'
);
// Show picker → user selects one
const { data: chat } = await api.post<ResumeChat>('/resume-chat/start/', {
  source: 'previous',
  base_resume_id: resumes[0].id,
});

//    Option C: from profile
const { data: chat } = await api.post<ResumeChat>('/resume-chat/start/', {
  source: 'profile',
});

// 2. Chat loop — state
let messages: ChatMessage[] = chat.messages;
let resumeData = chat.resume_data;
let progress: ChatProgress | null = null;

// 3. Send message
async function sendMessage(text: string) {
  const { data } = await api.post<TextMessageResponse>(
    `/resume-chat/${chat.id}/message/`,
    { text }
  );
  messages.push(data.user_message, data.assistant_message);
  resumeData = data.resume_data;
  progress = data.progress;
}

// 4. Render — THIS IS ALL THE FRONTEND NEEDS:
//
//   <ChatMessages messages={messages} />
//   <ProgressBar sections={progress?.sections_with_data} total={6} />
//   {progress?.ready_to_finalize && <FinalizeButton />}
//   <TextInput onSubmit={sendMessage} placeholder="Type a message..." />

// 5. Finalize
async function finalize(template = 'ats_classic', format = 'pdf') {
  const { data } = await api.post<FinalizeResponse>(
    `/resume-chat/${chat.id}/finalize/`,
    { template, format }
  );
  // data.id = GeneratedResume UUID → poll for download
}

// 6. Restore session on page reload
async function loadSession(chatId: string) {
  const { data } = await api.get<ResumeChat>(`/resume-chat/${chatId}/`);
  messages = data.messages;
  resumeData = data.resume_data;
}
```

### 29.10 Key Notes

- **Frontend = 1 component.** A text input + scrolling message list + optional progress bar. No forms, no `ui_spec` rendering.
- **LLM per message.** Every user message triggers an LLM call (1-3 sec). Show a typing indicator.
- **Multi-section extraction.** If the user dumps everything in one message, the AI extracts all of it at once.
- **50 message limit** per session to prevent abuse.
- **Session reload.** `GET /resume-chat/<id>/` returns full message history.
- **`resume_data` schema** is identical to `GeneratedResume.resume_content` — all template renderers work unchanged.
- **Finalize trigger.** When the user says "done" / "finish" / "I'm ready", `progress.ready_to_finalize` becomes `true`.
- **Editing.** Users can say "change my email to X" or "remove the second job" — the AI handles it naturally.
- **Credits.** 2 credits charged on finalize only. If rendering fails, credits are automatically refunded.
- **Max 5 active sessions** per user.

---

## 30. Feed & Analytics Endpoints

Endpoints powering the in-app home/feed page, market insights, and dashboard extras. All are **GET-only**, require auth, and use the `readonly` throttle scope (120/hour).

---

### 30.0 In-App Notifications

Notification bell/badge endpoints. Stored in the `Notification` model.

#### GET `/api/v1/notifications/` — List Notifications

🔒 Requires auth. Paginated list of the user's in-app notifications, newest first.

**Response (200):**

```json
{
  "count": 42,
  "next": "https://api.example.com/api/v1/notifications/?page=2",
  "previous": null,
  "results": [
    {
      "id": "a1b2c3d4-...",
      "title": "New job matches found!",
      "body": "3 new jobs match your Data Analyst alert.",
      "link": "/job-alerts/a1b2c3d4/matches",
      "is_read": false,
      "notification_type": "job_match",
      "metadata": { "alert_id": "a1b2c3d4-...", "match_count": 3 },
      "created_at": "2026-03-03T06:00:00Z"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | uuid | Notification ID |
| `title` | string | Short title |
| `body` | string | Description text |
| `link` | string | Relative URL for deep-linking (click handler) |
| `is_read` | bool | Whether the user has read this notification |
| `notification_type` | string | `"job_match"`, `"analysis_done"`, `"resume_generated"`, or `"system"` |
| `metadata` | object | Type-specific data (alert ID, match count, etc.) |
| `created_at` | datetime | When the notification was created |

#### GET `/api/v1/notifications/unread-count/` — Unread Badge Count

🔒 Requires auth. Lightweight endpoint for the notification bell badge.

**Response (200):**

```json
{ "unread_count": 5 }
```

**Frontend usage:** Poll this on route changes or every 60 seconds to update the bell badge. Use the count to show a red dot / number.

#### POST `/api/v1/notifications/mark-read/` — Mark Read

🔒 Requires auth. Mark a single notification or all notifications as read.

**Request — mark one:**

```json
{ "notification_id": "a1b2c3d4-..." }
```

**Request — mark all:**

```json
{ "mark_all": true }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `notification_id` | uuid | One of these | Mark a specific notification as read |
| `mark_all` | bool | is required | Mark ALL unread notifications as read |

**Response (200):**

```json
{ "marked_read": 5 }
```

`marked_read` is the number of notifications that were actually updated (were previously unread).

---

### 30.1 GET `/api/v1/feed/jobs/` — Personalised Job Feed

🔒 Requires auth. Returns jobs ranked by **pgvector embedding similarity** against the user's `JobSearchProfile`. Falls back to recency ordering when no profile embedding exists.

**Geography-aware:** Jobs in the user's country (from `profile.country`, default `"India"`) are shown first. Non-local jobs appear after local ones. Pass `?country=` to override with a specific country, or omit to use the profile default.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | `1` | Page number |
| `page_size` | int | `20` | Results per page (max 50) |
| `days` | int | `30` | How far back to look |
| `search` | string | — | Free-text search across title, company, location, skills, industry |
| `country` | string | profile country | Strict country filter (overrides profile default) |
| `remote` | string | — | Filter: `onsite`, `hybrid`, or `remote` |
| `seniority` | string | — | Filter: `intern`, `junior`, `mid`, `senior`, `lead`, etc. |
| `location` | string | — | Substring match on job location |
| `employment_type` | string | — | Filter: `full_time`, `part_time`, `contract`, `internship`, `freelance` |
| `industry` | string | — | Substring match on job industry |
| `skills` | string | — | Comma-separated skill keywords (all must match) |
| `salary_min` | int | — | Minimum `salary_min_usd` filter |
| `relevance_min` | float (0–1) | — | Only return jobs with `relevance >= value`. Applied **server-side before pagination** so `count` and pages are accurate. Jobs without embeddings are excluded when set. Ignored silently if value is out of range or non-numeric. Example: `?relevance_min=0.7` |
| `ordering` | string | `relevance` | Sort field. Allowed values: `relevance` (default — highest match first), `-posted_at` (newest first), `-salary_min_usd` (highest salary first). Invalid values fall back to `relevance`. When no explicit `country` param is provided, the user's geo-priority is always the **primary** sort key (local jobs first) and `ordering` is the secondary sort. Null values in `-posted_at` and `-salary_min_usd` sort last. |

> **India-first behaviour:** When no `country` param is passed, results are sorted with the user's country first, then global jobs. If `country` is explicitly provided, only jobs in that country are returned (strict filter).

**Response (200):**

```json
{
  "count": 142,
  "page": 1,
  "page_size": 20,
  "country": "India",
  "results": [
    {
      "id": "e5f6a7b8-...",
      "title": "Senior Software Engineer",
      "company": "Google",
      "location": "Bangalore, India",
      "country": "India",
      "url": "https://careers.google.com/jobs/123/",
      "salary_range": "₹30L - ₹50L",
      "salary_min_usd": 36000,
      "salary_max_usd": 60000,
      "employment_type": "full_time",
      "remote_policy": "hybrid",
      "seniority_level": "senior",
      "industry": "Technology",
      "skills_required": ["Python", "Go", "Kubernetes"],
      "posted_at": "2026-02-28T00:00:00Z",
      "created_at": "2026-02-28T06:00:00Z",
      "relevance": 0.8742
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `relevance` | float \| null | 0–1 cosine similarity score. `null` when pgvector is unavailable |
| `count` | int | Total matching jobs (for pagination) |
| `country` | string | The country filter applied (from query param or user profile) |
| `results[].country` | string | Normalised country of the job (may be empty for legacy data) |

**Frontend usage:** Main feed page job cards. Show `relevance` as a match percentage badge (e.g., "87% match"). Provide search bar and filter dropdowns for country, remote, seniority, employment type, industry, and skills.

Sort & filter controls should pass params to the API (server-side) rather than filtering/sorting locally, since results are paginated:

```js
// Match % threshold slider
if (jobFilters.match_min) params.set('relevance_min', jobFilters.match_min)

// Sort dropdown
if (jobFilters.sort === 'newest')  params.set('ordering', '-posted_at')
if (jobFilters.sort === 'salary')  params.set('ordering', '-salary_min_usd')
// omit ordering param (or pass 'relevance') for default relevance sort
```

> **Why server-side?** Client-side sorting only reorders the current page (e.g., 20 jobs). A job on page 5 that's the newest overall won't move to page 1. Similarly, filtering by match % on the client hides jobs from the current page but `count` still reflects the unfiltered total — the user sees "3 of 142 jobs" on page 1 with no way to know how many match on other pages. With `relevance_min` and `ordering`, `count` accurately reflects filtered/sorted results across all pages.

---

### 30.2 GET `/api/v1/feed/insights/` — Market Intelligence

🔒 Requires auth. Aggregated job market data from the last 30 days. **Cached 60 minutes per country + role.**

**Geography & role-aware:** Scoped to the user's profile country **and job titles** by default. The backend uses a hybrid two-layer role scoping system:
- **Layer 1 — LLM Role Map:** A `RoleFamily` record (generated asynchronously via LLM when the user's `JobSearchProfile` is created/updated) provides a curated list of related job titles.
- **Layer 2 — Embedding proximity:** Jobs within cosine distance ≤ 0.40 of the user's resume embedding are included, catching synonyms the map may have missed.
- If fewer than 5 jobs match after scoping, the **job listing** auto-broadens to all jobs in the country (so the user still sees results). However, **skill aggregation** (`top_skills`, `trending-skills`, `skill-gap`, `market-insights`) always uses the narrow role-scoped queryset — this prevents unrelated skills (e.g. React/Node.js for a Data Analyst) from appearing in top skills.

Pass `?country=` to filter for a specific country, or `?country=all` for global data. Pass `?role=all` to skip role scoping entirely (show all roles).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `country` | string | profile country | Country to scope insights to, or `"all"` for global |
| `role` | string | auto (from profile) | Pass `"all"` to disable role scoping and see all roles |

**Response (200):**

```json
{
  "country": "India",
  "total_jobs_last_30d": 1523,
  "total_jobs_role_specific": 487,
  "salary_currency": "INR",
  "avg_salary_role": 1850000,
  "avg_salary_by_seniority": {
    "senior": 2800000,
    "mid": 1600000,
    "junior": 900000
  },
  "top_skills": [
    {
      "skill": "python",
      "demand_count": 342,
      "growth_pct": 12.5,
      "you_have": true
    },
    {
      "skill": "kubernetes",
      "demand_count": 198,
      "growth_pct": 28.3,
      "you_have": false
    }
  ],
  "top_companies": [
    { "company": "Google", "job_count": 45 },
    { "company": "Stripe", "job_count": 32 }
  ],
  "top_locations": [
    { "location": "Bangalore, India", "job_count": 89 }
  ],
  "employment_type_breakdown": {
    "full_time": 1200,
    "contract": 180,
    "internship": 95
  },
  "remote_policy_breakdown": {
    "remote": 450,
    "hybrid": 620,
    "onsite": 453
  },
  "seniority_breakdown": {
    "senior": 520,
    "mid": 480,
    "junior": 310
  },
  "role_filter": {
    "source_titles": ["Data Analyst", "Business Analyst"],
    "related_titles": ["Data Scientist", "BI Analyst", "Analytics Engineer"],
    "method": "llm_map+embedding",
    "scoped": true,
    "broadened": false
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_jobs_role_specific` | int | Job count from the narrow role-scoped queryset only |
| `salary_currency` | string | ISO 4217 currency code derived from user's country (e.g. `"INR"`, `"EUR"`) |
| `avg_salary_role` | int \| null | Average salary (role-scoped) converted to `salary_currency`. `null` if no salary data |
| `avg_salary_by_seniority` | object \| null | `{ "senior": int, "mid": int, … }` — average salary per seniority level in `salary_currency` |
| `top_skills[].you_have` | bool | Whether the user's profile includes this skill |
| `top_skills[].growth_pct` | float | % change vs previous 30-day period |
| `role_filter.source_titles` | string[] | User's own job titles (from `JobSearchProfile`) |
| `role_filter.related_titles` | string[] | LLM-generated related titles used for scoping |
| `role_filter.method` | string | Scoping method used: `"llm_map+embedding"`, `"llm_map"`, `"titles_only"`, or `"none"` |
| `role_filter.scoped` | bool | `true` if results are role-filtered, `false` if showing all |
| `role_filter.broadened` | bool | `true` if auto-broadened due to < 5 results |

**Frontend usage:** Insights dashboard cards — donut charts for breakdowns, bar charts for top skills/companies. Optionally show a "Showing results for: Data Analyst + 3 related roles" label using `role_filter`. Add a toggle/button to switch to `?role=all` for unscoped view.

---

### 30.3 GET `/api/v1/feed/trending-skills/` — Skills Gap Analysis

🔒 Requires auth. Compares the user's skills against market demand. **Personalised — not cached.**

**Geography & role-aware:** Scoped to the user's profile country **and job titles** by default. Uses the same hybrid role scoping as insights (Layer 1: LLM Role Map + Layer 2: embedding proximity). Skill aggregation always uses the narrow role-scoped queryset even when the job count is low (see §30.2 broadening note). Pass `?role=all` to skip role scoping.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `country` | string | profile country | Country to scope trending skills, or `"all"` for global |
| `role` | string | auto (from profile) | Pass `"all"` to disable role scoping and see all roles |

**Response (200):**

```json
{
  "matches": [
    { "skill": "python", "demand_count": 342, "you_have": true, "category": "match" },
    { "skill": "react", "demand_count": 215, "you_have": true, "category": "match" }
  ],
  "gaps": [
    { "skill": "kubernetes", "demand_count": 198, "you_have": false, "category": "gap" },
    { "skill": "terraform", "demand_count": 156, "you_have": false, "category": "gap" }
  ],
  "niche": [
    { "skill": "fortran", "demand_count": 0, "you_have": true, "category": "niche" }
  ],
  "match_pct": 40.0,
  "role_filter": {
    "source_titles": ["Data Analyst", "Business Analyst"],
    "related_titles": ["Data Scientist", "BI Analyst", "Analytics Engineer"],
    "method": "llm_map+embedding",
    "scoped": true,
    "broadened": false
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `matches` | array | Skills you have that are in demand |
| `gaps` | array | In-demand skills you're missing |
| `niche` | array | Skills you have that aren't trending |
| `match_pct` | float | % of top 30 trending skills you possess |
| `role_filter` | object | Role scoping metadata (same shape as insights — see §30.2) |

**Frontend usage:** Skill gap radar chart, "Skills you should learn" cards, match percentage ring. Use `role_filter` to display which roles are being compared.

---

### 30.4 GET `/api/v1/feed/hub/` — Alerts & Prep Hub

🔒 Requires auth. Composite endpoint — active job alerts + recent interview preps + recent cover letters in one call.

**Response (200):**

```json
{
  "alerts": [
    {
      "id": "a1b2c3d4-...",
      "resume_filename": "john_doe_resume.pdf",
      "frequency": "daily",
      "is_active": true,
      "matches_this_week": 12,
      "health": "ok",
      "last_run_at": "2026-03-01T06:00:00Z",
      "next_run_at": "2026-03-02T06:00:00Z",
      "created_at": "2026-02-15T10:00:00Z"
    }
  ],
  "interview_preps": [
    {
      "id": "b2c3d4e5-...",
      "analysis_role": "Senior SWE",
      "status": "done",
      "created_at": "2026-02-28T14:00:00Z"
    }
  ],
  "cover_letters": [
    {
      "id": "c3d4e5f6-...",
      "analysis_role": "Backend Engineer",
      "tone": "professional",
      "status": "done",
      "created_at": "2026-02-27T11:00:00Z"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `alerts[].health` | `"ok"` \| `"quiet"` | `ok` = ≥1 match this week; `quiet` = 0 matches (suggest broadening) |
| `alerts[].matches_this_week` | int | Match count in the last 7 days |

**Frontend usage:** Hub section on home page — alert cards with health badges, recent prep/letter links.

---

### 30.5 GET `/api/v1/feed/recommendations/` — Next Actions

🔒 Requires auth. Rules-based (not LLM) action suggestions based on user state.

**Response (200):**

```json
[
  {
    "key": "upload_resume",
    "title": "Upload your resume",
    "description": "Upload a resume to unlock analysis, job matching, and interview prep.",
    "priority": "high",
    "action_url": "/resumes/upload",
    "completed": true
  },
  {
    "key": "run_analysis",
    "title": "Analyse your resume",
    "description": "Get ATS scores, keyword gaps, and improvement suggestions.",
    "priority": "high",
    "action_url": "/analyze",
    "completed": false
  },
  {
    "key": "skill_gaps",
    "title": "Close your skill gaps",
    "description": "Top in-demand skills you're missing: kubernetes, terraform, aws.",
    "priority": "medium",
    "action_url": "/feed/trending-skills",
    "completed": false
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `key` | string | Machine-readable identifier for the action |
| `priority` | `"high"` \| `"medium"` \| `"low"` | Suggested visual weight |
| `action_url` | string | Frontend route to navigate to |
| `completed` | bool | Whether the user has done this already |

**Possible `key` values:** `upload_resume`, `run_analysis`, `create_alert`, `interview_prep`, `cover_letter`, `resume_chat`, `skill_gaps`

**Sorted:** Incomplete items first, then by priority (high → medium → low).

**Frontend usage:** Action cards on home page — show incomplete first with CTA buttons, grey out completed items.

---

### 30.6 GET `/api/v1/feed/onboarding/` — Completion Checklist

🔒 Requires auth. Lightweight checklist of user milestones.

**Response (200):**

```json
{
  "has_resume": true,
  "has_analysis": true,
  "has_alert": false,
  "has_interview_prep": false,
  "has_cover_letter": false,
  "has_chat": false,
  "completed_count": 2,
  "total_steps": 6,
  "completion_pct": 33.3,
  "suggested_next": "create_alert"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `completion_pct` | float | 0–100 |
| `suggested_next` | string \| null | Next uncompleted step key, or `null` if all done |

**Frontend usage:** Progress bar on home page or onboarding modal. Show step-by-step checklist with checkmarks.

---

### 30.7 GET `/api/v1/dashboard/skill-gap/` — Skill Radar Chart Data

🔒 Requires auth. Data for a radar/spider chart comparing user skills vs market demand.

**Geography & role-aware:** Scoped to the user's profile country **and job titles** by default. Uses the same hybrid role scoping as feed insights (see §30.2). Skill aggregation always uses the narrow role-scoped queryset even when broadened. Pass `?role=all` to skip role scoping.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `country` | string | profile country | Country to scope market demand, or `"all"` for global |
| `role` | string | auto (from profile) | Pass `"all"` to disable role scoping and see all roles |

**Response (200):**

```json
[
  { "skill": "python", "user_score": 100, "market_score": 85 },
  { "skill": "kubernetes", "user_score": 0, "market_score": 72 },
  { "skill": "react", "user_score": 100, "market_score": 68 },
  { "skill": "terraform", "user_score": 0, "market_score": 55 }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `user_score` | int | `100` if user has the skill, `0` if not |
| `market_score` | int | 0–100 normalised demand (100 = most demanded skill) |

**Frontend usage:** Radar chart widget on the dashboard. Each axis is a skill.

---

### 30.8 GET `/api/v1/dashboard/market-insights/` — Weekly Trend Card

🔒 Requires auth. Short summary of this week vs last week. **Cached 60 minutes per country + role.**

**Geography & role-aware:** Scoped to the user's profile country **and job titles** by default. Uses the same hybrid role scoping as feed insights (see §30.2). Skill aggregation (`top_skills`, `top_skill_this_week`) always uses the narrow role-scoped queryset even when broadened. Pass `?role=all` to skip role scoping.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `country` | string | profile country | Country to scope weekly trends, or `"all"` for global |
| `role` | string | auto (from profile) | Pass `"all"` to disable role scoping and see all roles |

**Response (200):**

```json
{
  "country": "India",
  "salary_currency": "INR",
  "avg_salary_role": 1850000,
  "jobs_this_week": 245,
  "jobs_last_week": 198,
  "growth_pct": 23.7,
  "trend": "up",
  "top_skill_this_week": "python",
  "top_skills": [
    { "skill": "python", "count": 82 },
    { "skill": "react", "count": 65 },
    { "skill": "kubernetes", "count": 48 }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `salary_currency` | string | ISO 4217 currency code for the user's country |
| `avg_salary_role` | int \| null | Average salary (role-scoped) in `salary_currency` |
| `trend` | `"up"` \| `"down"` \| `"flat"` | Direction of job volume change |
| `growth_pct` | float | % change vs last week |

**Frontend usage:** Dashboard "Weekly Insight" card with trend arrow icon and top skill badge.

---

### 30.9 GET `/api/v1/dashboard/activity/` — Activity Streak

🔒 Requires auth. Uses existing `UserActivity.get_streak()` model method.

**Response (200):**

```json
{
  "streak_days": 7,
  "actions_this_month": 23
}
```

**Frontend usage:** Dashboard streak widget with fire 🔥 icon and day count.

---

### 30.10 GET `/api/v1/dashboard/activity/history/` — Daily Activity History

🔒 Requires auth. Returns per-day activity breakdown for a GitHub-style heatmap or timeline.

**Query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | int | 90 | How many days of history (max 365) |

**Response (200):**

```json
{
  "streak_days": 7,
  "actions_this_month": 23,
  "total_days_active": 12,
  "days": [
    {
      "date": "2026-03-03",
      "action_count": 4,
      "actions": {
        "login": 1,
        "analysis": 2,
        "resume_gen": 1
      }
    },
    {
      "date": "2026-03-02",
      "action_count": 1,
      "actions": {
        "login": 1
      }
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `streak_days` | int | Consecutive days of activity ending today/yesterday |
| `actions_this_month` | int | Total actions in the current calendar month |
| `total_days_active` | int | Number of days with ≥1 action in the requested range |
| `days` | array | Per-day entries, newest first |
| `days[].date` | string | Calendar date (YYYY-MM-DD) |
| `days[].action_count` | int | Total actions on this date |
| `days[].actions` | object | Breakdown by type: `login`, `analysis`, `resume_gen`, `interview_prep`, `cover_letter`, `job_alert_run`, `builder_finalize` |

**Frontend usage:** Activity heatmap (like GitHub contribution graph), activity timeline, or detailed history view.

---

### TypeScript Types (Feed)

```typescript
interface FeedJob {
  id: string;
  title: string;
  company: string;
  location: string;
  country: string;
  url: string;
  salary_range: string;
  salary_min_usd: number | null;
  salary_max_usd: number | null;
  employment_type: string;
  remote_policy: string;
  seniority_level: string;
  industry: string;
  skills_required: string[];
  posted_at: string | null;
  created_at: string;
  relevance: number | null;  // 0-1 cosine similarity, null if no embedding
}

interface FeedJobsResponse {
  count: number;
  page: number;
  page_size: number;
  country: string;      // country filter applied (from param or user profile)
  results: FeedJob[];
}

interface TrendingSkill {
  skill: string;
  demand_count: number;
  growth_pct: number;
  you_have: boolean;
}

interface SkillGapItem {
  skill: string;
  demand_count: number;
  you_have: boolean;
  category: 'match' | 'gap' | 'niche';
}

interface TrendingVsUser {
  matches: SkillGapItem[];
  gaps: SkillGapItem[];
  niche: SkillGapItem[];
  match_pct: number;
}

interface RoleFilter {
  source_titles: string[];
  related_titles: string[];
  method: 'llm_map+embedding' | 'llm_map' | 'titles_only' | 'none';
  scoped: boolean;
  broadened: boolean;
}

interface InsightsResponse {
  country: string;              // country scope applied
  total_jobs_last_30d: number;
  total_jobs_role_specific: number;
  salary_currency: string;      // ISO 4217 (e.g. "INR", "EUR")
  avg_salary_role: number | null;
  avg_salary_by_seniority: Record<string, number> | null;
  top_skills: TrendingSkill[];
  top_companies: { company: string; job_count: number }[];
  top_locations: { location: string; job_count: number }[];
  employment_type_breakdown: Record<string, number>;
  remote_policy_breakdown: Record<string, number>;
  seniority_breakdown: Record<string, number>;
  role_filter: RoleFilter;
}

interface HubAlertSummary {
  id: string;
  resume_filename: string;
  frequency: 'daily' | 'weekly';
  is_active: boolean;
  matches_this_week: number;
  health: 'ok' | 'quiet';
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
}

interface HubResponse {
  alerts: HubAlertSummary[];
  interview_preps: { id: string; analysis_role: string; status: string; created_at: string }[];
  cover_letters: { id: string; analysis_role: string; tone: string; status: string; created_at: string }[];
}

interface Recommendation {
  key: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  action_url: string;
  completed: boolean;
}

interface OnboardingChecklist {
  has_resume: boolean;
  has_analysis: boolean;
  has_alert: boolean;
  has_interview_prep: boolean;
  has_cover_letter: boolean;
  has_chat: boolean;
  completed_count: number;
  total_steps: number;
  completion_pct: number;
  suggested_next: string | null;
}

interface SkillGapRadarItem {
  skill: string;
  user_score: number;   // 0 or 100
  market_score: number; // 0-100
}

interface MarketInsights {
  country: string;              // country scope applied
  salary_currency: string;      // ISO 4217 (e.g. "INR", "EUR")
  avg_salary_role: number | null;
  jobs_this_week: number;
  jobs_last_week: number;
  growth_pct: number;
  trend: 'up' | 'down' | 'flat';
  top_skill_this_week: string | null;
  top_skills: { skill: string; count: number }[];
}

interface ActivityStreak {
  streak_days: number;
  actions_this_month: number;
}

interface ActivityHistoryDay {
  date: string;              // "YYYY-MM-DD"
  action_count: number;
  actions: Record<string, number>;  // e.g. { login: 1, analysis: 2 }
}

interface ActivityHistory extends ActivityStreak {
  total_days_active: number;
  days: ActivityHistoryDay[];
}
```

---

## 31. Database Table Reference — Job & Company Models

Complete column-level reference for all Job Alert and Company Intelligence tables. All primary keys are UUIDv4 unless noted. Timestamps use ISO 8601 (UTC). Admin-only models (CrawlSource, SentAlert) are included for completeness but have no user-facing API.

---

### 30.1 `Company`

Top-level brand / parent company (e.g., Google, Stripe). Managed via Django Admin.

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `name` | varchar(255) | No | — | **Unique** | Brand / common name (e.g. "Google", "Stripe") |
| `slug` | slug(255) | No | — | **Unique** | URL-safe identifier, auto-generated from `name` |
| `description` | text | No | `''` | — | Brief company description for display |
| `logo` | url(2048) | No | `''` | — | URL to company logo image |
| `industry` | varchar(100) | No | `''` | — | Primary industry sector |
| `founded_year` | smallint | Yes | `null` | — | Year the company was founded |
| `company_size` | varchar(12) | No | `''` | Choices¹ | Employee range category |
| `headquarters_country` | varchar(100) | No | `''` | — | HQ country name |
| `headquarters_city` | varchar(100) | No | `''` | — | HQ city name |
| `linkedin_url` | url(2048) | No | `''` | — | LinkedIn company page URL |
| `glassdoor_url` | url(2048) | No | `''` | — | Glassdoor company page URL |
| `tech_stack` | JSON | No | `[]` | — | Known technologies `["Python", "K8s", ...]` |
| `is_active` | bool | No | `true` | Indexed | Inactive companies hidden from suggestions |
| `created_at` | datetime | No | auto | — | Row creation timestamp |
| `updated_at` | datetime | No | auto | — | Last update timestamp |

¹ **`company_size` choices:** `startup` (1-50), `small` (51-200), `mid` (201-1000), `large` (1001-10000), `enterprise` (10000+)

**Ordering:** `name` ASC

**Relationships:**
- `entities` → `CompanyEntity[]` (one-to-many)

---

### 30.2 `CompanyEntity`

A legal / operating entity of a Company in a specific country. One Company can have multiple entities (e.g., "Stripe Inc" US + "Stripe India Pvt Ltd" IN).

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `company` | UUID (FK) | No | — | **FK → Company**, CASCADE | Parent brand |
| `legal_name` | varchar(500) | No | `''` | — | Registered legal name (e.g. "Google India Pvt Ltd") |
| `display_name` | varchar(255) | No | — | Unique² | Short display name (e.g. "Google India") |
| `operating_country` | varchar(100) | No | — | Unique² | Country this entity operates in |
| `operating_city` | varchar(100) | No | `''` | — | City this entity operates in |
| `is_headquarters` | bool | No | `false` | — | Whether this is the global HQ entity |
| `is_indian_entity` | bool | No | `false` | Indexed | Quick filter for Indian entities |
| `website` | url(2048) | No | `''` | — | Corporate website for this entity |
| `is_active` | bool | No | `true` | — | Inactive entities excluded from matching |
| `created_at` | datetime | No | auto | — | Row creation timestamp |
| `updated_at` | datetime | No | auto | — | Last update timestamp |

² **Unique constraint:** `(company, operating_country, display_name)` — one display name per company per country.

**Indexes:** `(company, operating_country)`, `(is_indian_entity)`

**Ordering:** `company` ASC, `operating_country` ASC

**Relationships:**
- `company` → `Company` (many-to-one)
- `career_pages` → `CompanyCareerPage[]` (one-to-many)
- `discovered_jobs` → `DiscoveredJob[]` (one-to-many)

---

### 30.3 `CompanyCareerPage`

A career page URL belonging to a CompanyEntity. One entity can have multiple career pages (engineering vs general, region-specific sub-pages).

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `entity` | UUID (FK) | No | — | **FK → CompanyEntity**, CASCADE | Owning entity |
| `url` | url(2048) | No | — | — | Career page URL |
| `label` | varchar(100) | No | `''` | — | Label (e.g. "Engineering", "Campus") |
| `country` | varchar(100) | No | `''` | — | Country this page targets (may differ from entity) |
| `is_active` | bool | No | `true` | Indexed | Inactive pages are not crawled |
| `last_crawled_at` | datetime | Yes | `null` | — | When this page was last successfully crawled |
| `crawl_frequency` | varchar(10) | No | `'weekly'` | Choices³ | How often to crawl |
| `created_at` | datetime | No | auto | — | Row creation timestamp |
| `updated_at` | datetime | No | auto | — | Last update timestamp |

³ **`crawl_frequency` choices:** `daily`, `weekly`

**Ordering:** `entity` ASC, `label` ASC

**Relationships:**
- `entity` → `CompanyEntity` (many-to-one)

---

### 30.4 `CrawlSource` _(admin-only)_

Admin-managed crawl source. Each entry defines a job board or company career page for the daily crawl. No user-facing API.

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `name` | varchar(100) | No | — | **Unique** | Display name (e.g. "LinkedIn", "Google Careers") |
| `source_type` | varchar(20) | No | `'job_board'` | Choices⁴ | Job board (templated URL) or company career page (plain URL) |
| `url_template` | varchar(2048) | No | — | — | URL with `{query}` and `{location}` placeholders (job board) or plain URL (company) |
| `is_active` | bool | No | `true` | Indexed | Inactive sources skipped during crawl |
| `priority` | smallint | No | `10` | — | Lower = crawled first |
| `last_crawled_at` | datetime | Yes | `null` | — | Timestamp of last successful crawl |
| `created_at` | datetime | No | auto | — | Row creation timestamp |
| `updated_at` | datetime | No | auto | — | Last update timestamp |

⁴ **`source_type` choices:** `job_board`, `company`

**Ordering:** `priority` ASC, `name` ASC

---

### 30.5 `JobSearchProfile`

LLM-extracted job search criteria from a resume. One profile per resume — auto-generated when a job alert is created.

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | int | No | auto | **PK** | Auto-increment primary key |
| `resume` | UUID (FK) | No | — | **FK → Resume**, CASCADE, **Unique** | Resume this profile was extracted from |
| `titles` | JSON | No | `[]` | — | Target job titles `["Senior Python Dev", "Backend Engineer"]` |
| `skills` | JSON | No | `[]` | — | Key skills `["Python", "Django", "PostgreSQL"]` |
| `seniority` | varchar(20) | No | `''` | Choices⁵ | Inferred seniority level |
| `industries` | JSON | No | `[]` | — | Target industries |
| `locations` | JSON | No | `[]` | — | Preferred work locations |
| `experience_years` | smallint | Yes | `null` | — | Years of experience inferred from resume |
| `raw_extraction` | JSON | Yes | `null` | — | Full LLM output for debugging |
| `embedding` | vector(1536) | Yes | `null` | — | pgvector embedding for similarity matching |
| `created_at` | datetime | No | auto | — | Row creation timestamp |
| `updated_at` | datetime | No | auto | — | Last update timestamp |

⁵ **`seniority` choices:** `junior`, `mid`, `senior`, `lead`, `executive`

**Ordering:** `-updated_at`

**Relationships:**
- `resume` → `Resume` (one-to-one)

---

### 30.6 `JobAlert`

A user's job alert subscription linked to a specific resume. The system periodically discovers and matches jobs.

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `user` | int (FK) | No | — | **FK → User**, CASCADE | Alert owner |
| `resume` | UUID (FK) | No | — | **FK → Resume**, PROTECT | Resume used for job matching |
| `frequency` | varchar(10) | No | `'weekly'` | Choices⁶ | Alert frequency |
| `is_active` | bool | No | `true` | Indexed | Whether alert is active |
| `preferences` | JSON | No | `{}` | — | Alert preferences (see below) |
| `last_run_at` | datetime | Yes | `null` | — | Timestamp of last crawl run |
| `next_run_at` | datetime | Yes | `null` | Indexed | When next crawl is scheduled |
| `created_at` | datetime | No | auto | — | Row creation timestamp |
| `updated_at` | datetime | No | auto | — | Last update timestamp |

⁶ **`frequency` choices:** `daily`, `weekly`

**`preferences` JSON shape:**
```json
{
  "excluded_companies": ["Evil Corp"],
  "priority_companies": ["Google", "Stripe"],
  "remote_ok": true,
  "location": "San Francisco",
  "salary_min": 120000
}
```

**Indexes:** `(user, -created_at)`, `(is_active, next_run_at)`

**Ordering:** `-created_at`

**Relationships:**
- `user` → `User` (many-to-one)
- `resume` → `Resume` (many-to-one, PROTECT)
- `matches` → `JobMatch[]` (one-to-many)
- `runs` → `JobAlertRun[]` (one-to-many)

---

### 30.7 `DiscoveredJob`

A job posting discovered from an external source (Firecrawl). Global — not per-user. Deduplicated by `(source, external_id)`.

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `source` | varchar(30) | No | — | Choices⁷, Indexed | Source platform (currently only `firecrawl`) |
| `external_id` | varchar(255) | No | — | Unique⁸ | Unique job ID from the source |
| `source_page_url` | url(2048) | No | `''` | — | The search/career page URL we crawled |
| `url` | url(2048) | No | — | — | Direct link to the actual job posting |
| `title` | varchar(500) | No | `''` | — | Job title |
| `company` | varchar(255) | No | `''` | — | Company name (as displayed in listing) |
| `company_entity` | UUID (FK) | Yes | `null` | **FK → CompanyEntity**, SET_NULL | Matched CompanyEntity record |
| `location` | varchar(255) | No | `''` | — | Job location |
| `country` | varchar(100) | No | `''` | Indexed | Normalised country (used for geo-scoped feed) |
| `salary_range` | varchar(255) | No | `''` | — | Raw salary range string from listing |
| `description_snippet` | text | No | `''` | — | Short job description excerpt |
| **Enriched fields** | | | | | |
| `skills_required` | JSON | No | `[]` | — | Required skills `["Python", "AWS"]` |
| `skills_nice_to_have` | JSON | No | `[]` | — | Nice-to-have skills `["Go", "Terraform"]` |
| `experience_years_min` | smallint | Yes | `null` | — | Minimum years of experience |
| `experience_years_max` | smallint | Yes | `null` | — | Maximum years of experience |
| `employment_type` | varchar(15) | No | `''` | Choices⁹ | Employment type |
| `remote_policy` | varchar(10) | No | `''` | Choices¹⁰ | Remote work policy |
| `seniority_level` | varchar(12) | No | `''` | Choices¹¹ | Seniority level |
| `industry` | varchar(100) | No | `''` | Indexed | Industry sector |
| `education_required` | varchar(50) | No | `''` | — | Minimum education (e.g. "bachelor") |
| `salary_min_usd` | int | Yes | `null` | — | LLM-normalised annual salary lower bound (USD) |
| `salary_max_usd` | int | Yes | `null` | — | LLM-normalised annual salary upper bound (USD) |
| `posted_at` | datetime | Yes | `null` | — | When the job was posted |
| `raw_data` | JSON | Yes | `null` | — | Full raw API response (internal) |
| `embedding` | vector(1536) | Yes | `null` | — | pgvector embedding for similarity matching |
| `created_at` | datetime | No | auto | — | Row creation timestamp |

⁷ **`source` choices:** `firecrawl`

⁸ **Unique constraint:** `(source, external_id)` — one record per job per source.

⁹ **`employment_type` choices:** `full_time`, `part_time`, `contract`, `internship`, `freelance`

¹⁰ **`remote_policy` choices:** `onsite`, `hybrid`, `remote`

¹¹ **`seniority_level` choices:** `intern`, `junior`, `mid`, `senior`, `lead`, `manager`, `director`, `executive`

**Indexes:** `(source, external_id)`, `(-created_at)`, `(industry)`, `(country)`

**Ordering:** `-created_at`

**Relationships:**
- `company_entity` → `CompanyEntity` (many-to-one, nullable)
- `matches` → `JobMatch[]` (one-to-many)
- `sent_alerts` → `SentAlert[]` (one-to-many)

---

### 30.8 `JobMatch`

Junction between a JobAlert and a DiscoveredJob. Stores the relevance score and user feedback.

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `job_alert` | UUID (FK) | No | — | **FK → JobAlert**, CASCADE, Unique¹² | The alert this match belongs to |
| `discovered_job` | UUID (FK) | No | — | **FK → DiscoveredJob**, CASCADE, Unique¹² | The matched job |
| `relevance_score` | smallint | No | — | 0–100 | LLM/pgvector relevance score |
| `match_reason` | text | No | `''` | — | LLM-generated match explanation |
| `user_feedback` | varchar(15) | No | `'pending'` | Choices¹³, Indexed | User's feedback on this match |
| `feedback_reason` | text | No | `''` | — | User-provided reason for feedback (feeds learning loop) |
| `created_at` | datetime | No | auto | — | Row creation timestamp |

¹² **Unique constraint:** `(job_alert, discovered_job)` — one match per job per alert.

¹³ **`user_feedback` choices:** `pending`, `relevant`, `irrelevant`, `applied`, `dismissed`

**Indexes:** `(job_alert, -relevance_score)`, `(job_alert, user_feedback)`

**Ordering:** `-relevance_score`, `-created_at`

**Relationships:**
- `job_alert` → `JobAlert` (many-to-one)
- `discovered_job` → `DiscoveredJob` (many-to-one)

---

### 30.9 `JobAlertRun`

Audit log for each discovery + matching pipeline run. One row per crawl execution per alert.

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `job_alert` | UUID (FK) | No | — | **FK → JobAlert**, CASCADE | The alert this run belongs to |
| `jobs_discovered` | int | No | `0` | — | Total jobs found in this run |
| `jobs_matched` | int | No | `0` | — | Jobs that passed relevance threshold |
| `notification_sent` | bool | No | `false` | — | Whether user was notified |
| `credits_used` | smallint | No | `0` | — | Credits consumed by this run |
| `credits_deducted` | bool | No | `false` | — | Idempotent flag — prevents double-charging on retry |
| `error_message` | text | No | `''` | — | Error details if run failed |
| `duration_seconds` | float | Yes | `null` | — | Pipeline execution time |
| `created_at` | datetime | No | auto | — | Run timestamp |

**Indexes:** `(job_alert, -created_at)`

**Ordering:** `-created_at`

**Relationships:**
- `job_alert` → `JobAlert` (many-to-one)

---

### 30.10 `SentAlert` _(internal)_

Deduplication log — prevents resending the same job to the same user on the same notification channel. No user-facing API.

| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| `id` | UUID | No | `uuid4()` | **PK** | Primary key |
| `user` | int (FK) | No | — | **FK → User**, CASCADE | Recipient |
| `discovered_job` | UUID (FK) | No | — | **FK → DiscoveredJob**, CASCADE | Job that was sent |
| `channel` | varchar(20) | No | — | Choices¹⁴ | Notification channel |
| `sent_at` | datetime | No | auto | — | When notification was sent |

¹⁴ **`channel` choices:** `email`, `in_app`

**Ordering:** `-sent_at`

---

### 30.11 Entity Relationship Diagram

```
Company (1) ──┤ has many ├── CompanyEntity (N)
                                  │
                             has many
                                  │
                       CompanyCareerPage (N)

CompanyEntity (1) ──┤ linked to ├── DiscoveredJob (N)  ← optional FK

User (1) ──┤ has many ├── JobAlert (N)
                              │
                         has many
                              │
                         JobMatch (N) ──┤ links to ├── DiscoveredJob (1)
                              │
                         has many
                              │
                       JobAlertRun (N)

Resume (1) ──┤ has one  ├── JobSearchProfile (1)
Resume (1) ──┤ used by  ├── JobAlert (N)

CrawlSource ── standalone admin model (drives daily crawl)
SentAlert   ── dedup log (User × DiscoveredJob × channel)
```

---

## 32. Quick Reference — All Endpoints

| Method | URL | Auth | Throttle | Description |
|--------|-----|------|----------|-------------|
| **Auth** |||||
| POST | `/api/v1/auth/register/` | ❌ | Auth (20/hr IP) | Create account + auto-login |
| POST | `/api/v1/auth/login/` | ❌ | Auth (20/hr IP) | Get JWT tokens |
| POST | `/api/v1/auth/google/` | ❌ | Auth (20/hr IP) | Google login (Step 1) |
| POST | `/api/v1/auth/google/complete/` | ❌ | Auth (20/hr IP) | Google registration (Step 2) |
| POST | `/api/v1/auth/logout/` | ✅ | User (200/hr) | Blacklist refresh token |
| POST | `/api/v1/auth/token/refresh/` | ❌ | Anon (60/hr IP) | Refresh JWT tokens |
| GET | `/api/v1/auth/me/` | ✅ | User (200/hr) | Current user profile + plan |
| PUT | `/api/v1/auth/me/` | ✅ | User (200/hr) | Update profile (name, email, social links, avatar) |
| DELETE | `/api/v1/auth/me/` | ✅ | User (200/hr) | Delete account permanently |
| POST | `/api/v1/auth/change-password/` | ✅ | User (200/hr) | Change password |
| POST | `/api/v1/auth/forgot-password/` | ❌ | Auth (20/hr IP) | Request password reset email |
| POST | `/api/v1/auth/reset-password/` | ❌ | Auth (20/hr IP) | Set new password with reset token |
| POST | `/api/v1/auth/avatar/` | ✅ | User (200/hr) | Upload avatar image (JPEG/PNG/WebP, max 2 MB) |
| DELETE | `/api/v1/auth/avatar/` | ✅ | User (200/hr) | Remove avatar |
| POST | `/api/v1/auth/contact/` | ❌ | Anon (per IP) | Landing page contact form submission |
| GET | `/api/v1/auth/notifications/` | ✅ | User (200/hr) | Get notification preferences |
| PUT | `/api/v1/auth/notifications/` | ✅ | User (200/hr) | Update notification preferences |
| **Email Verification** |||||
| POST | `/api/v1/auth/verify-email/` | ❌ | Auth (20/hr IP) | Verify email with token |
| POST | `/api/v1/auth/resend-verification/` | ✅ | Auth (20/hr IP) | Resend verification email |
| **Wallet & Plans** |||||
| GET | `/api/v1/auth/wallet/` | ✅ | User (200/hr) | Wallet balance + plan credits info |
| GET | `/api/v1/auth/wallet/transactions/` | ✅ | User (200/hr) | Paginated transaction history |
| GET | `/api/v1/auth/wallet/transactions/export/` | ✅ | User (200/hr) | Download transactions as CSV |
| POST | `/api/v1/auth/wallet/topup/` | ✅ | User (200/hr) | ~~Buy credit packs~~ DEPRECATED — use Razorpay (§21) |
| GET | `/api/v1/auth/plans/` | ❌ | Anon (60/hr IP) | List active plans |
| POST | `/api/v1/auth/plans/subscribe/` | ✅ | User (200/hr) | Downgrade to free plan (402 if target plan is paid — use Razorpay) |
| **Razorpay Payments** |||||
| POST | `/api/v1/auth/payments/subscribe/` | ✅ | Payment (30/hr) | Create Razorpay subscription |
| POST | `/api/v1/auth/payments/subscribe/verify/` | ✅ | Payment (30/hr) | Verify subscription payment |
| POST | `/api/v1/auth/payments/subscribe/cancel/` | ✅ | Payment (30/hr) | Cancel subscription |
| GET | `/api/v1/auth/payments/subscribe/status/` | ✅ | Payment (30/hr) | Subscription status |
| POST | `/api/v1/auth/payments/topup/` | ✅ | Payment (30/hr) | Create top-up order |
| POST | `/api/v1/auth/payments/topup/verify/` | ✅ | Payment (30/hr) | Verify top-up payment |
| POST | `/api/v1/auth/payments/webhook/` | ❌ | None (signature) | Razorpay webhook receiver |
| GET | `/api/v1/auth/payments/history/` | ✅ | Payment (30/hr) | Payment history |
| **Analysis** |||||
| POST | `/api/v1/analyze/` | ✅ | Analyze (10/hr) | Submit new analysis (file upload or `resume_id`) |
| ~~POST~~ | ~~`/api/v1/analyze/bulk/`~~ | — | — | **Removed in v0.34.0** — use single `POST /api/v1/analyze/` per JD |
| GET | `/api/v1/analyses/` | ✅ | Readonly (120/hr) | List analyses (search/filter/sort/paginated) |
| GET | `/api/v1/analyses/compare/` | ✅ | Readonly (120/hr) | Compare 2–5 analyses side-by-side |
| GET | `/api/v1/analyses/<id>/` | ✅ | Readonly (120/hr) | Full analysis detail |
| GET | `/api/v1/analyses/<id>/status/` | ✅ | Readonly (120/hr) | Poll status (lightweight) |
| POST | `/api/v1/analyses/<id>/retry/` | ✅ | Analyze (10/hr) | Retry failed analysis |
| DELETE | `/api/v1/analyses/<id>/delete/` | ✅ | Write (60/hr) | Soft-delete analysis |
| GET | `/api/v1/analyses/<id>/export-pdf/` | ✅ | Readonly (120/hr) | Download PDF report |
| POST | `/api/v1/analyses/<id>/share/` | ✅ | Write (60/hr) | Generate public share link |
| DELETE | `/api/v1/analyses/<id>/share/` | ✅ | Write (60/hr) | Revoke share link |
| **Interview Prep** |||||
| POST | `/api/v1/analyses/<id>/interview-prep/` | ✅ | Write (60/hr) | Generate interview prep (free) |
| GET | `/api/v1/analyses/<id>/interview-prep/` | ✅ | Write (60/hr) | Get latest interview prep status |
| GET | `/api/v1/interview-preps/` | ✅ | Readonly (120/hr) | List all interview preps |
| **Cover Letter** |||||
| POST | `/api/v1/analyses/<id>/cover-letter/` | ✅ | Write (60/hr) | Generate cover letter (free) |
| GET | `/api/v1/analyses/<id>/cover-letter/` | ✅ | Write (60/hr) | Get latest cover letter status |
| GET | `/api/v1/cover-letters/` | ✅ | Readonly (120/hr) | List all cover letters |
| **Resume** |||||
| GET | `/api/v1/resumes/` | ✅ | Readonly (120/hr) | List resumes (search/sort/paginated) |
| DELETE | `/api/v1/resumes/<uuid:id>/` | ✅ | Readonly (120/hr) | Delete resume file (blocked if in use) |
| POST | `/api/v1/resumes/bulk-delete/` | ✅ | Write (60/hr) | Bulk-delete up to 50 resumes |
| POST | `/api/v1/resumes/<uuid:id>/set-default/` | ✅ | Write (60/hr) | Set resume as user's default (§5) |
| GET | `/api/v1/resumes/<uuid:id>/versions/` | ✅ | Readonly (120/hr) | Resume version history |
| **Resume Generation** |||||
| POST | `/api/v1/analyses/<id>/generate-resume/` | ✅ | Analyze (10/hr) | Trigger AI resume generation (1 credit) |
| GET | `/api/v1/analyses/<id>/generated-resume/` | ✅ | Readonly (120/hr) | Poll generation status |
| GET | `/api/v1/analyses/<id>/generated-resume/download/` | ✅ | Readonly (120/hr) | Download generated resume (302 redirect) |
| GET | `/api/v1/generated-resumes/` | ✅ | Readonly (120/hr) | List all generated resumes (paginated) |
| DELETE | `/api/v1/generated-resumes/<uuid:id>/` | ✅ | Readonly (120/hr) | Delete a generated resume |
| **Resume Templates** |||||
| GET | `/api/v1/templates/` | ✅ | Readonly (120/hr) | List active resume templates (§28) |
| **Resume Chat Builder** |||||
| POST | `/api/v1/resume-chat/start/` | ✅ | Write (60/hr) | Start builder session (§29) |
| GET | `/api/v1/resume-chat/` | ✅ | Readonly (120/hr) | List chat sessions |
| GET | `/api/v1/resume-chat/<uuid:id>/` | ✅ | Readonly (120/hr) | Session detail with messages |
| POST | `/api/v1/resume-chat/<uuid:id>/message/` | ✅ | Write (60/hr) | Send text message (text mode) |
| POST | `/api/v1/resume-chat/<uuid:id>/submit/` | ✅ | Write (60/hr) | Submit step action (guided mode) |
| POST | `/api/v1/resume-chat/<uuid:id>/finalize/` | ✅ | Write (60/hr) | Generate PDF/DOCX (2 credits) |
| DELETE | `/api/v1/resume-chat/<uuid:id>/` | ✅ | Readonly (120/hr) | Delete session |
| GET | `/api/v1/resume-chat/resumes/` | ✅ | Readonly (120/hr) | List resumes for base selection |
| **Job Alerts** |||||
| GET | `/api/v1/job-alerts/` | ✅ | Readonly (120/hr) | List user's job alerts (paginated) |
| POST | `/api/v1/job-alerts/` | ✅ | Readonly (120/hr) | Create job alert (Pro, max 5 active, free) |
| GET | `/api/v1/job-alerts/<uuid:id>/` | ✅ | Readonly (120/hr) | Job alert detail |
| PUT | `/api/v1/job-alerts/<uuid:id>/` | ✅ | Readonly (120/hr) | Update job alert |
| DELETE | `/api/v1/job-alerts/<uuid:id>/` | ✅ | Readonly (120/hr) | Deactivate job alert |
| GET | `/api/v1/job-alerts/<uuid:id>/matches/` | ✅ | Readonly (120/hr) | List matches (paginated) |
| POST | `/api/v1/job-alerts/<uuid:id>/matches/<uuid:match_id>/feedback/` | ✅ | Readonly (120/hr) | Submit match feedback |
| POST | `/api/v1/job-alerts/<uuid:id>/run/` | ✅ | Analyze (10/hr) | Trigger manual alert run |
| **Notifications** |||||\n| GET | `/api/v1/notifications/` | ✅ | Readonly (120/hr) | Paginated notification list (§30.0) |\n| GET | `/api/v1/notifications/unread-count/` | ✅ | Readonly (120/hr) | Unread badge count (§30.0) |\n| POST | `/api/v1/notifications/mark-read/` | ✅ | Write (60/hr) | Mark one or all notifications as read (§30.0) |\n| **Feed & Analytics** |||||
| GET | `/api/v1/feed/jobs/` | ✅ | Readonly (120/hr) | Personalised job feed (pgvector similarity). Supports `relevance_min`, `ordering` |
| GET | `/api/v1/feed/insights/` | ✅ | Readonly (120/hr) | Market intelligence (cached 60 min). Role-aware: `?role=all` to disable |
| GET | `/api/v1/feed/trending-skills/` | ✅ | Readonly (120/hr) | User skills vs market demand. Role-aware: `?role=all` to disable |
| GET | `/api/v1/feed/hub/` | ✅ | Readonly (120/hr) | Alerts + preps + cover letters composite |
| GET | `/api/v1/feed/recommendations/` | ✅ | Readonly (120/hr) | AI-suggested next actions |
| GET | `/api/v1/feed/onboarding/` | ✅ | Readonly (120/hr) | Completion checklist |
| **Dashboard** |||||
| GET | `/api/v1/dashboard/stats/` | ✅ | Readonly (120/hr) | User analytics & trends (cached 5 min) |
| GET | `/api/v1/dashboard/skill-gap/` | ✅ | Readonly (120/hr) | Skill radar chart data. Role-aware: `?role=all` to disable |
| GET | `/api/v1/dashboard/market-insights/` | ✅ | Readonly (120/hr) | Weekly trend card (cached 60 min). Role-aware: `?role=all` to disable |
| GET | `/api/v1/dashboard/activity/` | ✅ | Readonly (120/hr) | Activity streak + monthly actions |
| GET | `/api/v1/dashboard/activity/history/` | ✅ | Readonly (120/hr) | Daily activity history (heatmap data) |
| **Share** |||||
| GET | `/api/v1/shared/<uuid:token>/` | ❌ | Anon (60/hr IP) | Public read-only shared analysis |
| GET | `/api/v1/shared/<uuid:token>/summary/` | ❌ | Anon (60/hr IP) | Lightweight score summary for social cards |
| **System** |||||
| GET | `/api/v1/health/` | ❌ | None | Health check |

---

## Changelog

### v0.38.0 — Role-Based Feed & Dashboard Scoping

#### Features — Hybrid Role Scoping
- **`RoleFamily` model** (`analyzer/models.py`): Stores LLM-generated related job titles per unique set of user titles. Deduplicated by SHA-256 hash, shared across users with identical title sets.
- **`generate_role_family_task`** (Celery): Async task that calls the LLM (Claude 3.5 Haiku via OpenRouter) to produce 10–15 related job titles for a user's `JobSearchProfile.titles`. Auto-retries with exponential backoff. Triggered automatically via `post_save` signal on `JobSearchProfile`.
- **Hybrid two-layer role scoping** on 4 endpoints:
  - `GET /api/v1/feed/insights/` (§30.2)
  - `GET /api/v1/feed/trending-skills/` (§30.3)
  - `GET /api/v1/dashboard/skill-gap/` (§30.7)
  - `GET /api/v1/dashboard/market-insights/` (§30.8)
- **Layer 1 — LLM Role Map:** Matches jobs whose title contains any of the user's own titles or LLM-generated related titles (`icontains` queries).
- **Layer 2 — Embedding proximity:** Includes jobs within cosine distance ≤ 0.40 of the user's resume embedding (pgvector `CosineDistance`).
- **Auto-broadening:** If fewer than 5 jobs match after scoping, the role filter is dropped and all jobs in the country are shown (with `broadened: true` in response).
- **`?role=all` query param:** Pass on any of the 4 endpoints to disable role scoping entirely and see data for all roles.
- **`role_filter` response object** added to insights and trending-skills responses: `source_titles`, `related_titles`, `method` (`"llm_map+embedding"` | `"llm_map"` | `"titles_only"` | `"none"`), `scoped` (bool), `broadened` (bool).
- **Cache keys** now include the user's `titles_hash` for role-differentiated caching.

#### Migration
- `0034_add_role_family_model.py` — creates `analyzer_rolefamily` table with `titles_hash` unique index.

#### Frontend Notes
- No breaking changes — existing calls without `?role` continue to work (role scoping applies automatically).
- To show unscoped data, pass `?role=all`.
- Use `role_filter.source_titles` / `role_filter.related_titles` to display a label like "Showing results for: Data Analyst + 3 related roles".
- Add a toggle/button to switch between role-scoped and all-roles views.

### v0.33.0 — Default Resume System, Chat Fixes & Premium Template Hardening

#### Features — Default Resume
- **`is_default` field** added to `Resume` model and all resume list responses (`GET /api/v1/resumes/`).
- **`POST /api/v1/resumes/<uuid>/set-default/`** — new endpoint to change the user's default resume. Busts dashboard cache on change.
- **Auto-default on first upload:** The first resume uploaded by a user is automatically set as the default.
- **Delete fallback:** Deleting the default resume auto-promotes the most recently uploaded remaining resume.
- **Dashboard scoping:** `average_ats_score`, `score_trend`, `grade_distribution`, `top_missing_keywords`, `keyword_match_trend`, `industry_benchmark_percentile` are now scoped to the **default resume's analyses** only. Overview counts (`total_analyses`, `resume_count`, etc.) remain user-wide. Falls back to all analyses if no default is set.
- **`default_resume_id`** field added to `GET /api/v1/dashboard/stats/` response.
- **Feed scoping:** `_get_user_skills()` and `_get_user_embedding()` now use the default resume's `JobSearchProfile`. Affects `feed/jobs/`, `feed/insights/`, `feed/trending-skills/`, `feed/recommendations/`, `dashboard/skill-gap/`.
- **Database constraint:** Partial unique index ensures at most one default resume per user (`unique_default_resume_per_user`).
- **TypeScript:** `Resume` interface now includes `is_default`, `days_since_upload`, `last_analyzed_at`.

#### Bug Fixes
- **Chat 500 error fixed:** `ResumeChatTextMessageSerializer` and `process_text_message` were not imported in `views_chat.py`, causing `NameError` on every `POST /resume-chat/<id>/message/` request.
- **Premium template expiry check:** `accessible` field and template gating on `GenerateResumeView` / `ResumeChatFinalizeView` now check `plan_valid_until`. Expired Pro users correctly lose access to premium templates.
- **`seed_credit_costs` in entrypoint:** Added to startup sequence so `CreditCost` rows (including `interview_prep`) are always present in production. Fixes the `CreditCost row missing` warning.

#### Chat Enhancements
- **Markdown formatting:** Text-mode chat responses now use Markdown (bold, bullet lists, headers). Frontend should render `content` with a Markdown renderer for rich display.

### v0.30.0 — Analyzed Job Sync & Crawler Bot Integration

- **Auto-save analyzed JDs**: Every successful analysis now saves (or updates) the JD as a `DiscoveredJob` with `source = "user_analysis"`. URL-based JDs use the URL as the unique key; text/form JDs use `analysis:<id>`.
- **Embedding auto-compute**: A pgvector embedding is computed for each user-analyzed job, so it immediately participates in personalised feed ranking (`/api/v1/feed/jobs/`).
- **Crawler Bot sync**: If `CRAWLER_BOT_INGEST_URL` and `CRAWLER_API_KEY` are configured, the company and job are pushed to the Crawler Bot's ingest API (fire-and-forget Celery task, never blocks the user).
- **New `CrawlerBotClient` service**: Reusable HTTP client with `X-Crawler-Key` auth, exponential-backoff retry (3 attempts on 429/5xx), 30 s timeout.
- **New `DiscoveredJob.source` value**: `"user_analysis"` added alongside `"firecrawl"`. Feed endpoints already expose the `source` field — no frontend changes needed.
- **No API contract changes**: The analyze endpoint request/response shapes are unchanged. Sync is a backend-only background task.

### v0.28.0 — Feed & Analytics Endpoints

- **9 new GET endpoints** powering the home/feed page and dashboard extras (§30):
  - `/api/v1/feed/jobs/` — Personalised job feed ranked by pgvector embedding similarity (paginated, filterable by remote/seniority/location/employment_type)
  - `/api/v1/feed/insights/` — Market intelligence: top skills, companies, locations, salary avg, breakdowns (cached 60 min)
  - `/api/v1/feed/trending-skills/` — User skills vs market demand with match/gap/niche buckets
  - `/api/v1/feed/hub/` — Composite: active alerts with health indicator + recent interview preps + cover letters
  - `/api/v1/feed/recommendations/` — Rules-based next-action suggestions (sorted by completion + priority)
  - `/api/v1/feed/onboarding/` — 6-step completion checklist with `completion_pct` and `suggested_next`
  - `/api/v1/dashboard/skill-gap/` — Radar chart data (user_score vs market_score per skill)
  - `/api/v1/dashboard/market-insights/` — Weekly job trend summary (this week vs last week, growth %)
  - `/api/v1/dashboard/activity/` — Streak days + actions this month
- **Batch-ready ingest pipeline**: Bot-ingested jobs now automatically trigger batch embeddings (100/API call) + user matching with Redis dedup locks. No frontend changes needed.
- **TypeScript types** added for all feed response shapes.

### v0.37.0 — Generated Resumes Are First-Class Resumes

#### Features
- **Auto-create Resume from GeneratedResume:** Every successfully generated resume (from analysis-based rewrite or chat builder) now automatically creates a full `Resume` record. The generated resume becomes immediately usable for new analyses, job alerts, feed, and embedding-based matching — no re-upload needed.
- **New `resume` field on GeneratedResume responses:** All generated resume endpoints (`GET /api/v1/analyses/<id>/generated-resume/`, `GET /api/v1/generated-resumes/`) now include a `resume` UUID field pointing to the auto-created Resume.
- **Deduplication:** If the generated file's SHA-256 hash matches an existing Resume for the same user, the system links to the existing Resume instead of creating a duplicate.
- **Auto-default:** If the user has no default resume, the auto-created Resume is set as default automatically.
- **JobSearchProfile auto-created:** Career profile (titles, skills, seniority, locations) is derived from the generated `resume_content` and used to create a `JobSearchProfile` for job alert matching.
- **Embedding auto-computed:** A background task computes the resume text embedding immediately after creation for pgvector similarity matching.

#### TypeScript Changes
- `GeneratedResume`: Added `resume: string | null` field (UUID of auto-created Resume, `null` while pending/processing)

#### Migration
- `0032_add_resume_fk_to_generated_resume` — adds nullable FK from `GeneratedResume` → `Resume`

### v0.36.0 — Code Cleanup (Deprecated Module Removal, PostgreSQL Dev Setup)

#### Features
- **Removed deprecated modules:** Deleted `resume_parser.py`, `job_search_profile.py`, `job_matcher.py` — all functionality consolidated into `resume_understanding.py` and `embedding_matcher.py`.
- **PostgreSQL dev setup documented:** README now includes full local development setup instructions for PostgreSQL + pgvector + Redis (Docker, Ubuntu, macOS).

### v0.34.0 — Architecture Simplification (Upload-Time Resume Understanding, Instant Interview Prep, Bulk Removal)

#### ⚠ Breaking Changes
- **`POST /api/v1/analyze/bulk/` removed** — This endpoint no longer exists. Use `POST /api/v1/analyze/` individually per JD. Frontend should convert any bulk submission logic to sequential or parallel single-analysis calls.
- **`resume_parse` pipeline step removed** — The analysis pipeline is now **4 steps** (`pdf_extract` → `jd_scrape` → `llm_call` → `parse_result`) instead of 5. The `resume_parse` value may still appear on older analyses but will not be emitted for new ones. Update progress bar mappings accordingly.

#### Features
- **Upload-time resume understanding (Phase A):** Resume parsing + career profile extraction now happen automatically at upload time via a background task. Three new fields on `Resume`: `processing_status` (`"pending"` → `"processing"` → `"done"` / `"failed"`), `parsed_content` (structured resume data), `career_profile` (target roles, skills, preferences). This means `parsed_content` is available **before** any analysis runs.
- **Instant interview prep (Phase C):** `POST /api/v1/analyses/<id>/interview-prep/` now returns `200 OK` with complete results instantly from a curated DB question bank (filtered by role, skills, and gap analysis). No polling needed. Falls back to async LLM (`202 Accepted`) only if the question bank is empty.
- **Pipeline reduced to 4 steps (Phase B):** Removed the `resume_parse` step from the analysis pipeline. Resume parsing data is now copied from the `Resume` model during `parse_result`. Crash recovery treats `resume_parse` as already complete.
- **LLM fallback matching removed (Phase E):** Job matching now uses pgvector embeddings exclusively. The LLM-based fallback matcher has been removed entirely.

#### TypeScript Changes
- `PipelineStep`: `'resume_parse'` moved to legacy (kept for backward compat but no longer emitted)
- `ResumeListItem` / resume responses: Added `processing_status`, `parsed_content`, `career_profile` fields
- Interview prep POST response: Now typically `200 OK` (instant) instead of `202 Accepted` (async)

#### Migration Notes
- If your frontend has a "Bulk Analyze" button or form, remove it or convert to sequential single calls.
- `STEP_PROGRESS` map should be updated: remove `resume_parse` from the main flow, adjust percentages (see §13).
- Interview prep UI can drop the polling spinner for the common case — check HTTP status code: `200` = ready, `202` = poll.

### v0.26.0 — Conversational Resume Builder

#### Features
- **Conversational Resume Builder**: Build resumes from scratch through a guided chat experience — one question at a time, Claude-style. 11-step wizard (contact → target role → experience → education → skills → certifications → projects → review → done) with rich interactive UI components.
- **3 data sources**: Start fresh (`scratch`), pre-fill from profile data (`profile`), or copy from a previous resume (`previous`).
- **7 new endpoints** under `/api/v1/resume-chat/`: `start/`, list, detail, `submit/`, `finalize/`, delete, `resumes/`.
- **Rich UI spec system**: Each assistant message includes a `ui_spec` JSON with type-specific rendering instructions — `editable_card`, `buttons`, `single_select`, `multi_select_chips`, `text_input`, `textarea`, `form_group`, `card_list`, `preview`, `template_picker`.
- **Minimal LLM usage**: Only 1-2 AI calls per session (experience structuring + final polish). All other steps are pure frontend input.
- **Credit cost**: 2 credits per finalized resume. Charged on finalize only. Auto-refund on render failure.
- **Max 5 active sessions** per user.
- **`resume_data` schema** matches existing `GeneratedResume.resume_content` — all template renderers work unchanged.

#### TypeScript Changes
- New types: `ResumeChat`, `ChatMessage`, `UISpec`, `ResumeChatListItem`, `SubmitResponse`, `FinalizeResponse`, `BaseResume` (§29.10).
- New enums: `ChatSource`, `ChatStatus`, `ChatStep`, `MessageRole`, `UISpecType`.

### v0.25.0 — Resume Template Marketplace

#### Features
- **Resume Template Marketplace**: 5 resume templates with distinct visual styles — `ats_classic` (free), `modern`, `executive`, `creative`, `minimal` (premium). Templates are stored in the DB (`ResumeTemplate` model) and managed via Django Admin.
- **New endpoint: `GET /api/v1/templates/`** — Browse active resume templates. Returns `accessible` flag per user's plan. Auth required.
- **Premium template gating**: Premium templates (`is_premium: true`) require a plan with `premium_templates: true`. Using a premium template without access returns **403** with `is_premium` and `template` in the response body.
- **`premium_templates` field on Plan model**: Boolean flag controlling access to premium templates. Default: `false`. Managed via Django Admin or seed data.
- **Template parameter in resume generation is now DB-validated**: `POST /api/v1/analyses/<id>/generate-resume/` validates the `template` slug against active templates in the DB. Invalid or inactive templates return **400** with available slugs listed.
- **New management command: `seed_templates`** — Seeds 5 default templates (idempotent).
- **Template renderers**: Each template has dedicated PDF (ReportLab) and DOCX (python-docx) renderers with distinct typography, colors, and layouts.

#### TypeScript Changes
- `ResumeTemplate` type changed from string literal `'ats_classic'` to `string` (template slugs are now dynamic, fetched from API).
- New `ResumeTemplate` interface added (§28.4) with `accessible`, `is_premium`, `category`, `preview_image_url` fields.

### v0.24.0 — Email Verification, Bulk Analysis, Interview Prep, Cover Letter, Infrastructure & API Versioning

#### ⚠ Breaking Changes
- **API versioning** — All endpoints moved from `/api/` to `/api/v1/`. Update your `API_URL` / `VITE_API_URL` / `EXPO_PUBLIC_API_URL` from `http://localhost:8000/api` to `http://localhost:8000/api/v1`. The old `/api/` prefix returns 404.
- **Registration** no longer sends welcome email immediately — sends verification email instead. Frontend must handle the verification step.

#### Features
- **Email verification flow**: Registration now sends a verification email instead of a welcome email. Response includes `email_verification_required: true` and `is_email_verified: false`. New endpoints: `POST /api/v1/auth/verify-email/`, `POST /api/v1/auth/resend-verification/`. Welcome email is sent only after verification.
- **`is_email_verified` field**: Added to user object in register, login, and `GET /api/v1/auth/me/` responses.
- **Bulk analysis**: ~~`POST /api/v1/analyze/bulk/`~~ **Removed in v0.34.0.** Use single `POST /api/v1/analyze/` per JD instead.
- **Interview prep generation**: `POST /api/v1/analyses/<id>/interview-prep/` (free, no credit cost) — **Now instant (200 OK)** using a curated DB question bank. Questions are filtered by role, skills, and gap analysis. Falls back to async LLM (202) only if question bank is empty. `GET` on same URL returns status/results. `GET /api/v1/interview-preps/` lists all.
- **Cover letter generation**: `POST /api/v1/analyses/<id>/cover-letter/` (free, no credit cost) — AI-generated cover letter with tone selection (`professional`, `conversational`, `enthusiastic`). Returns `content` (plain text) and `content_html`. `GET` on same URL returns status/results. `GET /api/v1/cover-letters/` lists all.
- **Resume version history**: `GET /api/v1/resumes/<uuid>/versions/` — tracks resume evolution with version numbers, `best_ats_score`, and `best_grade` per version. Auto-linked when re-uploading same filename.
- **Rate limit headers on all responses**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers are now included in every API response. Use to show proactive warnings before users hit 429.
- **New credit costs**: `interview_prep = 0` (free), `cover_letter = 0` (free), `job_alert_run = 0` (free).

#### Infrastructure
- **Structured JSON logging** — Production logs now emit JSON format (via `python-json-logger`) for better log aggregation in Railway/Datadog. Local dev unchanged (human-readable format).
- **Prometheus metrics** — `GET /metrics` exposes Prometheus-compatible metrics: analysis duration, LLM token usage, credit operations, payment failures, Celery task stats. No auth required (standard for metrics endpoints).
- **Gunicorn timeout reduced** — From 120s to 110s to respond before Railway's proxy timeout kills the connection.
- **Flower dashboard** — Celery monitoring via Flower available as a separate Railway service (`SERVICE_TYPE=flower`). Protected by basic auth (`FLOWER_USER`/`FLOWER_PASSWORD` env vars).
- **Celery monitoring endpoints** (admin-only):
  - `GET /api/v1/admin/celery/workers/` — Active workers and stats
  - `GET /api/v1/admin/celery/tasks/active/` — Currently running tasks
  - `GET /api/v1/admin/celery/tasks/<task_id>/` — Task status by ID
  - `GET /api/v1/admin/celery/queues/` — Queue lengths
- **Session invalidation** on password change — all existing tokens blacklisted

### v0.23.0 — Code Quality & Validation Hardening

- **PDF magic-byte validation enforced**: Uploading a non-PDF file (e.g. DOCX, HTML, image) now returns **400** with `"The uploaded file is not a valid PDF. Please upload a PDF document."` before any processing begins. Previously, invalid files would fail deeper in the pipeline with less clear errors.
- **DOCX resume generation sanitised**: Control characters and null bytes in user data are now stripped before DOCX rendering, preventing corrupted output files.
- **No API contract changes** — all endpoints, request/response schemas, and error codes remain identical to v0.22.0.

### v0.22.0 — Plans, Pricing & Contact Form

- **3 plans seeded**: Free (₹0), Pro Monthly (₹399, was ₹599), Pro Yearly (₹3,999, was ₹7,188)
- **`original_price` field** added to Plan model and serializer — use for strikethrough pricing display
- **Job alert quota re-enforced**: `max_job_alerts` field is now active again — Pro plan limited to **5 active alerts**. Free plan has no access (`job_notifications = false`, `max_job_alerts = 0`). Alert runs are **free** (no credit cost).
- **Contact form endpoint**: `POST /api/v1/auth/contact/` — public, anon-throttled, no auth required
- **ContactSubmission model**: `name`, `email`, `subject`, `message`, `created_at` — viewable in Django Admin (read-only)
- **Auto-sync plans to Razorpay**: New paid plans are automatically synced via `post_save` signal. Admin also shows sync feedback on save. Existing "Sync with Razorpay" action available as manual fallback.
- **PostgreSQL fix**: Migration 0014 sets server-side `DEFAULT ''` on `razorpay_plan_id` column to prevent `IntegrityError` when creating plans via Admin

### v0.29.0 — Dashboard Stats Expansion & Activity Tracking

#### ⚠ Breaking Changes
- **`credit_usage` data contract fixed**: Items now include `subtype` and `count` fields. `type` maps from raw `transaction_type` to `"debit"`/`"credit"`. `total` is now the absolute sum of amounts (always positive). Old format: `{month, type, total}`. New format: `{month, type, subtype, count, total}`.

#### Features
- **25+ new dashboard stats fields**: `best_ats_score`, `worst_ats_score`, `keyword_match_trend`, `resume_count`, `generated_resumes_total/done`, `interview_preps_total/done`, `cover_letters_total/done`, `chat_sessions_active/completed`, `job_alerts_count`, `active_job_alerts`, `total_job_matches`, `matches_applied/relevant/irrelevant`, `llm_calls`, `llm_tokens_used`, `llm_cost_usd`, `plan_usage`, `activity_streak`.
- **`UserActivity` model**: Tracks daily user actions (analysis, resume gen, interview prep, cover letter, job alert run, builder finalize, login). Powers the `activity_streak` field in dashboard stats.
- **Activity streak**: `streak_days` (consecutive days with ≥1 action) and `actions_this_month` (total actions in current calendar month).
- **Plan usage breakdown**: `plan_usage` object with `plan_name`, `analyses_this_month`, `analyses_limit`, `usage_percent`.
- **LLM usage stats**: `llm_calls`, `llm_tokens_used`, `llm_cost_usd` aggregated from `LLMResponse` model.

#### TypeScript Changes
- `DashboardStats` interface expanded from 7 fields to 35+ fields.
- New interfaces: `CreditUsageItem`, `KeywordMatchTrendItem`, `PlanUsage`, `ActivityStreak`.

### v0.28.0 — Company Intelligence & Enriched Job Crawl

- **Company models**: New `Company`, `CompanyEntity`, `CompanyCareerPage` models for structured company tracking. Supports multi-entity companies (e.g., "Stripe US" vs "Stripe India Pvt Ltd" as separate entities under one brand). Career pages are per-entity and drive priority crawling.
- **Enriched `DiscoveredJob`**: Jobs now carry LLM-extracted structured data — `skills_required`, `skills_nice_to_have`, `experience_years_min/max`, `employment_type`, `remote_policy`, `seniority_level`, `industry`, `education_required`, `salary_min_usd`, `salary_max_usd`. Zero extra API cost (same LLM call, expanded schema).
- **`source_page_url`** field on `DiscoveredJob`: Tracks which search/career page we crawled to discover the job. `url` remains the actual job posting link.
- **`company_entity`** FK on `DiscoveredJob`: Links discovered jobs to known company entities for priority matching and analytics.
- **TypeScript type changes**: `DiscoveredJob` interface expanded with all enriched fields.

### v0.21.0 — Frontend–Backend Gap Fixes

- **28 items implemented** across P0, P1, and P2 priorities. See [CHANGELOG.md](CHANGELOG.md) for full details.
- **New endpoints:** `POST/DELETE /api/v1/auth/avatar/`, `GET /api/v1/auth/wallet/transactions/export/`, `DELETE /api/v1/generated-resumes/<uuid>/`, `POST /api/v1/resumes/bulk-delete/`, `GET /api/v1/analyses/compare/`, `GET /api/v1/shared/<token>/summary/`
- **New query params on analyses:** `?search=`, `?status=`, `?score_min=`, `?score_max=`, `?ordering=`
- **New query params on resumes:** `?search=`, `?ordering=`
- **New writable fields on `PUT /api/v1/auth/me/`:** `first_name`, `last_name`, `website_url`, `github_url`, `linkedin_url`, `avatar_url`
- **New fields in resume list:** `days_since_upload`, `last_analyzed_at`
- **New fields in job alert list:** `total_matches`
- **New dashboard stats fields:** `keyword_match_percent` in score_trend, `top_missing_keywords`, `credit_usage`, `weekly_job_matches`, `industry_benchmark_percentile`
- **Breaking:** Payment history response changed from `{count, payments}` to `{count, next, previous, results}` with DRF pagination. `?limit=` replaced by `?page=`.

### v0.18.0 — Server-side Feed Sorting & Filtering + Ingest Fix

- **`relevance_min` query param** on `GET /api/v1/feed/jobs/`: Float 0–1. Only returns jobs with `relevance >= value`. Applied **before pagination** so `count` and page numbers are accurate. Jobs without embeddings are excluded when set. Silently ignored if invalid.
- **`ordering` query param** on `GET /api/v1/feed/jobs/`: Sort field with `-` prefix for descending. Allowed values: `relevance` (default), `-posted_at` (newest first), `-salary_min_usd` (highest salary first). Invalid values fall back to `relevance`. Null `posted_at`/`salary_min_usd` values sort last.
- **Geo-priority preserved:** When no explicit `country` param is passed, the user's country jobs always sort first (primary key), with `ordering` as the secondary sort. This matches existing behaviour.
- **Frontend migration:** Replace client-side sort/filter with API params: `params.set('relevance_min', matchMin)`, `params.set('ordering', '-posted_at')`. No response shape changes — `count`, `page`, `page_size`, `country`, `results` remain identical.
- **Ingest upsert fix:** `POST /api/v1/ingest/jobs/` and `/jobs/bulk/` now correctly upsert on `(source, external_id)` — re-pushing existing jobs updates them instead of returning a 400 duplicate error. No frontend impact (crawler-only endpoints).

### v0.17.0 — Unified Job Alerts Architecture

- **Job model removed**: The manual job tracker (`/api/v1/jobs/`) has been removed. All job discovery is now handled exclusively through Smart Job Alerts.
- **Firecrawl replaces SerpAPI/Adzuna**: Job crawling now uses Firecrawl for web scraping. The `source` field on discovered jobs is now `"firecrawl"` (previously `"serpapi"` or `"adzuna"`).
- **CrawlSource admin model**: Admins can configure crawl sources (job boards and company career pages) via Django Admin.
- **Admin-configurable crawl schedule**: The crawl schedule is now managed via `django-celery-beat` instead of a hardcoded 6-hour interval. Default: daily at 20:30 UTC.
- **pgvector matching**: Job matching uses OpenAI embeddings with pgvector cosine-similarity instead of LLM scoring.
- **`priority_companies` preference**: New preference field to boost matches from preferred companies. Allowed preference keys: `excluded_companies`, `priority_companies`, `remote_ok`, `location`, `salary_min`.
- **`feedback_reason` field**: `POST .../feedback/` now accepts an optional `feedback_reason` (free-text) alongside `user_feedback`.
- **Feedback learning loop**: Past feedback (relevant/irrelevant with reasons) now trains the matching algorithm — boosting/penalising companies and keywords for future runs.
- **TypeScript type changes**: `JobAlertPreferences` updated (removed `location_filter`/`date_filter`, added `priority_companies`/`remote_ok`/`location`/`salary_min`). `JobMatch` now includes `feedback_reason`. `DiscoveredJob.source` changed from union type to `string`.

### v0.15.0 — Edge Case Fixes

- **New `write` throttle scope (60/hour):** Analysis delete (`DELETE /api/v1/analyses/<id>/delete/`), share create (`POST /api/v1/analyses/<id>/share/`), and share revoke (`DELETE /api/v1/analyses/<id>/share/`) now use the stricter `write` scope instead of `readonly`.
- **`quick_wins` count is 1–3:** Previously documented as "always exactly 3 items"; the backend now validates and accepts 1–3 items.
- **Payment history `limit` clamped:** The `limit` query parameter on `GET /api/v1/auth/payments/history/` is now clamped server-side to **1–100**.
- **`section_feedback[].score` clamped 0–100:** Scores outside range are now clamped by the backend.
- **`overall_grade` always uppercase:** The backend normalises the LLM response to uppercase (`A`–`F`).
- **Subscription model:** Users can now have multiple historical subscriptions. The subscription status endpoint always returns the latest active subscription.
- **`posted_at` on discovered jobs:** Now returns ISO-8601 dates (previously could be relative strings like "3 days ago").
- **Salary currency:** Discovered jobs now include the correct currency symbol based on country (e.g., `£` for GB, `$` for US, `₹` for IN).

### v0.14.0 — Security Hardening

- **Account deletion requires password** (`DELETE /api/v1/auth/profile/`)
- **`celery_task_id` removed** from analysis responses
- **`payment` throttle scope** added (30/hour) for all payment endpoints