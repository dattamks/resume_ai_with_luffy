"""
Feed & analytics views.

Endpoints under ``/api/v1/feed/`` powering the in-app home/feed page
and under ``/api/v1/dashboard/`` for additional dashboard widgets.

All endpoints require authentication and use ``ReadOnlyThrottle``.
Heavy aggregations are cached in Redis for 15-60 minutes.
"""
import logging
from collections import Counter
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.throttles import ReadOnlyThrottle

from .models import (
    CoverLetter,
    DiscoveredJob,
    InterviewPrep,
    JobAlert,
    JobMatch,
    JobSearchProfile,
    Resume,
    ResumeAnalysis,
)
from .serializers_feed import (
    ActivitySerializer,
    FeedJobSerializer,
    HubSerializer,
    InsightsSerializer,
    RecommendationSerializer,
    SkillGapRadarItemSerializer,
    TrendingVsUserSerializer,
)

logger = logging.getLogger('analyzer')


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_user_skills(user) -> list[str]:
    """
    Return deduplicated lowercase skill list from the user's **default**
    resume's JobSearchProfile.  Falls back to ALL profiles if no default
    resume is set.
    """
    default_resume = Resume.get_default_for_user(user)
    if default_resume:
        profiles = JobSearchProfile.objects.filter(resume=default_resume)
    else:
        profiles = JobSearchProfile.objects.filter(resume__user=user)

    skills: set[str] = set()
    for p in profiles:
        for s in (p.skills or []):
            if isinstance(s, str) and s.strip():
                skills.add(s.strip().lower())
    return sorted(skills)


def _trending_skills_raw(days: int = 30, limit: int = 30) -> list[dict]:
    """
    Aggregate ``skills_required`` across recent DiscoveredJobs.
    Returns [{'skill': str, 'count': int}] sorted desc by count.
    """
    cache_key = f'feed:trending_skills_raw:{days}:{limit}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    since = timezone.now() - timedelta(days=days)
    jobs = DiscoveredJob.objects.filter(
        created_at__gte=since,
        skills_required__isnull=False,
    ).values_list('skills_required', flat=True)

    counter: Counter = Counter()
    for skill_list in jobs:
        if not isinstance(skill_list, list):
            continue
        for s in skill_list:
            if isinstance(s, str) and s.strip():
                counter[s.strip().lower()] += 1

    result = [{'skill': s, 'count': c} for s, c in counter.most_common(limit)]
    cache.set(cache_key, result, timeout=900)  # 15 min
    return result


def _prev_period_skills(days: int = 30, limit: int = 50) -> dict[str, int]:
    """Skills from the *previous* period for growth % calculation."""
    cache_key = f'feed:prev_skills:{days}:{limit}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    end = timezone.now() - timedelta(days=days)
    start = end - timedelta(days=days)
    jobs = DiscoveredJob.objects.filter(
        created_at__gte=start,
        created_at__lt=end,
        skills_required__isnull=False,
    ).values_list('skills_required', flat=True)

    counter: Counter = Counter()
    for skill_list in jobs:
        if not isinstance(skill_list, list):
            continue
        for s in skill_list:
            if isinstance(s, str) and s.strip():
                counter[s.strip().lower()] += 1

    result = dict(counter.most_common(limit))
    cache.set(cache_key, result, timeout=900)
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  GET /api/v1/feed/jobs/
# ═══════════════════════════════════════════════════════════════════════════

