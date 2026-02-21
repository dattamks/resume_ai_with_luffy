from rest_framework import serializers
from django.conf import settings

from .models import ResumeAnalysis


class ResumeAnalysisCreateSerializer(serializers.ModelSerializer):
    """Used for creating a new analysis request."""

    class Meta:
        model = ResumeAnalysis
        fields = (
            'id',
            'resume_file',
            'jd_input_type',
            'jd_text',
            'jd_url',
            'jd_role',
            'jd_company',
            'jd_skills',
            'jd_experience_years',
            'jd_industry',
            'jd_extra_details',
        )

    def validate_resume_file(self, value):
        max_bytes = settings.MAX_RESUME_SIZE_MB * 1024 * 1024
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f'Resume file must be under {settings.MAX_RESUME_SIZE_MB}MB.'
            )
        if not value.name.lower().endswith('.pdf'):
            raise serializers.ValidationError('Only PDF files are accepted.')
        return value

    def validate(self, attrs):
        jd_type = attrs.get('jd_input_type')

        if jd_type == ResumeAnalysis.JD_INPUT_TEXT and not attrs.get('jd_text'):
            raise serializers.ValidationError(
                {'jd_text': 'Job description text is required when input type is "text".'}
            )
        if jd_type == ResumeAnalysis.JD_INPUT_URL and not attrs.get('jd_url'):
            raise serializers.ValidationError(
                {'jd_url': 'A URL is required when input type is "url".'}
            )
        if jd_type == ResumeAnalysis.JD_INPUT_FORM and not attrs.get('jd_role'):
            raise serializers.ValidationError(
                {'jd_role': 'At least a job role is required when input type is "form".'}
            )
        return attrs


class ResumeAnalysisDetailSerializer(serializers.ModelSerializer):
    """Full read serializer — returned after analysis is done."""

    class Meta:
        model = ResumeAnalysis
        fields = (
            'id',
            'resume_file',
            'jd_input_type',
            'jd_text',
            'jd_url',
            'jd_role',
            'jd_company',
            'jd_skills',
            'jd_experience_years',
            'jd_industry',
            'jd_extra_details',
            'resolved_jd',
            'status',
            'error_message',
            'ats_score',
            'ats_score_breakdown',
            'keyword_gaps',
            'section_suggestions',
            'rewritten_bullets',
            'overall_assessment',
            'ai_provider_used',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class ResumeAnalysisListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    class Meta:
        model = ResumeAnalysis
        fields = (
            'id',
            'jd_role',
            'jd_company',
            'status',
            'ats_score',
            'ai_provider_used',
            'created_at',
        )
        read_only_fields = fields
