"""
API views for the normalised Skill catalogue.

Endpoints:
    GET  /api/v1/skills/           — list/search skills (paginated, filterable)
    GET  /api/v1/skills/<name>/    — single skill detail by canonical name
"""
import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.throttles import ReadOnlyThrottle
from .models import Skill
from .serializers_skills import SkillListSerializer, SkillDetailSerializer

logger = logging.getLogger('analyzer')


class SkillListView(ListAPIView):
    """
    GET /api/v1/skills/

    List skills with optional filtering and search.

    Query params:
        - ``q``        — free-text search across name, display_name, aliases
        - ``category`` — filter by category (e.g. ``language``, ``framework``)
        - ``trending`` — if ``true``, only return trending skills
        - ``ordering`` — one of: ``demand``, ``growth``, ``name``, ``salary``
                         (prefix with ``-`` for descending, default: ``-demand``)
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = SkillListSerializer

    ORDERING_MAP = {
        'demand': 'job_count_30d',
        '-demand': '-job_count_30d',
        'growth': 'growth_pct',
        '-growth': '-growth_pct',
        'name': 'name',
        '-name': '-name',
        'salary': 'avg_salary_usd',
        '-salary': '-avg_salary_usd',
    }

    def get_queryset(self):
        qs = Skill.objects.filter(is_active=True)

        # Free-text search
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(display_name__icontains=q)
                | Q(aliases__icontains=q)
            )

        # Category filter
        category = self.request.query_params.get('category', '').strip()
        if category:
            qs = qs.filter(category=category)

        # Trending filter
        trending = self.request.query_params.get('trending', '').strip().lower()
        if trending == 'true':
            qs = qs.filter(is_trending=True)

        # Ordering
        ordering_param = self.request.query_params.get('ordering', '-demand').strip()
        order_field = self.ORDERING_MAP.get(ordering_param, '-job_count_30d')
        qs = qs.order_by(order_field)

        return qs


class SkillDetailView(RetrieveAPIView):
    """
    GET /api/v1/skills/<name>/

    Retrieve a single skill by its canonical name (URL-safe lowercase slug).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]
    serializer_class = SkillDetailSerializer
    lookup_field = 'name'
    lookup_url_kwarg = 'name'

    def get_queryset(self):
        return Skill.objects.filter(is_active=True)