class FeedJobsView(APIView):
    """
    Personalised job feed ranked by pgvector embedding similarity
    against the user's ``JobSearchProfile``.

    Query params:
        - ``page``  (int, default 1)
        - ``page_size`` (int, default 20, max 50)
        - ``remote`` (onsite|hybrid|remote)
        - ``seniority`` (intern|junior|mid|senior|lead|…)
        - ``location`` (substring match)
        - ``employment_type`` (full_time|part_time|contract|…)
        - ``days`` (int, default 30 — how far back to look)

    Falls back to recency-ordered listing when pgvector is unavailable
    or the user has no embedding.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user = request.user

        # Parse pagination
        try:
            page = max(int(request.query_params.get('page', 1)), 1)
        except (ValueError, TypeError):
            page = 1
        try:
            page_size = min(max(int(request.query_params.get('page_size', 20)), 1), 50)
        except (ValueError, TypeError):
            page_size = 20

        offset = (page - 1) * page_size
        days = int(request.query_params.get('days', 30))

        # Base queryset — recent jobs
        since = timezone.now() - timedelta(days=days)
        qs = DiscoveredJob.objects.filter(created_at__gte=since)

        # Filters
        remote = request.query_params.get('remote')
        if remote:
            qs = qs.filter(remote_policy=remote)

        seniority = request.query_params.get('seniority')
        if seniority:
            qs = qs.filter(seniority_level=seniority)

        location = request.query_params.get('location')
        if location:
            qs = qs.filter(location__icontains=location)

        emp_type = request.query_params.get('employment_type')
        if emp_type:
            qs = qs.filter(employment_type=emp_type)

        # Try pgvector similarity ranking
        profile_embedding = self._get_user_embedding(user)
        if profile_embedding is not None:
            try:
                from pgvector.django import CosineDistance

                qs = (
                    qs.exclude(embedding__isnull=True)
                    .annotate(distance=CosineDistance('embedding', profile_embedding))
                    .order_by('distance')
                )

                total = qs.count()
                job_rows = list(qs[offset:offset + page_size])

                # Inject relevance as 1-distance (0-1 scale, rounded)
                for job in job_rows:
                    job.relevance = round(1.0 - job.distance, 4)

                serializer = FeedJobSerializer(job_rows, many=True)
                return Response({
                    'count': total,
                    'page': page,
                    'page_size': page_size,
                    'results': serializer.data,
                })
            except Exception:
                logger.debug('pgvector not available for feed — falling back to recency')

        # Fallback — recency order
        qs = qs.order_by('-created_at')
        total = qs.count()
        job_rows = list(qs[offset:offset + page_size])
        for job in job_rows:
            job.relevance = None

        serializer = FeedJobSerializer(job_rows, many=True)
        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'results': serializer.data,
        })

    @staticmethod
    def _get_user_embedding(user):
        """
        Return the embedding from the user's **default** resume's
        JobSearchProfile.  Falls back to the newest JSP embedding
        if no default resume is set.
        """
        default_resume = Resume.get_default_for_user(user)
        if default_resume:
            try:
                jsp = JobSearchProfile.objects.get(resume=default_resume)
                if hasattr(jsp, 'embedding') and jsp.embedding is not None:
                    return jsp.embedding
            except JobSearchProfile.DoesNotExist:
                pass

        # Fallback — newest embedding across all resumes
        profiles = JobSearchProfile.objects.filter(resume__user=user).order_by('-updated_at')
        for p in profiles:
            if hasattr(p, 'embedding') and p.embedding is not None:
                return p.embedding
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  GET /api/v1/feed/insights/
# ═══════════════════════════════════════════════════════════════════════════

class FeedInsightsView(APIView):
    """
    Career insights & market intelligence.

    Aggregates job data from the last 30 days:
    - Total jobs, average salary
    - Top skills, top companies, top locations
    - Employment-type / remote-policy / seniority breakdowns

    Cached for 60 minutes.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        cache_key = 'feed:insights:global'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        since = timezone.now() - timedelta(days=30)
        qs = DiscoveredJob.objects.filter(created_at__gte=since)

        total = qs.count()

        # Average salary (only jobs with salary data)
        avg_salary = qs.filter(
            salary_min_usd__isnull=False,
        ).aggregate(avg=Avg('salary_min_usd'))['avg']
        if avg_salary is not None:
            avg_salary = int(avg_salary)

        # Top skills
        user_skills = set(_get_user_skills(request.user))
        trending = _trending_skills_raw(days=30, limit=20)
        prev_skills = _prev_period_skills(days=30, limit=50)

        top_skills = []
        for item in trending:
            prev_count = prev_skills.get(item['skill'], 0)
            growth = (
                round((item['count'] - prev_count) / max(prev_count, 1) * 100, 1)
                if prev_count else 0.0
            )
            top_skills.append({
                'skill': item['skill'],
                'demand_count': item['count'],
                'growth_pct': growth,
                'you_have': item['skill'] in user_skills,
            })

        # Top companies
        top_companies = list(
            qs.filter(company__gt='')
            .values('company')
            .annotate(job_count=Count('id'))
            .order_by('-job_count')[:10]
        )

        # Top locations
        top_locations = list(
            qs.filter(location__gt='')
            .values('location')
            .annotate(job_count=Count('id'))
            .order_by('-job_count')[:10]
        )

        # Breakdowns
        emp_breakdown = dict(
            qs.filter(employment_type__gt='')
            .values_list('employment_type')
            .annotate(c=Count('id'))
            .order_by('-c')
        )
        remote_breakdown = dict(
            qs.filter(remote_policy__gt='')
            .values_list('remote_policy')
            .annotate(c=Count('id'))
            .order_by('-c')
        )
        seniority_breakdown = dict(
            qs.filter(seniority_level__gt='')
            .values_list('seniority_level')
            .annotate(c=Count('id'))
            .order_by('-c')
        )

        data = {
            'total_jobs_last_30d': total,
            'avg_salary_usd': avg_salary,
            'top_skills': top_skills,
            'top_companies': top_companies,
            'top_locations': top_locations,
            'employment_type_breakdown': emp_breakdown,
            'remote_policy_breakdown': remote_breakdown,
            'seniority_breakdown': seniority_breakdown,
        }

        cache.set(cache_key, data, timeout=3600)  # 60 min
        return Response(data)


