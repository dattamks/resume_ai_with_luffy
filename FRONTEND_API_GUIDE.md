# Frontend API Integration Guide

> **Last updated:** 2026-02-27 &nbsp;|&nbsp; **API version:** v0.18.0
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
22. [Quick Reference — All Endpoints](#22-quick-reference--all-endpoints)

---

## 1. Base URL & Authentication

### Base URL

```
Development:  http://localhost:8000/api
Production:   https://<backend>.up.railway.app/api
```

Configure via environment variable:

```env
# .env (Vite)
VITE_API_URL=http://localhost:8000/api

# .env (React Native / Expo)
EXPO_PUBLIC_API_URL=http://localhost:8000/api
```

### Authentication — JWT (Bearer Token)

All endpoints except `/api/auth/register/`, `/api/auth/login/`, `/api/auth/token/refresh/`, and `/api/health/` require a JWT access token.

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
POST /api/auth/token/refresh/
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
// src/api/client.js
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

All prefixed with `/api/auth/`.

### POST `/api/auth/register/` — Create Account

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
| `username` | string | ✅ | Unique username |
| `email` | string | ✅ | Valid email address |
| `password` | string | ✅ | Min 8 chars, can't be too common/numeric |
| `password2` | string | ✅ | Must match `password` |
| `agree_to_terms` | boolean | ✅ | Must be `true` — Terms of Service & Privacy Policy |
| `agree_to_data_usage` | boolean | ✅ | Must be `true` — AI data processing & Data Usage Policy |
| `marketing_opt_in` | boolean | ❌ | Optional (default `false`) — marketing emails & newsletters |

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
  "username": ["A user with that username already exists."],
  "password": ["This password is too common."],
  "password2": ["Passwords do not match."],
  "agree_to_terms": ["You must agree to the Terms of Service and Privacy Policy."],
  "agree_to_data_usage": ["You must acknowledge the Data Usage & AI Disclaimer."]
}
```

> **Consent audit:** Three `ConsentLog` entries are recorded per registration (terms, data usage, marketing) with the user's IP address, user agent, and timestamp. This log is immutable — used for GDPR/compliance auditing.
>
> **Newsletter sync:** When `marketing_opt_in` is `true`, the user's `NotificationPreference.newsletters_email` is automatically set to `true`.

> **Email:** A welcome email (HTML template `welcome`) is sent to the registered email address on successful registration.

---

### POST `/api/auth/login/` — Sign In

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

### POST `/api/auth/logout/` — Sign Out

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

### GET `/api/auth/me/` — Current User Profile

🔒 Requires auth. Returns the currently authenticated user's profile including phone fields and plan.

**Response (200):**
```json
{
  "id": 1,
  "username": "john",
  "email": "john@example.com",
  "date_joined": "2026-02-22T10:00:00Z",
  "country_code": "+91",
  "mobile_number": "",
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

### PUT `/api/auth/me/` — Update Profile

🔒 Requires auth. Update the current user's username, email, and/or phone fields. Partial updates are supported (send only the fields you want to change).

**Request (JSON):**
```json
{
  "username": "new_name",
  "email": "new@example.com",
  "country_code": "+1",
  "mobile_number": "5551234567"
}
```

**Response (200):**
```json
{
  "id": 1,
  "username": "new_name",
  "email": "new@example.com",
  "date_joined": "2026-02-22T10:00:00Z",
  "country_code": "+1",
  "mobile_number": "5551234567",
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

### DELETE `/api/auth/me/` — Delete Account

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

### POST `/api/auth/change-password/` — Change Password

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

### POST `/api/auth/forgot-password/` — Request Password Reset

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

### POST `/api/auth/reset-password/` — Set New Password

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

### GET `/api/auth/notifications/` — Get Notification Preferences

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

### PUT `/api/auth/notifications/` — Update Notification Preferences

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

### POST `/api/auth/token/refresh/` — Refresh JWT

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
         POST /api/auth/google/  { token: "<google_id_token>" }
         ↓
         Existing user? → JWT tokens returned (done!)
         New user?      → { needs_registration: true, temp_token, email, name, picture }

Step 2:  Frontend shows consent form + username/password fields
         ↓
         POST /api/auth/google/complete/  { temp_token, username, password, consents... }
         ↓
         User created → JWT tokens returned (done!)
```

### POST `/api/auth/google/` — Google Login (Step 1)

Verifies a Google ID token. For existing users, returns JWT tokens immediately. For new users, returns a temporary token to complete registration.

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

### POST `/api/auth/google/complete/` — Complete Google Registration (Step 2)

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
  const res = await api.post('/api/auth/google/', { token: googleIdToken });

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
  const res = await api.post('/api/auth/google/complete/', formData);
  storeTokens(res.data.access, res.data.refresh);
  navigateToDashboard();
}
```

---

## 4. Analysis Endpoints

All prefixed with `/api/`.

### POST `/api/analyze/` — Submit New Analysis

🔒 Requires auth. **Throttled:** 10/hour per user. Accepts **`multipart/form-data`** (file upload) or **`application/json`** (resume reuse).

Submits a resume + job description for async analysis. Returns immediately with a tracking ID. The analysis runs asynchronously via Celery background workers.

**Two ways to provide the resume — exactly one is required:**

1. **Upload a new PDF** → send `resume_file` via `multipart/form-data`.
2. **Reuse an existing resume** → send `resume_id` (UUID from `GET /api/resumes/`) via JSON or form field.

**Idempotency guard:** A second submit within 30 seconds returns **409 Conflict**. The frontend should **disable the submit button** after the first click and show a loading state.

**Form / JSON fields:**

| Field                 | Type    | Required                    | Description                                              |
|-----------------------|---------|-----------------------------|----------------------------------------------------------|
| `resume_file`         | File    | ✅ unless `resume_id` sent  | PDF file, max 5 MB, must have `.pdf` extension and `%PDF` magic bytes |
| `resume_id`           | UUID    | ✅ unless `resume_file` sent | UUID of an existing Resume owned by the user (from `GET /api/resumes/`) |
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
| 400  | Invalid resume_id | `{ "resume_id": ["Resume not found or does not belong to you."] }` |
| 400  | Missing JD fields | `{ "jd_text": ["Job description text is required when input type is \"text\"."] }` |
| 409  | Duplicate submit | `{ "detail": "An analysis is already being submitted. Please wait." }` |
| 429  | Rate limited | `{ "detail": "Request was throttled. Expected available in 120 seconds." }` |

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
  resume_id: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',  // from GET /api/resumes/
  jd_input_type: 'text',
  jd_text: 'We need a senior Python developer...',
});
// data = { id: 43, status: "processing", credits_used: 1, balance: 3 }
```

