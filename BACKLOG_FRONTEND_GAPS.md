# Frontend–Backend Gap Analysis & Prioritized Backlog

> **Generated:** 2026-02-27 &nbsp;|&nbsp; **Updated:** 2026-03-03 &nbsp;|&nbsp; **Backend version:** v0.35.0
> All P0, P1, and P2 items are now **implemented**. P3 items remain as backlog.

---

## Already Exists — No Work Needed (4 items)

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 23 | Bulk delete analyses | ✅ ALREADY EXISTS | `POST /api/analyses/bulk-delete/` — added in v0.19.0 |
| 25 | Job alerts pagination | ✅ ALREADY EXISTS | `GET /api/job-alerts/` uses `PageNumberPagination` — added in v0.18.0 |
| 26 | Generated resumes pagination | ✅ ALREADY EXISTS | `GET /api/generated-resumes/` uses `PageNumberPagination` — added in v0.18.0 |
| 29 | Resume regeneration with template/format | ✅ ALREADY EXISTS | `POST /api/analyses/<id>/generate-resume/` accepts `template` + `format` params |

**Frontend action:** Update frontend code to use these existing endpoints instead of showing placeholders.

---

## Deduplicated Items

Items 6 & 18 are the same (aggregated missing keywords). Items 7 & 19 are the same (credit usage per month). Counted once below.

---

## Prioritized Backlog — 28 Unique Items

### Priority Definitions
- **P0 (Critical):** Users see broken/fake data; data loss risk; security issue
- **P1 (High):** Core feature gap blocking real usage; straightforward to implement
- **P2 (Medium):** Improves UX significantly; moderate effort
- **P3 (Low):** Nice-to-have; large effort or niche audience

### Effort Definitions
- **XS:** < 1 hour (add a field, tweak a serializer)
- **S:** 1–3 hours (new endpoint, simple service logic)
- **M:** 3–8 hours (new model + endpoints + tests)
- **L:** 1–2 days (multi-model feature, complex logic)
- **XL:** 2+ days (new infrastructure, external integrations)

---