# ═══════════════════════════════════════════════════════════════════════════
#  GET /api/v1/feed/trending-skills/
# ═══════════════════════════════════════════════════════════════════════════

class FeedTrendingSkillsView(APIView):
    """
    Compare the user's skills against market demand.

    Returns three buckets:
    - ``matches``: skills the user has that are in demand
    - ``gaps``: in-demand skills the user is missing
    - ``niche``: skills the user has that aren't trending

    Plus ``match_pct``: percentage of top trending skills the user has.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user_skills = set(_get_user_skills(request.user))
        trending = _trending_skills_raw(days=30, limit=30)
        trending_set = {t['skill'] for t in trending}
        trending_map = {t['skill']: t['count'] for t in trending}

        matches = []
        gaps = []
        for item in trending:
            entry = {
                'skill': item['skill'],
                'demand_count': item['count'],
                'you_have': item['skill'] in user_skills,
                'category': 'match' if item['skill'] in user_skills else 'gap',
            }
            if item['skill'] in user_skills:
                matches.append(entry)
            else:
                gaps.append(entry)

        # Niche — user skills that aren't trending
        niche = [
            {
                'skill': s,
                'demand_count': trending_map.get(s, 0),
                'you_have': True,
                'category': 'niche',
            }
            for s in sorted(user_skills - trending_set)
        ]

        match_pct = round(len(matches) / max(len(trending), 1) * 100, 1)

        data = {
            'matches': matches,
            'gaps': gaps,
            'niche': niche,
            'match_pct': match_pct,
        }
        return Response(data)


# ═══════════════════════════════════════════════════════════════════════════
#  GET /api/v1/feed/hub/
# ═══════════════════════════════════════════════════════════════════════════

class FeedHubView(APIView):
    """
    Composite endpoint returning the user's active alerts, recent
    interview preps, and recent cover letters in a single response.

    Includes per-alert health indicator:
    - ``ok``: ≥1 match in the last 7 days
    - ``quiet``: 0 matches in the last 7 days (suggest broadening)
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user = request.user
        one_week_ago = timezone.now() - timedelta(days=7)

        # Alerts with match counts
        alerts = list(
            JobAlert.objects.filter(user=user, is_active=True)
            .select_related('resume')
            .order_by('-created_at')
        )
        for alert in alerts:
            week_matches = JobMatch.objects.filter(
                job_alert=alert,
                created_at__gte=one_week_ago,
            ).count()
            alert.matches_this_week = week_matches
            alert.health = 'ok' if week_matches > 0 else 'quiet'

        # Recent interview preps (last 10)
        preps = list(
            InterviewPrep.objects.filter(user=user)
            .select_related('analysis')
            .order_by('-created_at')[:10]
        )

        # Recent cover letters (last 10)
        letters = list(
            CoverLetter.objects.filter(user=user)
            .select_related('analysis')
            .order_by('-created_at')[:10]
        )

        data = HubSerializer({
            'alerts': alerts,
            'interview_preps': preps,
            'cover_letters': letters,
        }).data

        return Response(data)


