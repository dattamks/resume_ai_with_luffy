"""
Feed & analytics serializers.

Lightweight data-transfer serializers for the /api/v1/feed/ endpoints.
These are read-only and intentionally separate from the main serializers
to avoid pulling in heavy fields (raw_data, description_snippet, etc.)
unless explicitly needed.
"""
from rest_framework import serializers

from .models import DiscoveredJob, JobAlert, InterviewPrep, CoverLetter


# ── Feed Jobs ────────────────────────────────────────────────────────────

class FeedJobSerializer(serializers.ModelSerializer):
    """
    Compact job card for the personalised feed.
    Includes a ``relevance`` field injected by the view (annotation).
    """
    relevance = serializers.FloatField(read_only=True, default=None)

    class Meta:
        model = DiscoveredJob
        fields = (
            'id', 'title', 'company', 'location', 'country', 'url',
            'salary_range', 'salary_min_usd', 'salary_max_usd',
            'employment_type', 'remote_policy', 'seniority_level',
            'industry', 'skills_required',
            'posted_at', 'created_at',
            'relevance',
        )
        read_only_fields = fields


# ── Insights ─────────────────────────────────────────────────────────────

class TrendingSkillSerializer(serializers.Serializer):
    """One row in the trending-skills breakdown."""
    skill = serializers.CharField()
    demand_count = serializers.IntegerField(help_text='Number of recent jobs requiring this skill')
    growth_pct = serializers.FloatField(
        help_text='Percentage change vs previous period', default=0.0,
    )
    you_have = serializers.BooleanField(
        help_text='Whether the user\'s profile lists this skill', default=False,
    )


class TopCompanySerializer(serializers.Serializer):
    """Company with its recent job count."""
    company = serializers.CharField()
    job_count = serializers.IntegerField()


class InsightsSerializer(serializers.Serializer):
    """Composite response for GET /api/v1/feed/insights/."""
    total_jobs_last_30d = serializers.IntegerField()
    avg_salary_usd = serializers.IntegerField(allow_null=True)
    top_skills = TrendingSkillSerializer(many=True)
    top_companies = TopCompanySerializer(many=True)
    top_locations = serializers.ListField(child=serializers.DictField())
    employment_type_breakdown = serializers.DictField()
    remote_policy_breakdown = serializers.DictField()
    seniority_breakdown = serializers.DictField()


# ── Trending Skills vs User ─────────────────────────────────────────────

class SkillGapItemSerializer(serializers.Serializer):
    """Single skill in the trending-vs-user comparison."""
    skill = serializers.CharField()
    demand_count = serializers.IntegerField()
    you_have = serializers.BooleanField()
    category = serializers.ChoiceField(choices=['match', 'gap', 'niche'])


class TrendingVsUserSerializer(serializers.Serializer):
    """Response for GET /api/v1/feed/trending-skills/."""
    matches = SkillGapItemSerializer(many=True, help_text='Skills you have that are in demand')
    gaps = SkillGapItemSerializer(many=True, help_text='In-demand skills you\'re missing')
    niche = SkillGapItemSerializer(many=True, help_text='Skills you have that aren\'t trending')
    match_pct = serializers.FloatField(help_text='Percentage of trending skills you have')


# ── Hub ──────────────────────────────────────────────────────────────────

class HubAlertSummarySerializer(serializers.ModelSerializer):
    """Alert card in the hub."""
    resume_filename = serializers.CharField(source='resume.original_filename', read_only=True)
    matches_this_week = serializers.IntegerField(read_only=True, default=0)
    health = serializers.CharField(read_only=True, default='ok')

    class Meta:
        model = JobAlert
        fields = (
            'id', 'resume_filename', 'frequency', 'is_active',
            'matches_this_week', 'health',
            'last_run_at', 'next_run_at', 'created_at',
        )
        read_only_fields = fields


class HubInterviewPrepSerializer(serializers.ModelSerializer):
    """Compact interview prep card for the hub."""
    analysis_role = serializers.CharField(source='analysis.jd_role', read_only=True, default='')

    class Meta:
        model = InterviewPrep
        fields = ('id', 'analysis_role', 'status', 'created_at')
        read_only_fields = fields


class HubCoverLetterSerializer(serializers.ModelSerializer):
    """Compact cover-letter card for the hub."""
    analysis_role = serializers.CharField(source='analysis.jd_role', read_only=True, default='')

    class Meta:
        model = CoverLetter
        fields = ('id', 'analysis_role', 'tone', 'status', 'created_at')
        read_only_fields = fields


class HubSerializer(serializers.Serializer):
    """Composite response for GET /api/v1/feed/hub/."""
    alerts = HubAlertSummarySerializer(many=True)
    interview_preps = HubInterviewPrepSerializer(many=True)
    cover_letters = HubCoverLetterSerializer(many=True)


# ── Recommendations ─────────────────────────────────────────────────────

class RecommendationSerializer(serializers.Serializer):
    """A single actionable recommendation."""
    key = serializers.CharField(help_text='Machine-readable key, e.g. "upload_resume"')
    title = serializers.CharField()
    description = serializers.CharField()
    priority = serializers.ChoiceField(choices=['high', 'medium', 'low'])
    action_url = serializers.CharField(
        help_text='Frontend route to navigate to', allow_blank=True, default='',
    )
    completed = serializers.BooleanField(default=False)


# ── Dashboard extras ────────────────────────────────────────────────────

class SkillGapRadarItemSerializer(serializers.Serializer):
    """One axis on the skill-gap radar chart."""
    skill = serializers.CharField()
    user_score = serializers.IntegerField(help_text='0-100 based on resume mentions + analysis')
    market_score = serializers.IntegerField(help_text='0-100 based on job demand')


class ActivitySerializer(serializers.Serializer):
    """Response for GET /api/v1/dashboard/activity/."""
    streak_days = serializers.IntegerField()
    actions_this_month = serializers.IntegerField()
