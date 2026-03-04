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
from django.db.models import Avg, Case, Count, F, FloatField, IntegerField, Q, Value, When
from django.db.models.expressions import ExpressionWrapper
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.throttles import ReadOnlyThrottle

from .currency import convert_usd, get_currency_for_country
from .models import (
    CoverLetter,
    DiscoveredJob,
    InterviewPrep,
    JobAlert,
    JobMatch,
    JobSearchProfile,
    Resume,
    ResumeAnalysis,
    RoleFamily,
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


def _get_user_titles(user) -> list[str]:
    """
    Return target job titles from the user's default resume's
    JobSearchProfile.  Falls back to Resume.career_profile['titles'].
    Returns empty list if nothing is available.
    """
    default_resume = Resume.get_default_for_user(user)
    if default_resume:
        try:
            jsp = JobSearchProfile.objects.get(resume=default_resume)
            if jsp.titles:
                return [t.strip() for t in jsp.titles if isinstance(t, str) and t.strip()]
        except JobSearchProfile.DoesNotExist:
            pass
        # Fallback to career_profile on the Resume itself
        cp = default_resume.career_profile
        if cp and isinstance(cp, dict) and cp.get('titles'):
            return [t.strip() for t in cp['titles'] if isinstance(t, str) and t.strip()]
    # Last resort: check all JSPs
    profiles = JobSearchProfile.objects.filter(resume__user=user).order_by('-updated_at')
    for p in profiles:
        if p.titles:
            return [t.strip() for t in p.titles if isinstance(t, str) and t.strip()]
    return []


def _get_user_embedding(user):
    """
    Return the embedding from the user's default resume's
    JobSearchProfile.  Falls back to the newest JSP embedding.
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


def _build_role_title_q(all_titles: list[str]) -> Q:
    """
    Build a Q filter matching DiscoveredJob.title against any of
    the given titles (case-insensitive substring match).
    """
    q = Q()
    for t in all_titles:
        t = t.strip()
        if t and len(t) >= 3:  # skip very short strings
            q |= Q(title__icontains=t)
    return q


# ── Minimum results threshold for role-scoped queries ──────────────────
_ROLE_SCOPED_MIN_RESULTS = 5


def _get_role_scoped_qs(
    user, base_qs, *, use_embedding: bool = True,
    embedding_threshold: float = 0.40,
):
    """
    Filter a DiscoveredJob queryset to role-relevant jobs using a
    two-layer hybrid strategy:

      Layer 1: LLM Role Map — explicit title matching via RoleFamily
      Layer 2: Embedding proximity — catches synonyms the map missed

    Returns (filtered_qs, role_info_dict, is_scoped_bool).
    If no role data is available, returns the original queryset unfiltered.

    Auto-broadens to unfiltered results if the scoped query yields fewer
    than ``_ROLE_SCOPED_MIN_RESULTS`` results.
    """
    user_titles = _get_user_titles(user)
    if not user_titles:
        return base_qs, {'source_titles': [], 'related_titles': [], 'method': 'none', 'scoped': False, 'broadened': False}, False

    # ── Layer 1: LLM Role Map ────────────────────────────────────────
    role_family = RoleFamily.get_or_none(user_titles)
    related_titles = role_family.related_titles if role_family else []
    all_titles = user_titles + related_titles

    title_q = _build_role_title_q(all_titles)
    layer1_qs = base_qs.filter(title_q) if title_q else base_qs.none()

    # ── Layer 2: Embedding proximity ─────────────────────────────────
    layer2_qs = base_qs.none()
    has_embedding_layer = False

    if use_embedding:
        embedding = _get_user_embedding(user)
        if embedding is not None:
            try:
                from pgvector.django import CosineDistance
                layer1_ids = set(layer1_qs.values_list('id', flat=True)[:500])
                layer2_qs = (
                    base_qs
                    .exclude(id__in=layer1_ids)
                    .exclude(embedding__isnull=True)
                    .annotate(distance=CosineDistance('embedding', embedding))
                    .filter(distance__lte=embedding_threshold)
                )
                has_embedding_layer = True
            except Exception:
                logger.debug('pgvector not available for role scoping — Layer 1 only')

    # ── Union ────────────────────────────────────────────────────────
    scoped_qs = (layer1_qs | layer2_qs) if has_embedding_layer else layer1_qs

    # Keep narrow (role-only) queryset for skill aggregation even when
    # the job listing is broadened.  This prevents unrelated skills
    # (e.g. React/Node for a Data Analyst) from dominating top_skills.
    role_qs = scoped_qs

    # ── Auto-broaden if too few results ──────────────────────────────
    scoped_count = scoped_qs.count()
    broadened = False
    if scoped_count < _ROLE_SCOPED_MIN_RESULTS:
        scoped_qs = base_qs
        broadened = True
        logger.info(
            'Role-scoped query too few results (%d) for titles=%s — broadened to all',
            scoped_count, user_titles[:3],
        )

    method = 'llm_map+embedding' if has_embedding_layer else ('llm_map' if role_family else 'titles_only')

    role_info = {
        'source_titles': user_titles,
        'related_titles': related_titles,
        'method': method,
        'scoped': not broadened,
        'broadened': broadened,
    }

    return scoped_qs, role_info, not broadened, role_qs


def _trending_skills_raw(
    days: int = 30, limit: int = 30, country: str = '',
    role_titles_hash: str = '', queryset=None,
) -> list[dict]:
    """
    Aggregate ``skills_required`` across recent DiscoveredJobs.
    Returns [{'skill': str, 'count': int}] sorted desc by count.

    If ``country`` is given, only considers jobs in that country
    (by ``country`` field or location heuristic for India).

    If ``queryset`` is provided, uses it directly (already role-scoped).
    ``role_titles_hash`` is used only for cache key differentiation.
    """
    cache_key = f'feed:trending_skills_raw:{days}:{limit}:{country}:{role_titles_hash}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if queryset is not None:
        qs = queryset.filter(skills_required__isnull=False)
    else:
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


def _prev_period_skills(
    days: int = 30, limit: int = 50, country: str = '',
    role_titles_hash: str = '', role_title_q: Q | None = None,
) -> dict[str, int]:
    """Skills from the *previous* period for growth % calculation.

    Accepts an optional ``role_title_q`` Q object to scope by role titles,
    and ``role_titles_hash`` for cache key differentiation.
    """
    cache_key = f'feed:prev_skills:{days}:{limit}:{country}:{role_titles_hash}'
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
    if role_title_q:
        qs = qs.filter(role_title_q)

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

# ── Allowed ordering values for FeedJobsView ────────────────────────────
_FEED_ORDERING_ALLOWLIST = {'relevance', '-posted_at', '-salary_min_usd'}


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
        - ``relevance_min`` (float 0-1, only return jobs with relevance >= value;
          jobs without embeddings are excluded when set; requires pgvector)
        - ``ordering`` (sort field: ``relevance`` (default), ``-posted_at``,
          ``-salary_min_usd``; when no explicit country is selected the
          user's geo-priority is always the primary sort key)
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

        # ── Parse new query params ────────────────────────────────
        ordering_param = request.query_params.get('ordering', '').strip()
        if ordering_param not in _FEED_ORDERING_ALLOWLIST:
            ordering_param = 'relevance'  # default

        relevance_min_param = request.query_params.get('relevance_min')
        relevance_min: float | None = None
        if relevance_min_param is not None:
            try:
                relevance_min = float(relevance_min_param)
                if not (0.0 <= relevance_min <= 1.0):
                    relevance_min = None
            except (ValueError, TypeError):
                relevance_min = None

        # ── Ranking ──────────────────────────────────────────────────
        profile_embedding = self._get_user_embedding(user)
        has_pgvector = False

        if profile_embedding is not None:
            try:
                from pgvector.django import CosineDistance

                qs = (
                    qs.exclude(embedding__isnull=True)
                    .annotate(distance=CosineDistance('embedding', profile_embedding))
                    .annotate(
                        relevance_score=ExpressionWrapper(
                            Value(1.0) - F('distance'),
                            output_field=FloatField(),
                        )
                    )
                )
                has_pgvector = True
            except Exception:
                logger.debug('pgvector not available for feed — falling back to recency')

        # ── relevance_min filter (applied before pagination) ─────────
        if relevance_min is not None:
            if has_pgvector:
                qs = qs.filter(relevance_score__gte=relevance_min)
            else:
                # Without embeddings we cannot compute relevance;
                # return empty result set so counts are accurate.
                qs = qs.none()

        # ── Build ordering clause ────────────────────────────────────
        order_fields: list = []

        # Geo-priority is always the primary sort key when no explicit
        # country filter was provided by the user.
        if not strict_country_filter:
            order_fields.append('geo_priority')

        if ordering_param == 'relevance':
            if has_pgvector:
                order_fields.append('distance')  # asc = most relevant first
            else:
                order_fields.append('-created_at')  # fallback
        elif ordering_param == '-posted_at':
            order_fields.append(F('posted_at').desc(nulls_last=True))
        elif ordering_param == '-salary_min_usd':
            order_fields.append(F('salary_min_usd').desc(nulls_last=True))

        qs = qs.order_by(*order_fields)

        # ── Pagination ───────────────────────────────────────────────
        total = qs.count()
        job_rows = list(qs[offset:offset + page_size])

        # Attach relevance attribute for the serializer
        for job in job_rows:
            if has_pgvector and hasattr(job, 'relevance_score'):
                job.relevance = round(job.relevance_score, 4)
            else:
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

    **Role-aware** (hybrid LLM map + embedding): by default scopes
    aggregations to jobs matching the user's target roles from their
    resume.  Pass ``?role=all`` to see unfiltered market data.

    Geography-aware: scoped to the user's country by default.
    Pass ``?country=`` to filter for a specific country, or
    ``?country=all`` to see global data.

    Cached per-country per-role for 60 minutes.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        country_param = request.query_params.get('country', '').strip()
        user_country = _get_user_country(request.user)
        country = country_param if country_param else user_country
        is_global = country.lower() == 'all'

        # Role param: 'all' = no role filter, '' = auto from resume
        role_param = request.query_params.get('role', '').strip()
        skip_role_scope = role_param.lower() == 'all'

        # Compute cache key incorporating role
        user_titles = _get_user_titles(request.user) if not skip_role_scope else []
        titles_hash = RoleFamily.compute_hash(user_titles) if user_titles else 'all'
        cache_key = f'feed:insights:{country.lower()}:{titles_hash}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        since = timezone.now() - timedelta(days=30)
        qs = DiscoveredJob.objects.filter(created_at__gte=since)
        if not is_global:
            qs = _filter_by_country(qs, country)

        # ── Apply role scoping ──────────────────────────────────────────
        role_qs = None
        if not skip_role_scope:
            qs, role_info, is_scoped, role_qs = _get_role_scoped_qs(request.user, qs)
        else:
            role_info = {'source_titles': [], 'related_titles': [], 'method': 'none', 'scoped': False, 'broadened': False}

        # Determine the best queryset for role-specific aggregations.
        # When broadened, role_qs is the narrow (pre-broadened) set;
        # use it for aggregations so unrelated roles don't pollute data.
        agg_qs = role_qs if (role_qs is not None and role_qs.exists()) else qs

        total = qs.count()
        total_role = agg_qs.count() if agg_qs is not qs else total

        # ── Currency ────────────────────────────────────────────────────
        salary_currency = get_currency_for_country(country if not is_global else '')

        # ── Salary: role-level average ──────────────────────────────────
        avg_salary_usd = agg_qs.filter(
            salary_min_usd__isnull=False,
        ).aggregate(avg=Avg('salary_min_usd'))['avg']
        avg_salary_role = convert_usd(avg_salary_usd, salary_currency)

        # ── Salary: by seniority level ──────────────────────────────────
        seniority_salary_rows = (
            agg_qs.filter(
                salary_min_usd__isnull=False,
                seniority_level__gt='',
            )
            .values('seniority_level')
            .annotate(avg=Avg('salary_min_usd'))
        )
        avg_salary_by_seniority = {
            row['seniority_level']: convert_usd(row['avg'], salary_currency)
            for row in seniority_salary_rows
        }

        # Top skills — use the narrow role-scoped queryset when
        # broadened to avoid polluting skills with unrelated roles.
        user_skills = set(_get_user_skills(request.user))
        effective_country = '' if is_global else country
        trending = _trending_skills_raw(
            days=30, limit=20, country=effective_country,
            role_titles_hash=titles_hash, queryset=agg_qs,
        )

        # For growth %, build the role title Q to pass to prev_period
        role_title_q = None
        if not skip_role_scope and user_titles:
            role_family = RoleFamily.get_or_none(user_titles)
            related = role_family.related_titles if role_family else []
            all_t = user_titles + related
            role_title_q = _build_role_title_q(all_t)
            # Note: embedding layer not used for prev period (perf tradeoff)

        prev_skills = _prev_period_skills(
            days=30, limit=50, country=effective_country,
            role_titles_hash=titles_hash, role_title_q=role_title_q,
        )

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

        # Top companies (role-scoped)
        top_companies = list(
            agg_qs.filter(company__gt='')
            .values('company')
            .annotate(job_count=Count('id'))
            .order_by('-job_count')[:10]
        )

        # Top locations (role-scoped)
        top_locations = list(
            agg_qs.filter(location__gt='')
            .values('location')
            .annotate(job_count=Count('id'))
            .order_by('-job_count')[:10]
        )

        # Breakdowns (role-scoped)
        emp_breakdown = dict(
            agg_qs.filter(employment_type__gt='')
            .values_list('employment_type')
            .annotate(c=Count('id'))
            .order_by('-c')
        )
        remote_breakdown = dict(
            agg_qs.filter(remote_policy__gt='')
            .values_list('remote_policy')
            .annotate(c=Count('id'))
            .order_by('-c')
        )
        seniority_breakdown = dict(
            agg_qs.filter(seniority_level__gt='')
            .values_list('seniority_level')
            .annotate(c=Count('id'))
            .order_by('-c')
        )

        data = {
            'country': country if not is_global else 'all',
            'role_filter': role_info,
            'total_jobs_last_30d': total,
            'total_jobs_role_specific': total_role,
            'salary_currency': salary_currency,
            'avg_salary_role': avg_salary_role,
            'avg_salary_by_seniority': avg_salary_by_seniority,
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

    **Role-aware**: by default scopes skill aggregation to jobs matching
    the user's target roles (hybrid LLM map + embedding).  Pass
    ``?role=all`` to see the full market.

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
        is_global = country.lower() == 'all'
        effective_country = '' if is_global else country

        # Role param
        role_param = request.query_params.get('role', '').strip()
        skip_role_scope = role_param.lower() == 'all'

        user_titles = _get_user_titles(request.user) if not skip_role_scope else []
        titles_hash = RoleFamily.compute_hash(user_titles) if user_titles else 'all'

        # Build role-scoped queryset for trending aggregation
        since = timezone.now() - timedelta(days=30)
        qs = DiscoveredJob.objects.filter(
            created_at__gte=since,
            skills_required__isnull=False,
        )
        if effective_country:
            qs = _filter_by_country(qs, effective_country)

        role_info = {'source_titles': [], 'related_titles': [], 'method': 'none', 'scoped': False, 'broadened': False}
        role_qs = None
        if not skip_role_scope:
            qs, role_info, _, role_qs = _get_role_scoped_qs(request.user, qs)

        # Use narrow role-scoped queryset for skill aggregation when
        # broadened to avoid polluting with unrelated roles' skills.
        skills_qs = role_qs if (role_qs is not None and role_qs.exists()) else qs
        trending = _trending_skills_raw(
            days=30, limit=30, country=effective_country,
            role_titles_hash=titles_hash, queryset=skills_qs,
        )
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
            'role_filter': role_info,
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

    **Role-aware**: scoped to the user's target roles by default.
    Pass ``?role=all`` for full market.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user_skills = set(_get_user_skills(request.user))
        user_country = _get_user_country(request.user)
        country_param = request.query_params.get('country', '').strip()
        country = country_param if country_param else user_country
        is_global = country.lower() == 'all'
        effective_country = '' if is_global else country

        role_param = request.query_params.get('role', '').strip()
        skip_role_scope = role_param.lower() == 'all'

        user_titles = _get_user_titles(request.user) if not skip_role_scope else []
        titles_hash = RoleFamily.compute_hash(user_titles) if user_titles else 'all'

        # Build role-scoped queryset
        since = timezone.now() - timedelta(days=30)
        qs = DiscoveredJob.objects.filter(
            created_at__gte=since,
            skills_required__isnull=False,
        )
        if effective_country:
            qs = _filter_by_country(qs, effective_country)
        role_qs = None
        if not skip_role_scope:
            qs, _, _, role_qs = _get_role_scoped_qs(request.user, qs)

        # Use narrow role-scoped queryset for skill aggregation when
        # broadened to avoid polluting with unrelated roles' skills.
        skills_qs = role_qs if (role_qs is not None and role_qs.exists()) else qs
        trending = _trending_skills_raw(
            days=30, limit=12, country=effective_country,
            role_titles_hash=titles_hash, queryset=skills_qs,
        )

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

    **Role-aware**: scoped to the user's target roles by default.
    Pass ``?role=all`` for full market.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        user_country = _get_user_country(request.user)
        country_param = request.query_params.get('country', '').strip()
        country = country_param if country_param else user_country
        is_global = country.lower() == 'all'

        role_param = request.query_params.get('role', '').strip()
        skip_role_scope = role_param.lower() == 'all'
        user_titles = _get_user_titles(request.user) if not skip_role_scope else []
        titles_hash = RoleFamily.compute_hash(user_titles) if user_titles else 'all'

        cache_key = f'dashboard:market_insights:{country.lower()}:{titles_hash}'
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

        # Apply role scoping to both periods
        role_qs_this = None
        if not skip_role_scope:
            qs_this, _, _, role_qs_this = _get_role_scoped_qs(request.user, qs_this)
            qs_last, _, _, _ = _get_role_scoped_qs(request.user, qs_last)

        this_week_count = qs_this.count()
        last_week_count = qs_last.count()

        growth = (
            round((this_week_count - last_week_count) / max(last_week_count, 1) * 100, 1)
            if last_week_count else 0.0
        )

        # Use narrow role-scoped queryset for skill aggregation
        agg_qs = role_qs_this if (role_qs_this is not None and role_qs_this.exists()) else qs_this
        trending = _trending_skills_raw(
            days=7, limit=5, country='' if is_global else country,
            role_titles_hash=titles_hash, queryset=agg_qs,
        )
        top_skill = trending[0]['skill'] if trending else None

        # Currency-converted role-level average salary
        salary_currency = get_currency_for_country(country if not is_global else '')
        avg_usd = agg_qs.filter(
            salary_min_usd__isnull=False,
        ).aggregate(avg=Avg('salary_min_usd'))['avg']
        avg_salary_role = convert_usd(avg_usd, salary_currency)

        data = {
            'country': country if not is_global else 'all',
            'jobs_this_week': this_week_count,
            'jobs_last_week': last_week_count,
            'growth_pct': growth,
            'trend': 'up' if growth > 0 else ('down' if growth < 0 else 'flat'),
            'top_skill_this_week': top_skill,
            'top_skills': trending,
            'salary_currency': salary_currency,
            'avg_salary_role': avg_salary_role,
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


class DashboardActivityHistoryView(APIView):
    """
    GET /api/v1/dashboard/activity/history/

    Daily activity history for the authenticated user.
    Powers a GitHub-style activity heatmap or timeline.

    Query params:
        - ``days`` (int, default 90, max 365) — how many days of history
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        from .models import UserActivity

        try:
            days = min(max(int(request.query_params.get('days', 90)), 1), 365)
        except (ValueError, TypeError):
            days = 90

        since = timezone.now().date() - timedelta(days=days)

        rows = (
            UserActivity.objects
            .filter(user=request.user, date__gte=since)
            .order_by('-date')
            .values('date', 'action_count', 'actions')
        )

        streak_days, actions_this_month = UserActivity.get_streak(request.user)

        data = {
            'streak_days': streak_days,
            'actions_this_month': actions_this_month,
            'days': list(rows),
            'total_days_active': len(rows),
        }

        from .serializers_feed import ActivityHistorySerializer
        serializer = ActivityHistorySerializer(data)
        return Response(serializer.data)


# ── News Feed ────────────────────────────────────────────────────────────────


class FeedNewsListView(APIView):
    """
    GET /api/v1/feed/news/  — Paginated news feed.

    Returns active, approved, non-flagged news snippets sorted by
    ``published_at`` descending.

    Query params:
        - ``page`` (int, default 1)
        - ``page_size`` (int, default 20, max 50)
        - ``category`` (slug filter, e.g. ``hiring``, ``ai_automation``)
        - ``region`` (e.g. ``India``, ``US``, ``Global``)
        - ``sentiment`` (``positive``, ``neutral``, ``negative``)
        - ``search`` (free-text search across headline, summary, tags)
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        from .models import NewsSnippet
        from .serializers_ingest import NewsSnippetReadSerializer

        # Pagination
        try:
            page = max(int(request.query_params.get('page', 1)), 1)
        except (ValueError, TypeError):
            page = 1
        try:
            page_size = min(max(int(request.query_params.get('page_size', 20)), 1), 50)
        except (ValueError, TypeError):
            page_size = 20

        offset = (page - 1) * page_size

        # Base queryset — only active + approved + not flagged
        qs = NewsSnippet.objects.filter(
            is_active=True,
            is_approved=True,
            is_flagged=False,
        )

        # ── Filters ──────────────────────────────────────────────────
        category = request.query_params.get('category', '').strip()
        if category:
            qs = qs.filter(category=category)

        region = request.query_params.get('region', '').strip()
        if region:
            qs = qs.filter(region__iexact=region)

        sentiment = request.query_params.get('sentiment', '').strip()
        if sentiment:
            qs = qs.filter(sentiment=sentiment)

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(headline__icontains=search)
                | Q(summary__icontains=search)
                | Q(tags__icontains=search)
            )

        # ── Count + slice ────────────────────────────────────────────
        total = qs.count()
        snippets = qs.order_by('-published_at', '-created_at')[offset:offset + page_size]

        serializer = NewsSnippetReadSerializer(snippets, many=True)
        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size if total else 0,
            'results': serializer.data,
        })


class FeedNewsDetailView(APIView):
    """
    GET /api/v1/feed/news/<uuid:id>/  — Single news snippet detail.

    Only returns active, approved, non-flagged snippets.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        from .models import NewsSnippet
        from .serializers_ingest import NewsSnippetReadSerializer

        try:
            snippet = NewsSnippet.objects.get(
                id=pk,
                is_active=True,
                is_approved=True,
                is_flagged=False,
            )
        except NewsSnippet.DoesNotExist:
            return Response(
                {'detail': 'News snippet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = NewsSnippetReadSerializer(snippet)
        return Response(serializer.data)