# ═══════════════════════════════════════════════════════════════════════════
#  GET /api/v1/feed/recommendations/
# ═══════════════════════════════════════════════════════════════════════════

class FeedRecommendationsView(APIView):
    """
    AI-suggested next actions based on the user's current state.

    Rules-based (not LLM) for speed — checks what the user has/hasn't
    done and generates prioritised action cards.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user = request.user
        recs = []

        from .models import Resume, ResumeChat

        # 1. Has resume?
        has_resume = Resume.objects.filter(user=user).exists()
        recs.append({
            'key': 'upload_resume',
            'title': 'Upload your resume',
            'description': 'Upload a resume to unlock analysis, job matching, and interview prep.',
            'priority': 'high',
            'action_url': '/resumes/upload',
            'completed': has_resume,
        })

        # 2. Has analysis?
        has_analysis = ResumeAnalysis.objects.filter(
            user=user, status='done', deleted_at__isnull=True,
        ).exists()
        recs.append({
            'key': 'run_analysis',
            'title': 'Analyse your resume',
            'description': 'Get ATS scores, keyword gaps, and improvement suggestions.',
            'priority': 'high',
            'action_url': '/analyze',
            'completed': has_analysis,
        })

        # 3. Has job alert?
        has_alert = JobAlert.objects.filter(user=user, is_active=True).exists()
        recs.append({
            'key': 'create_alert',
            'title': 'Set up a job alert',
            'description': 'Get notified when new jobs match your profile.',
            'priority': 'medium',
            'action_url': '/job-alerts/create',
            'completed': has_alert,
        })

        # 4. Has interview prep?
        has_prep = InterviewPrep.objects.filter(user=user, status='done').exists()
        recs.append({
            'key': 'interview_prep',
            'title': 'Prepare for interviews',
            'description': 'Generate role-specific interview questions and sample answers.',
            'priority': 'medium',
            'action_url': '/interview-prep',
            'completed': has_prep,
        })

        # 5. Has cover letter?
        has_letter = CoverLetter.objects.filter(user=user, status='done').exists()
        recs.append({
            'key': 'cover_letter',
            'title': 'Generate a cover letter',
            'description': 'Create a tailored cover letter for your target role.',
            'priority': 'medium',
            'action_url': '/cover-letters',
            'completed': has_letter,
        })

        # 6. Has used chat?
        has_chat = ResumeChat.objects.filter(user=user).exists()
        recs.append({
            'key': 'resume_chat',
            'title': 'Chat with your resume',
            'description': 'Ask questions about your resume — strengths, gaps, rewrite suggestions.',
            'priority': 'low',
            'action_url': '/resume-chat',
            'completed': has_chat,
        })

        # 7. Skill gaps (only if user has skills + trending data available)
        user_skills = set(_get_user_skills(user))
        if user_skills:
            trending = _trending_skills_raw(days=30, limit=20)
            trending_set = {t['skill'] for t in trending}
            gaps = trending_set - user_skills
            if gaps:
                top_gaps = sorted(gaps)[:3]
                recs.append({
                    'key': 'skill_gaps',
                    'title': 'Close your skill gaps',
                    'description': f'Top in-demand skills you\'re missing: {", ".join(top_gaps)}.',
                    'priority': 'medium',
                    'action_url': '/feed/trending-skills',
                    'completed': False,
                })

        # Sort: incomplete first, then by priority
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        recs.sort(key=lambda r: (r['completed'], priority_order.get(r['priority'], 9)))

        serializer = RecommendationSerializer(recs, many=True)
        return Response(serializer.data)


# ═══════════════════════════════════════════════════════════════════════════
#  GET /api/v1/feed/onboarding/
# ═══════════════════════════════════════════════════════════════════════════

class FeedOnboardingView(APIView):
    """
    User completion checklist + suggested next step.
    Lightweight — no heavy aggregations.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user = request.user

        from .models import Resume, ResumeChat

        checklist = {
            'has_resume': Resume.objects.filter(user=user).exists(),
            'has_analysis': ResumeAnalysis.objects.filter(
                user=user, status='done', deleted_at__isnull=True,
            ).exists(),
            'has_alert': JobAlert.objects.filter(user=user, is_active=True).exists(),
            'has_interview_prep': InterviewPrep.objects.filter(user=user, status='done').exists(),
            'has_cover_letter': CoverLetter.objects.filter(user=user, status='done').exists(),
            'has_chat': ResumeChat.objects.filter(user=user).exists(),
        }

        # Suggest next step
        if not checklist['has_resume']:
            suggested_next = 'upload_resume'
        elif not checklist['has_analysis']:
            suggested_next = 'run_analysis'
        elif not checklist['has_alert']:
            suggested_next = 'create_alert'
        elif not checklist['has_interview_prep']:
            suggested_next = 'interview_prep'
        elif not checklist['has_cover_letter']:
            suggested_next = 'cover_letter'
        elif not checklist['has_chat']:
            suggested_next = 'resume_chat'
        else:
            suggested_next = None

        completed_count = sum(1 for v in checklist.values() if v)
        total_steps = len(checklist)

        return Response({
            **checklist,
            'completed_count': completed_count,
            'total_steps': total_steps,
            'completion_pct': round(completed_count / total_steps * 100, 1),
            'suggested_next': suggested_next,
        })


