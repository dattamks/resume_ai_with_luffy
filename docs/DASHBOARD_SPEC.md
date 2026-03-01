# Dashboard Page — KPIs, Metrics & Widget Specification

**File:** `src/pages/DashboardPage.jsx`  
**Last Updated:** 2026-03-01  
**Primary Endpoint:** `GET /api/v1/dashboard/stats/`  
**Additional Data Source:** `AuthContext` → `user` object (wallet, plan)

---

## Overview

The dashboard is organized in four visual tiers:

1. **Must Have** — Credits, Latest Score, Quick Actions, Recent Analyses, Job Alerts
2. **Should Have** — Trends & Analytics (charts, breakdowns, summary)
3. **Good to Have** — Collapsible "Insights & Intelligence" section (mix of API-driven and placeholder)
4. **Zero State** — Empty state CTA when user has no analyses

---

## Widget-by-Widget Breakdown

### 1. Credits Remaining

| Property | Detail |
|---|---|
| **Type** | KPI Tile |
| **Data Source** | `AuthContext` → `user.wallet.balance`, `user.plan.name`, `user.plan.credits_per_month` |
| **Endpoint** | `GET /api/v1/auth/me/` (loaded by AuthContext on login) |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Large number (credit balance), plan name, credits per month. Turns red and shows "Top up credits" link when ≤ 1. |
| **Understanding** | The user object from auth contains a nested `wallet` with `balance` and a `plan` with `name` and `credits_per_month`. These populate automatically when the user is authenticated. |

---

### 2. Latest Score

| Property | Detail |
|---|---|
| **Type** | KPI Tile with ScoreGauge (animated ring) |
| **Data Source** | `stats.score_trend[0]` (most recent analysis) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `score_trend` array |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | `ScoreGauge` ring displaying `ats_score`, plus role name and date. Shows "—" dash if no analyses exist. |
| **Understanding** | `score_trend` is sorted newest-first by the backend. We take `[0]` for the latest entry. Each item contains `{ jd_role, ats_score, workday_ats, greenhouse_ats, created_at }`. |

---

### 3. Quick Actions

| Property | Detail |
|---|---|
| **Type** | Action buttons card |
| **Data Source** | Static links; conditionally shows "View Last Report" if `score_trend` has entries |
| **Endpoint** | N/A (static UI) |
| **Status** | ✅ Live |
| **What it shows** | Three buttons: "Analyze Resume" → `/analyze`, "View Last Report" → `/history` (conditional), "Resume Library" → `/resumes`. |

---

### 4. Recent Analyses

| Property | Detail |
|---|---|
| **Type** | List (last 5 entries) |
| **Data Source** | `stats.score_trend` (sliced to first 5) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `score_trend` array |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Each row: colored dot (green/amber/red based on score), role name, ATS score, date. Links to full history. |
| **Understanding** | Uses `scoreBgClass()` utility for color coding. Hidden entirely if no analyses. Shows max 5 items. |

---

### 5. Smart Job Alerts

| Property | Detail |
|---|---|
| **Type** | Link card |
| **Data Source** | Static UI — links to `/job-alerts` |
| **Endpoint** | N/A (the `/job-alerts` page itself calls `GET /api/v1/job-alerts/`) |
| **Status** | ✅ Live (static link only, no count badge) |
| **What it shows** | Bell icon, "Smart Job Alerts" title, "Discover jobs matching your resume" subtitle, "View alerts →" link. |
| **Understanding** | This is a navigation entry point. The actual job alert counting/listing happens on the JobAlertsPage. A future improvement could show the unread count here. |

---

### 6. Score Trend (Line Chart)