### P0 — Critical ✅ ALL DONE

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 15 | **first_name / last_name writable on PUT /auth/me/** | ✅ DONE | `UpdateUserSerializer` includes `first_name`, `last_name` in fields |
| 5/17 | **keyword_match_percent in score_trend** | ✅ DONE | `DashboardStatsView` extracts `scores.get('keyword_match_percent')` into each `score_trend` item |
| 6/18 | **Aggregated top missing keywords** | ✅ DONE | Aggregated via `Counter` from last 20 analyses, returned as `top_missing_keywords` (top 10) |
| 7/19 | **Credit usage history (monthly)** | ✅ DONE | `WalletTransaction` grouped by month and type via ORM, returned as `credit_usage` |

---

### P1 — High ✅ ALL DONE

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 4 | **DELETE /generated-resumes/\<id\>/** | ✅ DONE | `GeneratedResumeDeleteView` in `views.py`, routed in `urls.py` |
| 21 | **Server-side search/filter/sort on analyses** | ✅ DONE | `AnalysisListView` has `SearchFilter` + `OrderingFilter` backends |
| 22 | **Server-side search/filter/sort on resumes** | ✅ DONE | `ResumeListView` has `SearchFilter` + `OrderingFilter` backends |
| 27 | **Payment history pagination** | ✅ DONE | `PaymentHistoryView` uses `PageNumberPagination` with `page_size=20` |
| 20 | **Job alert total_matches count** | ✅ DONE | `JobAlertSerializer.total_matches` via `SerializerMethodField`, queryset annotated with `Count('matches')` |
| 24 | **Bulk delete resumes** | ✅ DONE | `ResumeBulkDeleteView` at `POST /resumes/bulk-delete/` |
| 13 | **Weekly job match count** | ✅ DONE | `weekly_job_matches` in `DashboardStatsView` filters last 7 days |

---

### P2 — Medium ✅ ALL DONE

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 2 | **Social links (website/GitHub/LinkedIn)** | ✅ DONE | `UserProfile` has `website_url`, `github_url`, `linkedin_url` fields, exposed in `UpdateUserSerializer` |
| 1 | **Avatar upload endpoint** | ✅ DONE | `AvatarUploadView` at `POST /auth/avatar/`, validates JPEG/PNG/WebP, max 2 MB, R2 storage |
| 16 | **avatar_url writable** | ✅ DONE | Included in avatar upload implementation |
| 11 | **Resume health / staleness check** | ✅ DONE | `ResumeSerializer` has `days_since_upload` + `last_analyzed_at` computed fields |
| 31 | **Dedicated comparison endpoint** | ✅ DONE | `AnalysisCompareView` at `GET /analyses/compare/?ids=`, supports 2–5 analyses |
| 32 | **Social share ("Share Score")** | ✅ DONE | `SharedAnalysisSummaryView` at `GET /shared/<token>/summary/` for social card previews |
| 30 | **Export wallet/transaction data (CSV)** | ✅ DONE | `WalletTransactionExportView` at `GET /auth/wallet/transactions/export/`, returns `text/csv` |
| 12 | **Industry benchmark (percentile)** | ✅ DONE | Percentile rank computed in `DashboardStatsView`, returned as `industry_benchmark_percentile` |

---

### P3 — Low (Nice-to-have / Large effort)

| # | Item | Feasibility | Effort | Notes |
|---|------|-------------|--------|-------|
| 10 | **Activity streak** | Easy logic, but niche value | **S** | Count consecutive days with any analysis/generation activity from `ResumeAnalysis.created_at`. Add to dashboard stats. Gamification feature — nice but not critical. |
| 9 | **Skill gap analysis** | Moderate — aggregate keyword data, compare to market | **M** | Aggregate user's matched vs missing keywords across analyses. "Market demand" requires external data source or LLM-generated benchmark. Consider: use job alert discovered jobs as the demand signal instead of hardcoded data. |
| 3 | **Professional profile (skills/experience/education)** | Feasible but large scope | **L** | Needs new models (`Skill`, `Experience`, `Education`) or a JSON field on `UserProfile`. CRUD endpoints, serializers, admin. Consider: `JobSearchProfile` already extracts skills/titles from resume via LLM — could expose that as the "professional profile" instead of manual entry. |
| 14 | **Weekly market insight** | Hard — requires real market data pipeline | **L** | "Python demand ↑ 18%" needs trend data from job boards over time. Could derive from `DiscoveredJob` table (count skill mentions per week). Only meaningful with enough crawled data volume. |
| 8 | **Application tracker** | Feasible, large scope | **L** | New model: `Application(user, job, resume, status, applied_at, notes)` with status workflow (applied → phone_screen → interview → offer → rejected → withdrawn). CRUD endpoints, status transitions, dashboard counts. Consider: `JobMatch.user_feedback` already has `applied` status — could extend `JobMatch` instead of new model. |
| 33 | **Resume rename / display name** | Easy — add `display_name` field + PATCH endpoint | **S** | Neither uploaded nor generated resumes support renaming. Add `display_name` CharField to `Resume` and `GeneratedResume`, new PATCH endpoints, update list serializers. See `backend_todo.md` for 30 test cases. |
| 28 | **Push / in-app real-time notifications** | Hard — new infrastructure | **XL** | In-app notification model + endpoints already exist (polling). Push requires: Firebase Cloud Messaging setup, device token registration, FCM send on notification creation. WebSocket/SSE for real-time would need Django Channels + Redis pub/sub. Recommend: defer until mobile app is active. |

> **Subtotal: 6 items, ~40+ hours total**

---

## Recommended Implementation Order

### Sprint 1 — Quick Wins (P0 + easy P1) — ~6 hours
1. `first_name` / `last_name` writable (#15) — **XS**
2. `keyword_match_percent` in score_trend (#5/17) — **XS**
3. Payment history pagination (#27) — **XS**
4. Job alert `total_matches` (#20) — **XS**
5. Search/filter/sort on resumes (#22) — **XS**
6. Aggregated missing keywords (#6/18) — **S**
7. Credit usage history (#7/19) — **S**

### Sprint 2 — Core Gaps (remaining P1) — ~5 hours
8. DELETE generated-resume (#4) — **S**
9. Search/filter/sort on analyses (#21) — **S**
10. Bulk delete resumes (#24) — **S**
11. Weekly job match count (#13) — **S**

### Sprint 3 — UX Polish (P2) — ~25 hours
12. Social links (#2) — **S**
13. Resume staleness (#11) — **S**
14. Share score summary (#32) — **S**
15. Export wallet CSV (#30) — **S**
16. Avatar upload (#1 + #16) — **M**
17. Comparison endpoint (#31) — **M**
18. Industry benchmark (#12) — **M**

### Sprint 4 — Enhancements (P3) — as capacity allows
19. Activity streak (#10) — **S**
20. Skill gap analysis (#9) — **M**
21. Professional profile (#3) — **L** (consider reusing `JobSearchProfile`)
22. Weekly market insight (#14) — **L** (derive from `DiscoveredJob` data)
23. Application tracker (#8) — **L** (consider extending `JobMatch`)
24. Push notifications (#28) — **XL** (defer until mobile app ships)

---

## Optimization Notes for Our Project

1. **#3 (Professional profile):** Don't build from scratch. `JobSearchProfile` already extracts skills, titles, seniority, industries from resumes via LLM. Expose `GET /api/job-search-profile/` as the professional profile read endpoint. Only add manual override fields if users request it.

2. **#8 (Application tracker):** Don't create a new `Application` model. Extend `JobMatch.user_feedback` choices to include `phone_screen`, `interview`, `offer`, `rejected`, `withdrawn`. Add `status_updated_at` field. This reuses existing infrastructure.

3. **#9 (Skill gap):** Use `DiscoveredJob` data as the "market demand" signal. Count skill mentions across discovered jobs vs user's matched skills from analyses. No external data source needed.

4. **#14 (Market insight):** Same as #9 — derive trends from `DiscoveredJob` weekly counts. Only useful once we have enough crawl volume (100+ jobs/week).

5. **#28 (Push notifications):** Polling via `GET /api/notifications/unread-count/` is sufficient for web. Push should wait until the React Native mobile app has active users. Firebase setup is wasted effort with 0 mobile users.

6. **#12 (Industry benchmark):** Use `PERCENT_RANK()` PostgreSQL window function for efficient percentile calculation. Cache for 24 hours since it's a cross-user aggregate. Safe for privacy (no individual data exposed).
