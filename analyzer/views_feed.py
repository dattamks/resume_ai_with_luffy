"""
Feed & analytics views.

Endpoints under ``/api/v1/feed/`` powering the in-app home/feed page
and under ``/api/v1/dashboard/`` for additional dashboard widgets.

All endpoints require authentication and use ``ReadOnlyThrottle``.
Heavy aggregations are cached in Redis for 15-60 minutes.

Geography filtering:
    The user's ``profile.country`` (default "India") is used as the base
    geo filter.  Feed and analytics endpoints prioritise jobs in the
    user's country, falling back to global results when insufficient
    local data exists.
"""
import logging
from collections import Counter
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Avg, Case, Count, IntegerField, Q, Value, When
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

# ── India location heuristics ────────────────────────────────────────────
# Used to infer country='India' from free-text location strings when the
# crawler hasn't set the country field explicitly.
_INDIA_KEYWORDS = {
    'india', 'bangalore', 'bengaluru', 'mumbai', 'delhi', 'ncr',
    'hyderabad', 'pune', 'chennai', 'kolkata', 'noida', 'gurgaon',
    'gurugram', 'ahmedabad', 'jaipur', 'lucknow', 'chandigarh',
    'thiruvananthapuram', 'kochi', 'indore', 'bhopal', 'coimbatore',
    'nagpur', 'visakhapatnam', 'mysore', 'mysuru', 'navi mumbai',
    'greater noida', 'faridabad', 'ghaziabad',
}


def _is_india_location(location: str) -> bool:
    """Quick heuristic: does the free-text location mention an Indian city?"""
    low = location.lower()
    return any(kw in low for kw in _INDIA_KEYWORDS)


def _get_user_country(user) -> str:
    """Return the user's profile country, default 'India'."""
    profile = getattr(user, 'profile', None)
    if profile and profile.country:
        return profile.country
    return 'India'


def _filter_by_country(qs, country: str):
    """
    Filter a DiscoveredJob queryset to jobs in the given country.

    Matches on the structured ``country`` field first. For India,
    also includes jobs whose free-text ``location`` contains known
    Indian city names (for legacy data without country set).
    """
    country_q = Q(country__iexact=country)
    if country.lower() == 'india':
        # Also match location strings mentioning Indian cities
        india_q = Q()
        for kw in _INDIA_KEYWORDS:
            india_q |= Q(location__icontains=kw)
        country_q |= india_q
    return qs.filter(country_q)


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


def _trending_skills_raw(days: int = 30, limit: int = 30, country: str = '') -> list[dict]:
    """
    Aggregate ``skills_required`` across recent DiscoveredJobs.
    Returns [{'skill': str, 'count': int}] sorted desc by count.

    If ``country`` is given, only considers jobs in that country
    (by ``country`` field or location heuristic for India).
    """
    cache_key = f'feed:trending_skills_raw:{days}:{limit}:{country}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    since = timezone.now() - timedelta(days=days)
    qs = DiscoveredJob.objects.filter(
        created_at__gte=since,
        skills_required__isnull=False,
    )
    if country:
        qs = _filter_by_country(qs, country)

    jobs = qs.values_list('skills_required', flat=True)

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


