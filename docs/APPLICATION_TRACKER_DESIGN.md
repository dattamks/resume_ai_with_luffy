# Design Proposal — Job Application Tracker

> **Status:** DRAFT for approval. No code has been written. This documents the
> proposed model, API, and UX so it can be signed off before implementation.

## 1. Why

The platform matches users to jobs (feed + alerts) but has no way for a user to
**track what they've applied to**. Since we do **not** offer in-platform
applying (users apply on the employer/job-board site), tracking is **manual
entry** — the product value is a lightweight personal pipeline ("where am I with
each application?"), not an automated ATS.

This closes the loop after discovery and is a natural **retention** feature: a
reason to come back daily.

## 2. Scope (intentionally small for v1)

In scope:
- Log an application (from a feed job, or fully manual entry).
- Move it through a simple status pipeline.
- See everything on one board/list, filter by status.
- Optional reminder date for the next action.

Out of scope for v1 (revisit later):
- Auto-detecting applications (email parsing, browser extension).
- Interview scheduling / calendar sync.
- Document attachments per application.

## 3. Data model

New model `JobApplication` in the `analyzer` app:

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigAuto / UUID | consistent with existing models |
| `user` | FK → User (CASCADE) | owner |
| `discovered_job` | FK → DiscoveredJob (SET_NULL, null) | set when logged from the feed; else null |
| `company` | Char(200) | required (prefilled from `discovered_job` if present) |
| `role` | Char(200) | required |
| `job_url` | URL(1000), blank | link the user applied through |
| `location` | Char(200), blank | |
| `source` | Char(100), blank | e.g. "LinkedIn", "Company site", "Referral" |
| `status` | Char(20), choices | see pipeline below; default `saved` |
| `applied_at` | Date, null | when they applied (null while `saved`) |
| `next_action_date` | Date, null | optional reminder |
| `notes` | Text, blank | free-form |
| `created_at` / `updated_at` | DateTime | auto |

**Status pipeline** (`status` choices):
`saved → applied → interviewing → offer → {accepted | rejected | withdrawn}`

- Transitions are not enforced server-side in v1 (any → any) to keep it simple;
  the UI presents them in order.
- Setting status to `applied` auto-stamps `applied_at` if empty.

Indexes: `(user, status)`, `(user, -updated_at)`, `(user, next_action_date)`.

Ownership: every query filtered by `request.user` (same pattern as the rest of
the app). One application per `(user, discovered_job)` is **not** enforced — a
user may legitimately track re-applications; dedup is a UI nicety, not a
constraint.

## 4. Credits

**Free.** Tracking is manual data entry with no LLM/AI cost, so it does not
touch the credit system. (Consistent with the "every *LLM* call is metered"
rule — there is no LLM call here.)

## 5. API (`/api/v1/applications/`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/applications/` | List the user's applications. `?status=` filter, `?ordering=`; paginated. |
| POST | `/applications/` | Create (manual, or with `discovered_job` id to prefill). |
| GET | `/applications/<id>/` | Detail. |
| PATCH | `/applications/<id>/` | Update fields / change status. |
| DELETE | `/applications/<id>/` | Remove. |
| GET | `/applications/board/` | Same data grouped by status: `{ saved: [...], applied: [...], ... }` for a Kanban view. |
| GET | `/applications/stats/` | Counts per status + count with `next_action_date` due (for a dashboard tile). |

Throttling: `WriteThrottle` on mutations, `ReadOnlyThrottle` on reads (existing
classes). Requires `IsAuthenticated` (not the email-verified gate — it's free
and low-risk).

Optional integration: a "Log application" affordance on a feed job POSTs with
`discovered_job=<id>`; the serializer prefills `company`, `role`, `job_url`,
`location` from that job. Users can also create a blank one and type everything.

## 6. UX sketch (for the mobile app / web)

- **Primary view:** a **status board** (columns: Saved · Applied · Interviewing
  · Offer · Closed) — tap a card to edit, tap the status chip to advance. On
  small screens this collapses to a **filterable list** grouped by status.
- **Add:** floating "＋ Log application" → form (company, role, url, source,
  status, applied date, reminder, notes). From a feed job, the same form opens
  prefilled.
- **Reminders:** if `next_action_date` is today/overdue, surface a badge and
  (optionally) reuse the existing notification system to send a nudge — this
  would be a small Celery beat task; **flagged as a follow-up**, not v1-core.
- **Dashboard tile:** "Applications: 3 interviewing · 1 offer · 2 follow-ups
  due" linking into the board.

## 7. Rollout / effort estimate

1. Model + migration + serializer + viewset + URL wiring — small.
2. `board/` and `stats/` aggregation endpoints — small.
3. Tests (ownership, status filter, prefill-from-job, stats) — small.
4. (Follow-up) reminder Celery task + notification wiring.
5. (Frontend/mobile) board + form — separate repos.

**Backend is ~1 focused change.** Requesting approval on: the field set, the
status pipeline, and whether reminders are in v1 or deferred.
