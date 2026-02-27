# Frontend–Backend Gap Analysis & Prioritized Backlog

> **Generated:** 2026-02-27 &nbsp;|&nbsp; **Backend version:** v0.21.0
> Items audited against the live codebase. P0/P1/P2 all implemented in v0.21.0. P3 items remain as TODO.

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

### P0 — Critical (Fake data visible to users)

| # | Item | Feasibility | Effort | Notes |
|---|------|-------------|--------|-------|
| 15 | **first_name / last_name writable on PUT /auth/me/** | Easy — add 2 fields to `UpdateUserSerializer` | **XS** | Frontend submits these but they silently revert on reload. Quick serializer fix. |
| 5/17 | **keyword_match_percent in score_trend** | Easy — extract from existing `scores` JSONField | **XS** | Data already in DB. Just add `keyword_match_percent` to the score_trend loop in `DashboardStatsView`. |
| 6/18 | **Aggregated top missing keywords** | Easy — aggregate from existing `keyword_analysis` JSONField | **S** | Data is per-analysis in `keyword_analysis.missing_keywords[]`. Aggregate top-N across recent analyses with `Counter`. |
| 7/19 | **Credit usage history (monthly)** | Easy — aggregate from `WalletTransaction` model | **S** | Group `WalletTransaction` by month for debit types. Add to dashboard stats response. |

> **Subtotal: 4 items, ~3 hours total**

---

### P1 — High (Core feature gaps)

| # | Item | Feasibility | Effort | Notes |
|---|------|-------------|--------|-------|
| 4 | **DELETE /generated-resumes/\<id\>/** | Easy — add detail view with destroy mixin | **S** | Model exists, just needs a `DestroyAPIView` route + user ownership check. Also delete file from R2. |
| 21 | **Server-side search/filter/sort on analyses** | Easy — add `django-filter` + `SearchFilter` + `OrderingFilter` to `AnalysisListView` | **S** | DRF has built-in filter backends. Add `?search=`, `?status=`, `?sort=`, `?score_min=`, `?score_max=`. |
| 22 | **Server-side search/filter/sort on resumes** | Easy — same pattern as #21 for `ResumeListView` | **XS** | Add `SearchFilter` on `original_filename` + `OrderingFilter`. |
| 27 | **Payment history pagination** | Easy — switch from manual `[:limit]` to DRF `PageNumberPagination` | **XS** | Replace the manual limit/slice in `PaymentHistoryView` with standard DRF pagination. |
| 20 | **Job alert total_matches count** | Easy — annotate queryset with `Count('matches')` | **XS** | Add `total_matches` annotation to `JobAlertListCreateView` queryset + serializer field. |
| 24 | **Bulk delete resumes** | Easy — same pattern as existing `AnalysisBulkDeleteView` | **S** | Accept `{ids: [...]}`, validate ownership, delete files from R2, cascade-check active analyses. |
| 13 | **Weekly job match count** | Moderate — aggregate `JobMatch` created in last 7 days | **S** | Add to dashboard stats or as a field on job alert serializer. `JobMatch.objects.filter(created_at__gte=7d).count()`. |

> **Subtotal: 7 items, ~8 hours total**

---

### P2 — Medium (Significant UX improvement)

| # | Item | Feasibility | Effort | Notes |
|---|------|-------------|--------|-------|
| 2 | **Social links (website/GitHub/LinkedIn)** | Easy — add 3 URLFields to `UserProfile` + expose in serializer | **S** | New fields on `UserProfile`, add to `UpdateUserSerializer`. Migration + tests. |
| 1 | **Avatar upload endpoint** | Moderate — change `avatar_url` from URLField to `ImageField`, add upload endpoint | **M** | Need: `ImageField` on UserProfile, upload view with size/type validation, R2 storage, `Pillow` for image processing. Keep URL fallback for Google OAuth. |
| 16 | **avatar_url writable** | Tied to #1 — depends on avatar upload approach | **—** | If #1 is implemented, this is included. If skipping #1, allow setting `avatar_url` as a writable URL field (easier, less safe). |
| 11 | **Resume health / staleness check** | Easy — compute from `Resume.uploaded_at` | **S** | Add `days_since_update` computed field to resume serializer. Frontend can show "Resume not updated in N days" from real data. Also add `last_analyzed_at` from most recent analysis. |
| 31 | **Dedicated comparison endpoint** | Moderate — new view returning 2+ analyses side-by-side | **M** | `GET /api/analyses/compare/?ids=1,2` — validate ownership, return both analyses in a structured diff-friendly format. Saves frontend from 2 separate API calls + loading all analyses for dropdown. |
| 32 | **Social share ("Share Score")** | Easy — share analysis already exists, just needs a lightweight score-only variant | **S** | Add a `GET /api/shared/<token>/summary/` returning only `{score, grade, role, name}` for social card preview. Or generate an OG-image URL. Existing share infra handles auth/tokens. |
| 30 | **Export wallet/transaction data (CSV)** | Easy — stream `WalletTransaction` as CSV | **S** | New `GET /api/auth/wallet/transactions/export/` that returns `text/csv`. Same pattern as GDPR export but wallet-only. |
| 12 | **Industry benchmark (percentile)** | Moderate — requires statistical computation across all users | **M** | Compute percentile rank of user's avg ATS score vs all users' scores. Cache result (expensive query). `PERCENT_RANK()` window function or Python computation. Privacy-safe since it's anonymous aggregation. |

> **Subtotal: 8 items, ~25 hours total**

---

### P3 — Low (Nice-to-have / Large effort)

| # | Item | Feasibility | Effort | Notes |
|---|------|-------------|--------|-------|
| 10 | **Activity streak** | Easy logic, but niche value | **S** | Count consecutive days with any analysis/generation activity from `ResumeAnalysis.created_at`. Add to dashboard stats. Gamification feature — nice but not critical. |
| 9 | **Skill gap analysis** | Moderate — aggregate keyword data, compare to market | **M** | Aggregate user's matched vs missing keywords across analyses. "Market demand" requires external data source or LLM-generated benchmark. Consider: use job alert discovered jobs as the demand signal instead of hardcoded data. |
| 3 | **Professional profile (skills/experience/education)** | Feasible but large scope | **L** | Needs new models (`Skill`, `Experience`, `Education`) or a JSON field on `UserProfile`. CRUD endpoints, serializers, admin. Consider: `JobSearchProfile` already extracts skills/titles from resume via LLM — could expose that as the "professional profile" instead of manual entry. |
| 14 | **Weekly market insight** | Hard — requires real market data pipeline | **L** | "Python demand ↑ 18%" needs trend data from job boards over time. Could derive from `DiscoveredJob` table (count skill mentions per week). Only meaningful with enough crawled data volume. |
| 8 | **Application tracker** | Feasible, large scope | **L** | New model: `Application(user, job, resume, status, applied_at, notes)` with status workflow (applied → phone_screen → interview → offer → rejected → withdrawn). CRUD endpoints, status transitions, dashboard counts. Consider: `JobMatch.user_feedback` already has `applied` status — could extend `JobMatch` instead of new model. |
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