def _prev_period_skills(days: int = 30, limit: int = 50, country: str = '') -> dict[str, int]:
    """Skills from the *previous* period for growth % calculation."""
    cache_key = f'feed:prev_skills:{days}:{limit}:{country}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    end = timezone.now() - timedelta(days=days)
    start = end - timedelta(days=days)
    qs = DiscoveredJob.objects.filter(
        created_at__gte=start,
        created_at__lt=end,
        skills_required__isnull=False,
    )
    if country:
        qs = _filter_by_country(qs, country)

    jobs = qs.values_list('skills_required', flat=True)

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

    **Geography-aware**: by default, jobs in the user's country
    (from ``profile.country``, default India) are shown first.
    Non-local jobs appear only after local results or when the user
    explicitly filters for another country.

    Query params:
        - ``page``  (int, default 1)
        - ``page_size`` (int, default 20, max 50)
        - ``search`` (free-text search across title, company, skills, location)
        - ``country`` (exact country filter — overrides profile default)
        - ``remote`` (onsite|hybrid|remote)
        - ``seniority`` (intern|junior|mid|senior|lead|…)
        - ``location`` (substring match on location field)
        - ``employment_type`` (full_time|part_time|contract|…)
        - ``industry`` (substring match)
        - ``skills`` (comma-separated skill keywords)
        - ``salary_min`` (int, minimum salary USD filter)
        - ``days`` (int, default 30 — how far back to look)
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

        # ── Filters ──────────────────────────────────────────────────

        # Country filter: explicit param > user's profile country
        country_param = request.query_params.get('country', '').strip()
        user_country = _get_user_country(user)
        filter_country = country_param or user_country

        # If no explicit country param was passed, we do India-first
        # ordering rather than strict filtering (so global jobs still
        # appear after local ones).
        strict_country_filter = bool(country_param)

        if strict_country_filter:
            qs = _filter_by_country(qs, filter_country)

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

        industry = request.query_params.get('industry')
        if industry:
            qs = qs.filter(industry__icontains=industry)

        skills_param = request.query_params.get('skills', '').strip()
        if skills_param:
            for skill in skills_param.split(','):
                skill = skill.strip()
                if skill:
                    qs = qs.filter(skills_required__icontains=skill)

        salary_min = request.query_params.get('salary_min')
        if salary_min:
            try:
                qs = qs.filter(salary_min_usd__gte=int(salary_min))
            except (ValueError, TypeError):
                pass

        # ── Search (free-text) ───────────────────────────────────────
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(company__icontains=search)
                | Q(location__icontains=search)
                | Q(skills_required__icontains=search)
                | Q(industry__icontains=search)
            )

        # ── Geo-priority annotation ─────────────────────────────────
        # When no strict country filter is applied, annotate a
        # ``geo_priority`` field: 0 = user's country, 1 = other.
        # This is used as the primary sort key so local jobs come first.
        if not strict_country_filter:
            geo_q = Q(country__iexact=filter_country)
            if filter_country.lower() == 'india':
                for kw in _INDIA_KEYWORDS:
                    geo_q |= Q(location__icontains=kw)
            qs = qs.annotate(
                geo_priority=Case(
                    When(geo_q, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
            )

        # ── Ranking ──────────────────────────────────────────────────
        profile_embedding = self._get_user_embedding(user)
        if profile_embedding is not None:
            try:
                from pgvector.django import CosineDistance

                qs = (
                    qs.exclude(embedding__isnull=True)
                    .annotate(distance=CosineDistance('embedding', profile_embedding))
                )

                if strict_country_filter:
                    qs = qs.order_by('distance')
                else:
                    qs = qs.order_by('geo_priority', 'distance')

                total = qs.count()
                job_rows = list(qs[offset:offset + page_size])

                for job in job_rows:
                    job.relevance = round(1.0 - job.distance, 4)

                serializer = FeedJobSerializer(job_rows, many=True)
                return Response({
                    'count': total,
                    'page': page,
                    'page_size': page_size,
                    'country': filter_country,
                    'results': serializer.data,
                })
            except Exception:
                logger.debug('pgvector not available for feed — falling back to recency')

        # Fallback — recency order with geo priority
        if strict_country_filter:
            qs = qs.order_by('-created_at')
        else:
            qs = qs.order_by('geo_priority', '-created_at')

        total = qs.count()
        job_rows = list(qs[offset:offset + page_size])
        for job in job_rows:
            job.relevance = None

        serializer = FeedJobSerializer(job_rows, many=True)
        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'country': filter_country,
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

    Geography-aware: scoped to the user's country by default.
    Pass ``?country=`` to filter for a specific country, or
    ``?country=all`` to see global data.

    Cached per-country for 60 minutes.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        country_param = request.query_params.get('country', '').strip()
        user_country = _get_user_country(request.user)
        country = country_param if country_param else user_country
        is_global = country.lower() == 'all'

        cache_key = f'feed:insights:{country.lower()}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        since = timezone.now() - timedelta(days=30)
        qs = DiscoveredJob.objects.filter(created_at__gte=since)
        if not is_global:
            qs = _filter_by_country(qs, country)

        total = qs.count()

        # Average salary (only jobs with salary data)
        avg_salary = qs.filter(
            salary_min_usd__isnull=False,
        ).aggregate(avg=Avg('salary_min_usd'))['avg']
        if avg_salary is not None:
            avg_salary = int(avg_salary)

        # Top skills
        user_skills = set(_get_user_skills(request.user))
        effective_country = '' if is_global else country
        trending = _trending_skills_raw(days=30, limit=20, country=effective_country)
        prev_skills = _prev_period_skills(days=30, limit=50, country=effective_country)

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
            'country': country if not is_global else 'all',
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

        # Geo-scoped trending skills
        country_param = request.query_params.get('country', '').strip()
        user_country = _get_user_country(request.user)
        country = country_param if country_param else user_country
        effective_country = '' if country.lower() == 'all' else country

        trending = _trending_skills_raw(days=30, limit=30, country=effective_country)
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
        user_country = _get_user_country(user)
        if user_skills:
            trending = _trending_skills_raw(days=30, limit=20, country=user_country)
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
        user_country = _get_user_country(request.user)
        country_param = request.query_params.get('country', '').strip()
        country = country_param if country_param else user_country
        effective_country = '' if country.lower() == 'all' else country

        trending = _trending_skills_raw(days=30, limit=12, country=effective_country)

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
        user_country = _get_user_country(request.user)
        country_param = request.query_params.get('country', '').strip()
        country = country_param if country_param else user_country
        is_global = country.lower() == 'all'

        cache_key = f'dashboard:market_insights:{country.lower()}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        now = timezone.now()
        this_week = now - timedelta(days=7)
        last_week_start = now - timedelta(days=14)

        qs_this = DiscoveredJob.objects.filter(created_at__gte=this_week)
        qs_last = DiscoveredJob.objects.filter(
            created_at__gte=last_week_start,
            created_at__lt=this_week,
        )
        if not is_global:
            qs_this = _filter_by_country(qs_this, country)
            qs_last = _filter_by_country(qs_last, country)

        this_week_count = qs_this.count()
        last_week_count = qs_last.count()

        growth = (
            round((this_week_count - last_week_count) / max(last_week_count, 1) * 100, 1)
            if last_week_count else 0.0
        )

        trending = _trending_skills_raw(days=7, limit=5, country='' if is_global else country)
        top_skill = trending[0]['skill'] if trending else None

        data = {
            'country': country if not is_global else 'all',
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