| Property | Detail |
|---|---|
| **Type** | Recharts `LineChart` |
| **Data Source** | `stats.score_trend` (reversed to chronological order) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `score_trend` |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | X-axis: role names (truncated at 12 chars). Y-axis: 0–100. Single indigo line plotting `ats_score`. Custom tooltip shows full role name, date, and score. |
| **Understanding** | Backend returns newest-first; frontend reverses for left-to-right chronological display. Only renders when ≥ 2 data points exist. Workday/Greenhouse ATS scores are available in the data but not plotted (could be added as additional lines). |
| **Visibility** | Hidden if `score_trend` has < 2 items |

---

### 7. Grade Distribution (Bar Chart)

| Property | Detail |
|---|---|
| **Type** | Recharts `BarChart` |
| **Data Source** | `stats.grade_distribution` (object: `{ A: n, B: n, C: n, D: n, F: n }`) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `grade_distribution` |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Vertical bars for A/B/C/D/F grades, each with a distinct color (green/blue/yellow/orange/red). Only grades with count > 0 are shown. |
| **Understanding** | The backend aggregates all analyses into letter-grade buckets. Frontend maps color by grade letter. |
| **Visibility** | Hidden if all grade counts are 0 |

---

### 8. Top Industries Analyzed

| Property | Detail |
|---|---|
| **Type** | Horizontal progress bars |
| **Data Source** | `stats.top_industries` (array of `{ jd_industry, count }`) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `top_industries` |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Each industry name with count, rendered as a progress bar relative to the top industry's count (normalized to 100%). |
| **Understanding** | Backend returns industries sorted by frequency descending. Progress bar width is `(count / maxCount) * 100%`. |
| **Visibility** | Hidden if `top_industries` is empty |

---

### 9. Analysis Summary

| Property | Detail |
|---|---|
| **Type** | 3-column KPI tiles |
| **Data Source** | `stats.total_analyses`, `stats.active_analyses`, `stats.deleted_analyses` |
| **Endpoint** | `GET /api/v1/dashboard/stats/` |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Three large numbers: Total (gray), Active (green), Deleted (muted gray). |
| **Understanding** | Simple integer counts. Always visible when dashboard loads with data. |

---

### 10. Analyses per Month (Bar Chart)

| Property | Detail |
|---|---|
| **Type** | Recharts `BarChart` |
| **Data Source** | `stats.analyses_per_month` (array of `{ month, count }`) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `analyses_per_month` |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Monthly bar chart. X-axis: month abbreviation (parsed from ISO datetime). Y-axis: analysis count. Indigo bars. |
| **Understanding** | `month` field from API is an ISO datetime like `"2025-09-01T00:00:00Z"`. Frontend parses to `"Sep"`, `"Oct"`, etc. |
| **Visibility** | Hidden if no monthly data |

---

### 11. Top Roles Analyzed

| Property | Detail |
|---|---|
| **Type** | Horizontal progress bars |
| **Data Source** | `stats.top_roles` (array of `{ jd_role, count }`) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `top_roles` |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Each role name with count, rendered as an indigo-to-purple gradient progress bar relative to the top role's count. |
| **Understanding** | Same presentation pattern as Top Industries. Backend returns roles sorted by frequency. |
| **Visibility** | Hidden if `top_roles` is empty |

---

### 12. Resume Health ⏳ PLACEHOLDER

| Property | Detail |
|---|---|
| **Type** | Info card with icon |
| **Data Source** | **Hardcoded text** |
| **Endpoint** | **None — no backend endpoint exists** |
| **Status** | ⏳ Placeholder — marked "Coming Soon" |
| **What it shows** | Warning icon, "Resume Health" title, hardcoded text: "Your resume hasn't been updated in 30 days. 12 new keywords are trending in your target role." Plus a "Re-analyze now" link to `/analyze`. |
| **Understanding** | Would need a backend endpoint that tracks when the user's resume was last analyzed and compares trending keywords in the user's target role against their resume. No such API exists. |
| **What's needed from backend** | An endpoint like `GET /api/v1/dashboard/resume-health/` returning `{ days_since_last_analysis, trending_keywords_count, trending_keywords[] }`. |

