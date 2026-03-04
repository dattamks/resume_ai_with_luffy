"""
Serializers for the normalised Skill catalogue.
"""
from rest_framework import serializers

from .models import Skill


class SkillListSerializer(serializers.ModelSerializer):
    """Compact skill card for list / search views."""

    class Meta:
        model = Skill
        fields = (
            'id', 'name', 'display_name', 'category',
            'job_count_30d', 'job_count_1y', 'job_count_5y',
            'growth_pct', 'is_trending',
        )
        read_only_fields = fields


class SkillDetailSerializer(serializers.ModelSerializer):
    """Full skill detail including description, roles, salary info."""
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = Skill
        fields = (
            'id', 'name', 'display_name', 'description',
            'category', 'category_display', 'aliases', 'roles',
            'job_count_30d', 'job_count_1y', 'job_count_5y',
            'growth_pct', 'avg_salary_usd',
            'is_trending', 'is_active',
            'last_aggregated_at', 'created_at', 'updated_at',
        )
        read_only_fields = fields
