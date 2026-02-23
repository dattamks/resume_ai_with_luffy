from rest_framework import serializers
from django.conf import settings
from django.db.models import Count

from .models import ResumeAnalysis, ScrapeResult, LLMResponse, Resume


class ResumeSerializer(serializers.ModelSerializer):
    """Read-only serializer for the Resume model."""
    active_analysis_count = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = (
            'id', 'original_filename', 'file_size_bytes',
            'uploaded_at', 'active_analysis_count',
        )
        read_only_fields = fields

    def get_active_analysis_count(self, obj):
        # Annotated by the view queryset for efficiency
        return getattr(obj, 'active_analysis_count', 0)


class ScrapeResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScrapeResult
        fields = (
            'id', 'source_url', 'summary',
            'status', 'error_message', 'created_at', 'updated_at',
        )
        read_only_fields = fields


class LLMResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMResponse
        fields = (
            'id', 'parsed_response',
            'model_used', 'status', 'error_message', 'duration_seconds',
            'created_at',
        )
        read_only_fields = fields


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
        # Validate PDF magic bytes to prevent disguised file uploads
        header = value.read(4)
        value.seek(0)
        if header != b'%PDF':
            raise serializers.ValidationError(
                'File content does not appear to be a valid PDF.'
            )
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

    def create(self, validated_data):
        """Override to handle Resume deduplication on create."""
        user = validated_data.get('user') or self.context['request'].user
        resume_file = validated_data.get('resume_file')

        # Deduplicate resume file
        if resume_file:
            resume_obj, _created = Resume.get_or_create_from_upload(user, resume_file)
            validated_data['resume'] = resume_obj

        return super().create(validated_data)


class ResumeAnalysisDetailSerializer(serializers.ModelSerializer):
    """Full read serializer — returned after analysis is done."""
    scrape_result = ScrapeResultSerializer(read_only=True)
    llm_response = LLMResponseSerializer(read_only=True)
    report_pdf_url = serializers.SerializerMethodField()
    resume_file_url = serializers.SerializerMethodField()

    class Meta:
        model = ResumeAnalysis
        fields = (
            'id',
            'resume_file',
            'resume_file_url',
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
            'scrape_result',
            'llm_response',
            'status',
            'pipeline_step',
            'error_message',
            'ats_score',
            'ats_score_breakdown',
            'keyword_gaps',
            'section_suggestions',
            'rewritten_bullets',
            'overall_assessment',
            'ai_provider_used',
            'celery_task_id',
            'report_pdf_url',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_report_pdf_url(self, obj):
        if obj.report_pdf:
            return obj.report_pdf.url
        return None

    def get_resume_file_url(self, obj):
        if obj.resume_file:
            return obj.resume_file.url
        return None


class ResumeAnalysisListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    report_pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = ResumeAnalysis
        fields = (
            'id',
            'jd_role',
            'jd_company',
            'status',
            'pipeline_step',
            'ats_score',
            'ai_provider_used',
            'report_pdf_url',
            'created_at',
        )
        read_only_fields = fields

    def get_report_pdf_url(self, obj):
        if obj.report_pdf:
            return obj.report_pdf.url
        return None