---

### 13. Benchmark

| Property | Detail |
|---|---|
| **Type** | Info card with icon |
| **Data Source** | `stats.industry_benchmark_percentile` with fallback to `PLACEHOLDER_BENCHMARK` (68) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `industry_benchmark_percentile` |
| **Status** | ✅ Live — dynamic, with hardcoded fallback |
| **What it shows** | "Your latest resume scores higher than X% of candidates for your target role." |
| **Understanding** | When the API returns `industry_benchmark_percentile` as a number, it's used directly. When it's `null` (no data), the constant `PLACEHOLDER_BENCHMARK = 68` is shown as fallback. The fallback is cosmetic — it keeps the card visually populated. |

---

### 14. Top Missing Keywords

| Property | Detail |
|---|---|
| **Type** | Chip/tag list |
| **Data Source** | `stats.top_missing_keywords` (array of strings or `{ keyword, count }` objects) |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `top_missing_keywords` |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Up to 10 red chips showing keywords missing from the user's resume. Below: keyword match rate percentage if available. |
| **Understanding** | Handles both string arrays and object arrays (`{ keyword, count }`) for forward compatibility. Count is displayed in parentheses if available. `keyword_match_percent` is shown as a summary stat below. |
| **Visibility** | Hidden if `top_missing_keywords` is empty |

---

### 15. Credit Usage

| Property | Detail |
|---|---|
| **Type** | Progress bar with summary |
| **Data Source** | `stats.credit_usage` (array of `{ type, total }` where type is "debit" or "credit") |
| **Endpoint** | `GET /api/v1/dashboard/stats/` → `credit_usage` |
| **Status** | ✅ Live — fully dynamic |
| **What it shows** | Total debits used out of total credits, rendered as a text fraction and an indigo progress bar. Also shows `weekly_job_matches` count if available. |
| **Understanding** | Frontend filters by `type === 'debit'` and `type === 'credit'` to compute totals. Progress bar width is `(debits / credits) * 100%`, capped at 100%. |
| **Visibility** | Hidden if `credit_usage` is empty |

---

### 16. Skill Gap Analysis (Radar Chart) ⏳ PLACEHOLDER

| Property | Detail |
|---|---|
| **Type** | Recharts `RadarChart` |
| **Data Source** | **`PLACEHOLDER_SKILL_GAP` constant** (hardcoded: Python, SQL, Cloud, CI/CD, ML, Docker) |
| **Endpoint** | **None — no backend endpoint exists** |
| **Status** | ⏳ Placeholder — marked "Coming Soon" |
| **What it shows** | Radar chart with two overlapping areas: "Your Resume" (solid indigo) vs "Market Demand" (dashed purple). Six skill axes. |
| **Understanding** | The backend would need to analyze the user's resume skills and cross-reference them against market demand data for the user's target role/industry. No such analysis endpoint exists. The hardcoded data is illustrative only. |
| **What's needed from backend** | An endpoint like `GET /api/v1/dashboard/skill-gap/` returning `[{ skill, user_score, market_score }]`. |

---

### 17. Weekly Insight ⏳ PLACEHOLDER

| Property | Detail |
|---|---|
| **Type** | Info card with icon |
| **Data Source** | **Hardcoded text** |
| **Endpoint** | **None — no backend endpoint exists** |
| **Status** | ⏳ Placeholder — marked "Coming Soon" |
| **What it shows** | Globe icon, "Weekly Insight" title, hardcoded text: "Python demand ↑ 18% in Bangalore this week. React.js holding steady at #2 most requested skill." |
| **Understanding** | Would require a labor-market intelligence system on the backend that aggregates job posting trends by skill, location, and time period. No such system exists. |
| **What's needed from backend** | An endpoint like `GET /api/v1/dashboard/market-insights/` returning weekly trend summaries. |

---