---

### GET `/api/analyses/` — List Analyses (Paginated)

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Returns **paginated** list of the user's own analyses, newest first.

Only returns **active** (non-soft-deleted) analyses.

**Query parameters:**

| Param  | Default | Description |
|--------|---------|-------------|
| `page` | 1       | Page number (20 items per page) |

**Response (200):**
```json
{
  "count": 47,
  "next": "http://localhost:8000/api/analyses/?page=3",
  "previous": "http://localhost:8000/api/analyses/?page=1",
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
      "share_url": "https://yourhost.com/api/shared/a1b2c3d4-e5f6-7890-abcd-ef1234567890/",
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

### GET `/api/analyses/<id>/` — Analysis Detail

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Returns the full analysis with all results, nested scrape result, and LLM response.

Returns 404 if the analysis is soft-deleted or belongs to another user.

**Response (200):** See [Detail Response Schema](#detail-response-schema) in section 9.

---

### GET `/api/analyses/<id>/status/` — Poll Status (Lightweight)

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

### POST `/api/analyses/<id>/retry/` — Retry Failed Analysis

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

### DELETE `/api/analyses/<id>/delete/` — Soft-Delete Analysis

🔒 Requires auth. **Throttled:** `write` scope (60/hour).

Performs a **soft-delete** — the analysis row is preserved in the database with lightweight metadata for analytics, but is removed from all list/detail views.

**What happens on soft-delete:**
- `deleted_at` timestamp is set
- Heavy text fields cleared (`resume_text`, `resolved_jd`, `jd_text`)
- Report PDF deleted from R2 storage
- Orphaned `ScrapeResult` and `LLMResponse` rows cleaned up
- Lightweight metadata preserved: `ats_score`, `jd_role`, `jd_company`, `status`, `created_at`
- The analysis **no longer appears** in `GET /api/analyses/` list or `GET /api/analyses/<id>/` detail
- Soft-deleted analyses **are counted** in `GET /api/dashboard/stats/` for audit trail

**Response (204):** No content.

**Error (404):** `{ "detail": "Not found." }` — Analysis doesn't exist, already soft-deleted, or belongs to another user.

**Frontend action:** Remove the analysis from local state/cache after a successful 204. No need to check `deleted_at` fields — the backend handles filtering automatically.

---

### GET `/api/analyses/<id>/export-pdf/` — Download PDF Report

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

---

## 5. Resume Endpoints

All prefixed with `/api/`.

Resume files are **deduplicated by SHA-256 hash per user** — uploading the same PDF for multiple analyses stores the file only once. Each unique file gets a `Resume` row with a UUID primary key.

### GET `/api/resumes/` — List Resumes (Paginated)

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Returns **paginated** list of the user's deduplicated resume files, newest first.

**Query parameters:**

| Param  | Default | Description |
|--------|---------|-------------|
| `page` | 1       | Page number (20 items per page) |

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
      "file_url": "https://r2.example.com/resumes/my_resume_2026.pdf"
    },
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "original_filename": "resume_v2.pdf",
      "file_size_bytes": 198432,
      "uploaded_at": "2026-02-20T08:15:00Z",
      "active_analysis_count": 1,
      "file_url": "https://r2.example.com/resumes/resume_v2.pdf"
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

**Frontend usage:** Use `active_analysis_count` to show how many analyses reference each resume, and to determine whether the delete button should show a warning.

---

### DELETE `/api/resumes/<uuid:id>/` — Delete Resume

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Permanently deletes the resume file from R2 storage.

**Blocked if active analyses exist.** Only allowed when `active_analysis_count === 0` (no active, non-soft-deleted analyses reference this resume). If active analyses exist, returns **409 Conflict**.

**Response (204):** No content — resume and file permanently deleted.

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

## 6. Dashboard Endpoints

### GET `/api/dashboard/stats/` — User Dashboard Analytics

🔒 Requires auth. **Throttled:** `readonly` scope (120/hour). Returns aggregated analytics from **all** analyses (including soft-deleted) for a complete audit trail.

**Response (200):**
```json
{
  "total_analyses": 47,
  "active_analyses": 42,
  "deleted_analyses": 5,
  "average_ats_score": 76.3,
  "score_trend": [
    {
      "ats_score": 85,
      "jd_role": "Senior Developer",
      "created_at": "2026-02-23T14:00:00Z"
    },
    {
      "ats_score": 72,
      "jd_role": "Backend Engineer",
      "created_at": "2026-02-22T10:00:00Z"
    }
  ],
  "top_roles": [
    { "jd_role": "Backend Engineer", "count": 12 },
    { "jd_role": "Full Stack Developer", "count": 8 },
    { "jd_role": "DevOps Engineer", "count": 5 },
    { "jd_role": "ML Engineer", "count": 3 },
    { "jd_role": "Frontend Developer", "count": 2 }
  ],
  "analyses_per_month": [
    { "month": "2025-09-01T00:00:00Z", "count": 3 },
    { "month": "2025-10-01T00:00:00Z", "count": 7 },
    { "month": "2025-11-01T00:00:00Z", "count": 10 },
    { "month": "2025-12-01T00:00:00Z", "count": 5 },
    { "month": "2026-01-01T00:00:00Z", "count": 15 },
    { "month": "2026-02-01T00:00:00Z", "count": 7 }
  ]
}
```

**Response fields:**

| Field                | Type           | Description                                                 |
|----------------------|----------------|-------------------------------------------------------------|
| `total_analyses`     | int            | All analyses ever created (including soft-deleted)           |
| `active_analyses`    | int            | Non-deleted analyses                                        |
| `deleted_analyses`   | int            | Soft-deleted analyses                                       |
| `average_ats_score`  | float \| null  | Average ATS score across all **completed** analyses; `null` if no completed analyses |
| `score_trend`        | array          | Last **10** completed analyses with score, role, and date (newest first) |
| `top_roles`          | array          | Top **5** most-analyzed job roles with count                 |
| `analyses_per_month` | array          | Monthly analysis count for the last **6 months** (oldest first) |

**`score_trend` item:**

| Field        | Type     | Description                      |
|--------------|----------|----------------------------------|
| `ats_score`  | int      | ATS score (0-100)                |
| `jd_role`    | string   | Job role analyzed                |
| `created_at` | datetime | When analysis was submitted      |

**`top_roles` item:**

| Field    | Type   | Description          |
|----------|--------|----------------------|
| `jd_role`| string | Job role name        |
| `count`  | int    | Number of analyses   |

**`analyses_per_month` item:**

| Field   | Type     | Description                                    |
|---------|----------|------------------------------------------------|
| `month` | datetime | First day of the month (ISO 8601)              |
| `count` | int      | Total analyses submitted in that month          |

**Frontend usage suggestions:**

| Data Field          | UI Component          | Library Suggestion     |
|--------------------|-----------------------|------------------------|
| `total/active/deleted` | Summary stat cards | Simple `<div>` cards   |
| `average_ats_score`    | Large gauge/number | `ScoreGauge` component |
| `score_trend`          | Line chart          | Chart.js, Recharts     |
| `top_roles`            | Horizontal bar chart | Chart.js, Recharts     |
| `analyses_per_month`   | Bar/area chart       | Chart.js, Recharts     |

---

## 7. Share Endpoints

Allow users to generate a public, read-only link for a completed analysis. Anyone with the link can view the results — no login required.

### POST `/api/analyses/<id>/share/` — Generate Share Link

🔒 Requires auth. **Throttled:** `write` scope (60/hour). Only works on **completed** (`status: "done"`) analyses.

**Idempotent:** If a share token already exists, returns the existing token (200). Otherwise creates a new one (201).

**Request:** Empty body (no payload needed).

**Response (201 Created / 200 OK):**
```json
{
  "share_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "share_url": "https://yourhost.com/api/shared/a1b2c3d4-e5f6-7890-abcd-ef1234567890/"
}
```

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Analysis not complete | `{ "detail": "Only completed analyses can be shared." }` |
| 404  | Not found / not owner | `{ "detail": "Not found." }` |

**Frontend usage:**
```js
const { data } = await api.post(`/analyses/${id}/share/`);
const fullUrl = `${window.location.origin}/shared/${data.share_token}`;
navigator.clipboard.writeText(fullUrl);
showToast('Share link copied!');
```

---

### DELETE `/api/analyses/<id>/share/` — Revoke Share Link

🔒 Requires auth. **Throttled:** `write` scope (60/hour). Immediately revokes the share token — the public link stops working.

**Request:** Empty body.

**Response (204):** No content.

**Errors:**

| Code | Condition | Response |
|------|-----------|----------|
| 400  | Not currently shared | `{ "detail": "This analysis is not currently shared." }` |
| 404  | Not found / not owner | `{ "detail": "Not found." }` |

---

### GET `/api/shared/<token>/` — Public Shared Analysis

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
| `created_at`           | datetime        | When analysis was submitted                              |

**Error (404):**
```json
{ "detail": "Shared analysis not found or link has been revoked." }
```

> **Soft-deleted analyses** are not accessible via share links — the default manager automatically excludes them.

---

## 8. Health Check

### GET `/api/health/` — Health Check

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

Returned by `GET /api/analyses/<id>/`. This is the full analysis payload with all results.

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
  "ai_provider_used": "OpenRouterProvider",
  "report_pdf_url": "https://r2.example.com/reports/report_42.pdf",
  "share_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "share_url": "https://yourhost.com/api/shared/a1b2c3d4-e5f6-7890-abcd-ef1234567890/",
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

All list endpoints (`GET /api/analyses/`, `GET /api/resumes/`, `GET /api/generated-resumes/`, `GET /api/job-alerts/`, `GET /api/job-alerts/<id>/matches/`) return paginated responses.

| Setting     | Value                    |
|-------------|--------------------------|
| Page size   | 20 items per page        |
| Style       | `PageNumberPagination`   |
| Query param | `?page=N`               |

**Envelope format:**
```json
{
  "count": 47,
  "next": "http://localhost:8000/api/analyses/?page=3",
  "previous": "http://localhost:8000/api/analyses/?page=1",
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
| `analyze` (per user) | 10 / hour | `ANALYZE_THROTTLE_RATE` | `POST /api/analyze/`, `POST /api/analyses/<id>/retry/` |
| `readonly` (per user) | 120 / hour | `READONLY_THROTTLE_RATE` | All authenticated read endpoints |
| `write` (per user) | 60 / hour | `WRITE_THROTTLE_RATE` | Analysis delete, share toggle |
| `payment` (per user) | 30 / hour | `PAYMENT_THROTTLE_RATE` | All Razorpay payment endpoints (subscribe, verify, cancel, topup, history) |

When rate-limited, the API returns:

```http
HTTP 429 Too Many Requests
Retry-After: 120

{
  "detail": "Request was throttled. Expected available in 120 seconds."
}
```

**Exempt endpoints (no throttle applied):**
- `GET /api/health/` — health check (must always respond)
- `GET /api/shared/<token>/` — public shared analysis (uses default `anon` scope only)

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

After submitting an analysis (`POST /api/analyze/` → `{ id, status }`), poll the lightweight status endpoint until complete.

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

### Recommended polling implementation

```js
/**
 * Poll analysis status until done/failed.
 * @param {number} analysisId - The analysis ID from POST /api/analyze/
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
  pdf_extract: 15,
  jd_scrape: 35,
  llm_call: 55,
  parse_result: 85,
  done: 100,
  failed: 0,
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

**Single error (most endpoints):**
```json
{
  "detail": "Human-readable error message."
}
```

**Validation errors (400 on create/submit):**
```json
{
  "resume_file": ["Only PDF files are accepted."],
  "jd_text": ["Job description text is required when input type is \"text\"."]
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

  switch (status) {
    case 400:
      // Validation errors — may be field-level or detail
      if (data.detail) return { type: 'validation', message: data.detail };
      // Field-level errors: { field: [errors] }
      const fieldErrors = Object.entries(data)
        .map(([field, msgs]) => `${field}: ${msgs.join(', ')}`)
        .join('\n');
      return { type: 'validation', message: fieldErrors };

    case 401:
      return { type: 'auth', message: 'Session expired. Please log in again.' };

    case 404:
      return { type: 'not_found', message: 'Resource not found.' };

    case 409:
      return { type: 'conflict', message: data.detail || 'Request conflicts with current state.' };

    case 429:
      const retryAfter = error.response.headers['retry-after'] || '60';
      return { type: 'rate_limit', message: `Too many requests. Try again in ${retryAfter}s.` };

    case 503:
      return { type: 'service', message: 'Service temporarily unavailable. Try again later.' };

    default:
      return { type: 'unknown', message: data.detail || 'An unexpected error occurred.' };
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
  price: string;          // decimal as string, e.g. "499.00"
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
                  | 'parse_result' | 'done' | 'failed';

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
  share_url: string;            // e.g., "https://yourhost.com/api/shared/<uuid>/"
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

interface DashboardStats {
  total_analyses: number;
  active_analyses: number;
  deleted_analyses: number;
  average_ats_score: number | null;
  score_trend: ScoreTrendItem[];
  top_roles: TopRoleItem[];
  analyses_per_month: MonthlyCountItem[];
}
```

---

## 16. Frontend Integration Recipes

### Recipe 1: Analysis Submit Flow (React)

```jsx
import { useState } from 'react';
import api from '../api/client';

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
import api from '../api/client';

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
import api from '../api/client';

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
import api from '../api/client';

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
POST /api/analyze/ → balance ≥ 1? → NO → 402 "Insufficient credits"
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
| `price` | `DecimalField(8,2)` | Price in INR (`0.00` for free tier) |
| `credits_per_month` | `int` | Credits granted each billing cycle |
| `max_credits_balance` | `int` | Max credits from monthly grants (`0` = no cap). Top-ups bypass this |
| `topup_credits_per_pack` | `int` | Credits per top-up pack (`0` = top-up not allowed) |
| `topup_price` | `DecimalField(8,2)` | Price per top-up pack in INR |
| `analyses_per_month` | `int` | Max analyses per month (`0` = unlimited) |
| `api_rate_per_hour` | `int` | Max general API requests per hour |
| `max_resume_size_mb` | `int` | Max resume file size in MB |
| `max_resumes_stored` | `int` | Max resumes stored at once (`0` = unlimited) |
| `job_notifications` | `bool` | Can receive job alert notifications |
| `max_job_alerts` | `int` | Maximum active job alerts (`0` = disabled) |
| `pdf_export` | `bool` | Can export analysis as PDF |
| `share_analysis` | `bool` | Can generate public share links |
| `job_tracking` | `bool` | Can use job tracking features |
| `priority_queue` | `bool` | Analyses processed in priority Celery queue |
| `email_support` | `bool` | Has access to email support |
| `is_active` | `bool` | Inactive plans cannot be assigned to new users |
| `display_order` | `int` | Sort order on pricing page (lower = first) |

### Default Plans

Seeded via `python manage.py seed_plans` (idempotent — safe to re-run).

| Name | Slug | Price | Credits/mo | Cap | Top-up | Job Notifications | Rate | Resumes |
|------|------|-------|-----------|-----|--------|-------------------|------|---------|
| **Free** | `free` | ₹0 | 2 | 10 | ❌ | ❌ | 200/hr | 5 stored, 5MB max |
| **Pro** | `pro` | ₹499/mo | 25 | 100 | 5 credits/₹49 | ✅ | 500/hr | Unlimited, 10MB max |

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

#### `GET /api/auth/wallet/`

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

#### `GET /api/auth/wallet/transactions/`

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

#### `POST /api/auth/wallet/topup/` *(DEPRECATED)*

> **Deprecated in v0.13.1.** Credit top-ups now require payment via Razorpay.
> Use `POST /api/auth/payments/topup/` instead (see [§ 21](#21-razorpay-payments)).

This endpoint now always returns **402 Payment Required**:

```json
{
  "detail": "Credit top-ups require payment. Use POST /api/auth/payments/topup/ instead.",
  "payment_url": "/api/auth/payments/topup/"
}
```

**Migration guide:** Replace direct top-up calls with the Razorpay checkout flow:
1. `POST /api/auth/payments/topup/` → get `order_id` + `key_id`
2. Open Razorpay checkout with the returned params
3. `POST /api/auth/payments/topup/verify/` → credits are added after payment verification

### Plan Endpoints

#### `GET /api/auth/plans/`

List all active plans. **Public endpoint — no auth required.**

**Response:**
```json
[
  {
    "id": 1,
    "name": "Free",
    "slug": "free",
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
    "credits_per_month": 25,
    "topup_credits_per_pack": 5,
    "topup_price": "49.00",
    "job_notifications": true,
    "max_job_alerts": 10,
    "...": "..."
  }
]
```

#### `POST /api/auth/plans/subscribe/`

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
  "detail": "Upgrading to a paid plan requires payment. Use POST /api/auth/payments/subscribe/ instead.",
  "payment_url": "/api/auth/payments/subscribe/"
}
```

> **Migration guide:** To upgrade to Pro, use the Razorpay subscription flow:
> 1. `POST /api/auth/payments/subscribe/` with `{"plan_slug": "pro"}`
> 2. Open Razorpay checkout with the returned `subscription_id` + `key_id`
> 3. `POST /api/auth/payments/subscribe/verify/` → plan is upgraded after payment

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

`POST /api/analyze/` and `POST /api/analyses/<id>/retry/` now include credit info:

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
| `password-reset` | `auth` | `POST /api/auth/forgot-password/` | `{{ username }}`, `{{ reset_link }}`, `{{ expiry_hours }}`, `{{ app_name }}` |
| `welcome` | `auth` | `POST /api/auth/register/` | `{{ username }}`, `{{ frontend_url }}`, `{{ app_name }}` |
| `password-changed` | `auth` | `POST /api/auth/change-password/` | `{{ username }}`, `{{ changed_at }}`, `{{ app_name }}` |

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

### 19.1 Trigger Generation

```
POST /api/analyses/<id>/generate-resume/
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
| `template` | `string` | `"ats_classic"` | `ats_classic` | Resume layout template |
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
| 402 | Insufficient credits | `{"detail": "...", "balance": 0, "cost": 1}` |
| 404 | Analysis not found / not owned | Standard 404 |

### 19.2 Poll Generation Status

```
GET /api/analyses/<id>/generated-resume/
Authorization: Bearer <token>
```

**Response — 200 OK:**

```json
{
  "id": "a1b2c3d4-...",
  "analysis": 42,
  "template": "ats_classic",
  "format": "pdf",
  "status": "done",
  "error_message": "",
  "file_url": "https://r2.example.com/generated_resumes/...",
  "created_at": "2026-02-26T12:00:00Z"
}
```

| `status` | Meaning |
|----------|---------|
| `pending` | Queued, not yet picked up by worker |
| `processing` | LLM rewrite + render in progress |
| `done` | File ready for download via `file_url` |
| `failed` | Generation failed — check `error_message`. Credits refunded automatically. |

**Polling recommendation:** Same pattern as analysis polling — start at 2s, back off to 5s.

### 19.3 Download Generated Resume

```
GET /api/analyses/<id>/generated-resume/download/
Authorization: Bearer <token>
```

**Response — 302 Redirect** to signed R2 download URL (1-hour TTL).

| Status | Condition |
|--------|-----------|
| 302 | File ready — `Location` header contains signed URL |
| 404 | No generated resume, or generation not done yet |

### 19.4 List All Generated Resumes

```
GET /api/generated-resumes/
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

### 19.5 TypeScript Types

```typescript
type ResumeTemplate = 'ats_classic';
type ResumeFormat = 'pdf' | 'docx';
type GeneratedResumeStatus = 'pending' | 'processing' | 'done' | 'failed';

interface GenerateResumeRequest {
  template?: ResumeTemplate;
  format?: ResumeFormat;
}

interface GenerateResumeResponse {
  id: string;
  status: GeneratedResumeStatus;
  template: ResumeTemplate;
  format: ResumeFormat;
  credits_used: number;
  balance: number;
}

interface GeneratedResume {
  id: string;
  analysis: number;
  template: ResumeTemplate;
  format: ResumeFormat;
  status: GeneratedResumeStatus;
  error_message: string;      // "" when no error, not null
  file_url: string | null;
  created_at: string;
}
```

### 19.6 Frontend Integration Recipe

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
- **Quota**: Each plan defines `max_job_alerts` (Free=0, Pro=3)
- **Credits**: Each alert run costs **1 credit** (`job_alert_run` action)
- **Crawl schedule**: Admin-configurable via `django-celery-beat` (default: daily at 20:30 UTC). Crawl sources are managed in Django Admin via the `CrawlSource` model.
- **Matching**: Uses pgvector cosine-similarity against OpenAI embeddings, with a feedback learning loop that adjusts scores based on past user feedback.

### 20.1 List / Create Job Alerts

```
GET  /api/job-alerts/
POST /api/job-alerts/
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
| 403 | `{"detail": "You have reached the maximum of 3 active job alerts...", "max_job_alerts": 3, "active_count": 3}` |
| 400 | Validation error (invalid resume, etc.) |

### 20.2 Job Alert Detail

```
GET    /api/job-alerts/<uuid:id>/
PUT    /api/job-alerts/<uuid:id>/
DELETE /api/job-alerts/<uuid:id>/
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
GET /api/job-alerts/<uuid:id>/matches/
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
  "next": "http://localhost:8000/api/job-alerts/.../matches/?page=3",
  "previous": "http://localhost:8000/api/job-alerts/.../matches/?page=1",
  "results": [
    {
      "id": "uuid",
      "job": {
        "id": "uuid",
        "source": "firecrawl",
        "title": "Senior Python Developer",
        "company": "TechCorp",
        "location": "Remote",
        "url": "https://...",
        "salary_range": "$120k-$160k",
        "description_snippet": "We're looking for...",
        "posted_at": "2025-01-01T00:00:00Z",
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
POST /api/job-alerts/<uuid:id>/matches/<uuid:match_id>/feedback/
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
POST /api/job-alerts/<uuid:id>/run/
```

Triggers an immediate job discovery + matching run for the alert. Costs 1 credit.

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
| 402 | Insufficient credits |

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
  location: string;
  url: string;
  salary_range: string;
  description_snippet: string;
  posted_at: string | null;
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
  const { data } = await api.get('/api/job-alerts/', { params: { page } });
  return data;  // paginated { count, next, previous, results }
};

// Create a new alert
const createAlert = async (resumeId: string, frequency: 'daily' | 'weekly') => {
  const { data } = await api.post('/api/job-alerts/', {
    resume: resumeId,
    frequency,
  });
  return data;
};

// Fetch matches for an alert
const fetchMatches = async (alertId: string, page = 1, feedback?: string) => {
  const params: Record<string, string> = { page: String(page) };
  if (feedback) params.feedback = feedback;
  const { data } = await api.get(`/api/job-alerts/${alertId}/matches/`, { params });
  return data;  // paginated { count, next, previous, results }
};

// Submit feedback on a match
const submitFeedback = async (alertId: string, matchId: string, feedback: MatchFeedback, reason?: string) => {
  const { data } = await api.post(
    `/api/job-alerts/${alertId}/matches/${matchId}/feedback/`,
    { user_feedback: feedback, feedback_reason: reason }
  );
  return data;
};

// Trigger manual run
const triggerRun = async (alertId: string) => {
  const { data } = await api.post(`/api/job-alerts/${alertId}/run/`);
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
POST /api/auth/payments/subscribe/
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
POST /api/auth/payments/subscribe/verify/
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
POST /api/auth/payments/subscribe/cancel/
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
GET /api/auth/payments/subscribe/status/
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
POST /api/auth/payments/topup/
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
POST /api/auth/payments/topup/verify/
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
GET /api/auth/payments/history/?limit=20
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
POST /api/auth/payments/webhook/
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
  const { data } = await api.post('/api/auth/payments/subscribe/', {
    plan_slug: 'pro',
  });

  const options = {
    key: data.key_id,
    subscription_id: data.subscription_id,
    name: 'i-Luffy',
    description: `${data.plan_name} Plan`,
    handler: async (response: RazorpayResponse) => {
      const result = await api.post('/api/auth/payments/subscribe/verify/', {
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
  const { data } = await api.post('/api/auth/payments/topup/', { quantity });

  const options = {
    key: data.key_id,
    amount: data.amount,
    currency: data.currency,
    order_id: data.order_id,
    name: 'i-Luffy',
    description: `${data.credits} Credits`,
    handler: async (response: RazorpayResponse) => {
      const result = await api.post('/api/auth/payments/topup/verify/', {
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
  const { data } = await api.get('/api/auth/payments/subscribe/status/');
  return data;
};

// 5. Cancel subscription
const cancelSubscription = async () => {
  const { data } = await api.post('/api/auth/payments/subscribe/cancel/');
  await fetchMe();
  toast.info(data.message);
};
```

---

## 22. Quick Reference — All Endpoints

| Method | URL | Auth | Throttle | Description |
|--------|-----|------|----------|-------------|
| **Auth** |||||
| POST | `/api/auth/register/` | ❌ | Auth (20/hr IP) | Create account + auto-login |
| POST | `/api/auth/login/` | ❌ | Auth (20/hr IP) | Get JWT tokens |
| POST | `/api/auth/google/` | ❌ | Auth (20/hr IP) | Google login (Step 1) |
| POST | `/api/auth/google/complete/` | ❌ | Auth (20/hr IP) | Google registration (Step 2) |
| POST | `/api/auth/logout/` | ✅ | User (200/hr) | Blacklist refresh token |
| POST | `/api/auth/token/refresh/` | ❌ | Anon (60/hr IP) | Refresh JWT tokens |
| GET | `/api/auth/me/` | ✅ | User (200/hr) | Current user profile + plan |
| PUT | `/api/auth/me/` | ✅ | User (200/hr) | Update username/email/phone |
| DELETE | `/api/auth/me/` | ✅ | User (200/hr) | Delete account permanently |
| POST | `/api/auth/change-password/` | ✅ | User (200/hr) | Change password |
| POST | `/api/auth/forgot-password/` | ❌ | Auth (20/hr IP) | Request password reset email |
| POST | `/api/auth/reset-password/` | ❌ | Auth (20/hr IP) | Set new password with reset token |
| GET | `/api/auth/notifications/` | ✅ | User (200/hr) | Get notification preferences |
| PUT | `/api/auth/notifications/` | ✅ | User (200/hr) | Update notification preferences |
| **Wallet & Plans** |||||
| GET | `/api/auth/wallet/` | ✅ | User (200/hr) | Wallet balance + plan credits info |
| GET | `/api/auth/wallet/transactions/` | ✅ | User (200/hr) | Paginated transaction history |
| POST | `/api/auth/wallet/topup/` | ✅ | User (200/hr) | ~~Buy credit packs~~ DEPRECATED — use Razorpay (§21) |
| GET | `/api/auth/plans/` | ❌ | Anon (60/hr IP) | List active plans |
| POST | `/api/auth/plans/subscribe/` | ✅ | User (200/hr) | Switch plan (upgrade/downgrade) |
| **Razorpay Payments** |||||
| POST | `/api/auth/payments/subscribe/` | ✅ | Payment (30/hr) | Create Razorpay subscription |
| POST | `/api/auth/payments/subscribe/verify/` | ✅ | Payment (30/hr) | Verify subscription payment |
| POST | `/api/auth/payments/subscribe/cancel/` | ✅ | Payment (30/hr) | Cancel subscription |
| GET | `/api/auth/payments/subscribe/status/` | ✅ | Payment (30/hr) | Subscription status |
| POST | `/api/auth/payments/topup/` | ✅ | Payment (30/hr) | Create top-up order |
| POST | `/api/auth/payments/topup/verify/` | ✅ | Payment (30/hr) | Verify top-up payment |
| POST | `/api/auth/payments/webhook/` | ❌ | None (signature) | Razorpay webhook receiver |
| GET | `/api/auth/payments/history/` | ✅ | Payment (30/hr) | Payment history |
| **Analysis** |||||
| POST | `/api/analyze/` | ✅ | Analyze (10/hr) | Submit new analysis (file upload or `resume_id`) |
| GET | `/api/analyses/` | ✅ | Readonly (120/hr) | List analyses (paginated) |
| GET | `/api/analyses/<id>/` | ✅ | Readonly (120/hr) | Full analysis detail |
| GET | `/api/analyses/<id>/status/` | ✅ | Readonly (120/hr) | Poll status (lightweight) |
| POST | `/api/analyses/<id>/retry/` | ✅ | Analyze (10/hr) | Retry failed analysis |
| DELETE | `/api/analyses/<id>/delete/` | ✅ | Write (60/hr) | Soft-delete analysis |
| GET | `/api/analyses/<id>/export-pdf/` | ✅ | Readonly (120/hr) | Download PDF report |
| POST | `/api/analyses/<id>/share/` | ✅ | Write (60/hr) | Generate public share link |
| DELETE | `/api/analyses/<id>/share/` | ✅ | Write (60/hr) | Revoke share link |
| **Resume** |||||
| GET | `/api/resumes/` | ✅ | Readonly (120/hr) | List resumes (with `file_url` for download) |
| DELETE | `/api/resumes/<uuid:id>/` | ✅ | Readonly (120/hr) | Delete resume file (blocked if in use) |
| **Resume Generation** |||||
| POST | `/api/analyses/<id>/generate-resume/` | ✅ | Analyze (10/hr) | Trigger AI resume generation (1 credit) |
| GET | `/api/analyses/<id>/generated-resume/` | ✅ | Readonly (120/hr) | Poll generation status |
| GET | `/api/analyses/<id>/generated-resume/download/` | ✅ | Readonly (120/hr) | Download generated resume (302 redirect) |
| GET | `/api/generated-resumes/` | ✅ | Readonly (120/hr) | List all generated resumes (paginated) |
| **Job Alerts** |||||
| GET | `/api/job-alerts/` | ✅ | Readonly (120/hr) | List user's job alerts (paginated) |
| POST | `/api/job-alerts/` | ✅ | Readonly (120/hr) | Create job alert (Pro, 1 credit/run) |
| GET | `/api/job-alerts/<uuid:id>/` | ✅ | Readonly (120/hr) | Job alert detail |
| PUT | `/api/job-alerts/<uuid:id>/` | ✅ | Readonly (120/hr) | Update job alert |
| DELETE | `/api/job-alerts/<uuid:id>/` | ✅ | Readonly (120/hr) | Deactivate job alert |
| GET | `/api/job-alerts/<uuid:id>/matches/` | ✅ | Readonly (120/hr) | List matches (paginated) |
| POST | `/api/job-alerts/<uuid:id>/matches/<uuid:match_id>/feedback/` | ✅ | Readonly (120/hr) | Submit match feedback |
| POST | `/api/job-alerts/<uuid:id>/run/` | ✅ | Analyze (10/hr) | Trigger manual alert run |
| **Dashboard** |||||
| GET | `/api/dashboard/stats/` | ✅ | Readonly (120/hr) | User analytics & trends (cached 5 min) |
| **Share** |||||
| GET | `/api/shared/<uuid:token>/` | ❌ | Anon (60/hr IP) | Public read-only shared analysis |
| **System** |||||
| GET | `/api/health/` | ❌ | None | Health check |

---

## Changelog

### v0.17.0 — Unified Job Alerts Architecture

- **Job model removed**: The manual job tracker (`/api/jobs/`) has been removed. All job discovery is now handled exclusively through Smart Job Alerts.
- **Firecrawl replaces SerpAPI/Adzuna**: Job crawling now uses Firecrawl for web scraping. The `source` field on discovered jobs is now `"firecrawl"` (previously `"serpapi"` or `"adzuna"`).
- **CrawlSource admin model**: Admins can configure crawl sources (job boards and company career pages) via Django Admin.
- **Admin-configurable crawl schedule**: The crawl schedule is now managed via `django-celery-beat` instead of a hardcoded 6-hour interval. Default: daily at 20:30 UTC.
- **pgvector matching**: Job matching uses OpenAI embeddings with pgvector cosine-similarity instead of LLM scoring.
- **`priority_companies` preference**: New preference field to boost matches from preferred companies. Allowed preference keys: `excluded_companies`, `priority_companies`, `remote_ok`, `location`, `salary_min`.
- **`feedback_reason` field**: `POST .../feedback/` now accepts an optional `feedback_reason` (free-text) alongside `user_feedback`.
- **Feedback learning loop**: Past feedback (relevant/irrelevant with reasons) now trains the matching algorithm — boosting/penalising companies and keywords for future runs.
- **TypeScript type changes**: `JobAlertPreferences` updated (removed `location_filter`/`date_filter`, added `priority_companies`/`remote_ok`/`location`/`salary_min`). `JobMatch` now includes `feedback_reason`. `DiscoveredJob.source` changed from union type to `string`.

### v0.15.0 — Edge Case Fixes

- **New `write` throttle scope (60/hour):** Analysis delete (`DELETE /api/analyses/<id>/delete/`), share create (`POST /api/analyses/<id>/share/`), and share revoke (`DELETE /api/analyses/<id>/share/`) now use the stricter `write` scope instead of `readonly`.
- **`quick_wins` count is 1–3:** Previously documented as "always exactly 3 items"; the backend now validates and accepts 1–3 items.
- **Payment history `limit` clamped:** The `limit` query parameter on `GET /api/auth/payments/history/` is now clamped server-side to **1–100**.
- **`section_feedback[].score` clamped 0–100:** Scores outside range are now clamped by the backend.
- **`overall_grade` always uppercase:** The backend normalises the LLM response to uppercase (`A`–`F`).
- **Subscription model:** Users can now have multiple historical subscriptions. The subscription status endpoint always returns the latest active subscription.
- **`posted_at` on discovered jobs:** Now returns ISO-8601 dates (previously could be relative strings like "3 days ago").
- **Salary currency:** Discovered jobs now include the correct currency symbol based on country (e.g., `£` for GB, `$` for US, `₹` for IN).

### v0.14.0 — Security Hardening

- **Account deletion requires password** (`DELETE /api/auth/profile/`)
- **`celery_task_id` removed** from analysis responses
- **`payment` throttle scope** added (30/hour) for all payment endpoints
- **Session invalidation** on password change — all existing tokens blacklisted