# ═══════════════════════════════════════════════════════════════════════════
#  Dashboard extras
# ═══════════════════════════════════════════════════════════════════════════

class DashboardSkillGapView(APIView):
    """
    GET /api/v1/dashboard/skill-gap/

    Returns ``[{skill, user_score, market_score}]`` for a radar chart.
    User score = 100 if skill is in their profile, 0 otherwise.
    Market score = normalised demand (0-100).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user_skills = set(_get_user_skills(request.user))
        trending = _trending_skills_raw(days=30, limit=12)

        if not trending:
            return Response([])

        max_demand = max(t['count'] for t in trending)

        # Build radar data — use trending skills + any user skills not in trending
        items = []
        seen = set()
        for t in trending:
            market_score = int(t['count'] / max(max_demand, 1) * 100)
            items.append({
                'skill': t['skill'],
                'user_score': 100 if t['skill'] in user_skills else 0,
                'market_score': market_score,
            })
            seen.add(t['skill'])

        # Add top user skills not in trending (max 4 extra)
        for s in sorted(user_skills - seen)[:4]:
            items.append({
                'skill': s,
                'user_score': 100,
                'market_score': 0,
            })

        serializer = SkillGapRadarItemSerializer(items, many=True)
        return Response(serializer.data)


class DashboardMarketInsightsView(APIView):
    """
    GET /api/v1/dashboard/market-insights/

    Weekly insight widget — a short summary of market trends.
    Returns structured data the frontend can render as a card.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        cache_key = 'dashboard:market_insights'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        now = timezone.now()
        this_week = now - timedelta(days=7)
        last_week_start = now - timedelta(days=14)

        this_week_count = DiscoveredJob.objects.filter(created_at__gte=this_week).count()
        last_week_count = DiscoveredJob.objects.filter(
            created_at__gte=last_week_start,
            created_at__lt=this_week,
        ).count()

        growth = (
            round((this_week_count - last_week_count) / max(last_week_count, 1) * 100, 1)
            if last_week_count else 0.0
        )

        trending = _trending_skills_raw(days=7, limit=5)
        top_skill = trending[0]['skill'] if trending else None

        data = {
            'jobs_this_week': this_week_count,
            'jobs_last_week': last_week_count,
            'growth_pct': growth,
            'trend': 'up' if growth > 0 else ('down' if growth < 0 else 'flat'),
            'top_skill_this_week': top_skill,
            'top_skills': trending,
        }

        cache.set(cache_key, data, timeout=3600)  # 60 min
        return Response(data)


class DashboardActivityView(APIView):
    """
    GET /api/v1/dashboard/activity/

    Activity streak and actions this month.
    Uses ``UserActivity.get_streak()`` which already exists.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        from .models import UserActivity

        streak_days, actions_this_month = UserActivity.get_streak(request.user)
        data = {
            'streak_days': streak_days,
            'actions_this_month': actions_this_month,
        }
        serializer = ActivitySerializer(data)
        return Response(serializer.data)