### 18. Activity Streak ⏳ PLACEHOLDER

| Property | Detail |
|---|---|
| **Type** | KPI card with two metrics |
| **Data Source** | **`PLACEHOLDER_STREAK` constant** (hardcoded: `{ days: 7, thisMonth: 14 }`) |
| **Endpoint** | **None — no backend endpoint exists** |
| **Status** | ⏳ Placeholder — marked "Coming Soon" |
| **What it shows** | Fire icon, "Activity Streak" title, "7 day streak" and "14 this month" as large bold numbers. |
| **Understanding** | Would need the backend to track daily user activity (analyses, logins, profile updates, etc.) and compute consecutive-day streaks and monthly totals. |
| **What's needed from backend** | An endpoint like `GET /api/v1/dashboard/activity/` returning `{ streak_days, actions_this_month }`. |

---

### 19. Zero State (No Analyses)

| Property | Detail |
|---|---|
| **Type** | Full-page empty state |
| **Data Source** | Triggered when `stats.total_analyses === 0` |
| **Endpoint** | `GET /api/v1/dashboard/stats/` (when it returns 0 analyses) |
| **Status** | ✅ Live |
| **What it shows** | Chart icon, "No analyses yet" heading, descriptive text, "Run First Analysis" CTA button linking to `/analyze`. |

---

## Summary Table

| # | Widget | Data Source | Endpoint | Status |
|---|---|---|---|---|
| 1 | Credits Remaining | `user.wallet.balance` | `GET /auth/me/` | ✅ Live |
| 2 | Latest Score | `score_trend[0]` | `GET /dashboard/stats/` | ✅ Live |
| 3 | Quick Actions | Static links | N/A | ✅ Live |
| 4 | Recent Analyses | `score_trend[0:5]` | `GET /dashboard/stats/` | ✅ Live |
| 5 | Smart Job Alerts | Static link | N/A | ✅ Live |
| 6 | Score Trend Chart | `score_trend` | `GET /dashboard/stats/` | ✅ Live |
| 7 | Grade Distribution | `grade_distribution` | `GET /dashboard/stats/` | ✅ Live |
| 8 | Top Industries | `top_industries` | `GET /dashboard/stats/` | ✅ Live |
| 9 | Analysis Summary | `total/active/deleted` | `GET /dashboard/stats/` | ✅ Live |
| 10 | Analyses per Month | `analyses_per_month` | `GET /dashboard/stats/` | ✅ Live |
| 11 | Top Roles | `top_roles` | `GET /dashboard/stats/` | ✅ Live |
| 12 | Resume Health | Hardcoded text | **None** | ⏳ Placeholder |
| 13 | Benchmark | `industry_benchmark_percentile` | `GET /dashboard/stats/` | ✅ Live (fallback to 68) |
| 14 | Top Missing Keywords | `top_missing_keywords` | `GET /dashboard/stats/` | ✅ Live |
| 15 | Credit Usage | `credit_usage` | `GET /dashboard/stats/` | ✅ Live |
| 16 | Skill Gap Radar | `PLACEHOLDER_SKILL_GAP` | **None** | ⏳ Placeholder |
| 17 | Weekly Insight | Hardcoded text | **None** | ⏳ Placeholder |
| 18 | Activity Streak | `PLACEHOLDER_STREAK` | **None** | ⏳ Placeholder |
| 19 | Zero State | `total_analyses === 0` | `GET /dashboard/stats/` | ✅ Live |

---

## Removed Widgets (this update)

| Widget | Reason for Removal |
|---|---|
| **Application Tracker** (Applied/Interview/Offer/Rejected tiles) | No backend application tracking API. Was using `PLACEHOLDER_APP_TRACKER` with fake counts. Fully removed. |
| **Share Score CTA** (LinkedIn share card) | No share-token generation from dashboard. The shared-result flow exists only on individual result pages. Button had no functionality. Fully removed. |
