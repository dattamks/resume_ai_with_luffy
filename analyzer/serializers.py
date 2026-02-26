from rest_framework import serializers
from django.conf import settings

from .models import ResumeAnalysis, ScrapeResult, LLMResponse, Resume, Job, GeneratedResume, JobAlert, JobMatch, DiscoveredJob, JobAlertRun, JobSearchProfile


class ResumeSerializer(serializers.ModelSerializer):
    """Read-only serializer for the Resume model."""
    active_analysis_count = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = (
            'id', 'original_filename', 'file_size_bytes',
            'uploaded_at', 'active_analysis_count', 'file_url',
        )
        read_only_fields = fields

    def get_active_analysis_count(self, obj):
        # Annotated by the view queryset for efficiency
        return getattr(obj, 'active_analysis_count', 0)

    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None


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
    """
    Used for creating a new analysis request.

    Accepts EITHER:
      • resume_file  – a PDF upload (multipart/form-data), OR
      • resume_id    – UUID of an existing Resume owned by the user (JSON / form)

    Exactly one must be provided.
    """
    resume_id = serializers.UUIDField(required=False, write_only=True)

    class Meta:
        model = ResumeAnalysis
        fields = (
            'id',
            'resume_file',
            'resume_id',
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
        extra_kwargs = {
            'resume_file': {'required': False},
        }

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
        resume_file = attrs.get('resume_file')
        resume_id = attrs.get('resume_id')

        if resume_file and resume_id:
            raise serializers.ValidationError(
                'Provide either "resume_file" or "resume_id", not both.'
            )
        if not resume_file and not resume_id:
            raise serializers.ValidationError(
                'Either "resume_file" or "resume_id" is required.'
            )

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
        """
        Override to handle Resume deduplication on create.

        Two paths:
        1) resume_file provided → deduplicate via Resume.get_or_create_from_upload
        2) resume_id provided   → look up existing Resume by UUID, reuse its file
        """
        user = validated_data.get('user') or self.context['request'].user
        resume_file = validated_data.get('resume_file')
        resume_id = validated_data.pop('resume_id', None)

        if resume_id:
            # Path 2: reuse an existing Resume
            try:
                resume_obj = Resume.objects.get(id=resume_id, user=user)
            except Resume.DoesNotExist:
                raise serializers.ValidationError(
                    {'resume_id': 'Resume not found or does not belong to you.'}
                )
            validated_data['resume'] = resume_obj
            # Point to the same storage path so the pipeline works unchanged
            validated_data['resume_file'] = resume_obj.file.name
        elif resume_file:
            # Path 1: fresh upload → deduplicate
            resume_obj, _created = Resume.get_or_create_from_upload(user, resume_file)
            validated_data['resume'] = resume_obj

        return super().create(validated_data)


class ResumeAnalysisDetailSerializer(serializers.ModelSerializer):
    """Full read serializer — returned after analysis is done."""
    scrape_result = ScrapeResultSerializer(read_only=True)
    llm_response = LLMResponseSerializer(read_only=True)
    report_pdf_url = serializers.SerializerMethodField()
    resume_file_url = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()

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
            'overall_grade',
            'ats_score',
            'scores',
            'ats_disclaimers',
            'keyword_analysis',
            'section_feedback',
            'sentence_suggestions',
            'formatting_flags',
            'quick_wins',
            'summary',
            'ai_provider_used',
            'celery_task_id',
            'report_pdf_url',
            'share_token',
            'share_url',
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

    def get_share_url(self, obj):
        if obj.share_token:
            request = self.context.get('request')
            path = f'/api/shared/{obj.share_token}/'
            if request:
                return request.build_absolute_uri(path)
            return path
        return None


class ResumeAnalysisListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    report_pdf_url = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = ResumeAnalysis
        fields = (
            'id',
            'jd_role',
            'jd_company',
            'status',
            'pipeline_step',
            'overall_grade',
            'ats_score',
            'ai_provider_used',
            'report_pdf_url',
            'share_token',
            'share_url',
            'created_at',
        )
        read_only_fields = fields

    def get_report_pdf_url(self, obj):
        if obj.report_pdf:
            return obj.report_pdf.url
        return None

    def get_share_url(self, obj):
        if obj.share_token:
            request = self.context.get('request')
            path = f'/api/shared/{obj.share_token}/'
            if request:
                return request.build_absolute_uri(path)
            return path
        return None


class SharedAnalysisSerializer(serializers.ModelSerializer):
    """
    Public read-only serializer for shared analyses.
    Excludes sensitive fields: resume_file, resume_text, resolved_jd, celery_task_id.
    """

    class Meta:
        model = ResumeAnalysis
        fields = (
            'jd_role',
            'jd_company',
            'jd_industry',
            'status',
            'overall_grade',
            'ats_score',
            'scores',
            'ats_disclaimers',
            'keyword_analysis',
            'section_feedback',
            'sentence_suggestions',
            'formatting_flags',
            'quick_wins',
            'summary',
            'ai_provider_used',
            'created_at',
        )
        read_only_fields = fields


# ── Job serializers ────────────────────────────────────────────────────────

class JobSerializer(serializers.ModelSerializer):
    """Full read serializer for Job model."""
    resume_filename = serializers.CharField(
        source='resume.original_filename', read_only=True, default=None,
    )

    class Meta:
        model = Job
        fields = (
            'id', 'job_url', 'title', 'company', 'description',
            'relevance', 'source', 'resume', 'resume_filename',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'resume_filename')


class JobCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new tracked job."""
    resume_id = serializers.UUIDField(required=False, write_only=True)

    class Meta:
        model = Job
        fields = (
            'id', 'job_url', 'title', 'company', 'description',
            'source', 'resume_id',
        )
        read_only_fields = ('id',)

    def create(self, validated_data):
        user = self.context['request'].user
        resume_id = validated_data.pop('resume_id', None)

        if resume_id:
            try:
                resume = Resume.objects.get(id=resume_id, user=user)
            except Resume.DoesNotExist:
                raise serializers.ValidationError(
                    {'resume_id': 'Resume not found or does not belong to you.'}
                )
            validated_data['resume'] = resume

        validated_data['user'] = user
        return super().create(validated_data)


class GeneratedResumeSerializer(serializers.ModelSerializer):
    """Read-only serializer for generated resume status and download."""
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedResume
        fields = (
            'id', 'analysis', 'template', 'format',
            'status', 'error_message', 'file_url', 'created_at',
        )
        read_only_fields = fields

    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None


class GeneratedResumeCreateSerializer(serializers.Serializer):
    """Serializer for requesting a resume generation."""
    template = serializers.SlugField(max_length=50, default='ats_classic')
    format = serializers.ChoiceField(
        choices=[('pdf', 'PDF'), ('docx', 'DOCX')],
        default='pdf',
    )

    def validate_template(self, value):
        # Currently only ats_classic is supported
        supported = ('ats_classic',)
        if value not in supported:
            raise serializers.ValidationError(
                f'Template "{value}" is not supported. Available: {", ".join(supported)}'
            )
        return value


# ── Phase 11: Smart Job Alerts ────────────────────────────────────────────────


class JobSearchProfileSerializer(serializers.ModelSerializer):
    """Read-only — returned nested inside JobAlertDetailSerializer."""
    class Meta:
        model = JobSearchProfile
        fields = (
            'titles', 'skills', 'seniority', 'industries',
            'locations', 'experience_years', 'updated_at',
        )
        read_only_fields = fields


class DiscoveredJobSerializer(serializers.ModelSerializer):
    """Read-only serializer for a discovered job."""
    class Meta:
        model = DiscoveredJob
        fields = (
            'id', 'source', 'title', 'company', 'location',
            'salary_range', 'description_snippet', 'url', 'posted_at', 'created_at',
        )
        read_only_fields = fields


class JobMatchSerializer(serializers.ModelSerializer):
    """Serializer for a job match result (includes nested DiscoveredJob)."""
    job = DiscoveredJobSerializer(source='discovered_job', read_only=True)

    class Meta:
        model = JobMatch
        fields = (
            'id', 'job', 'relevance_score', 'match_reason',
            'user_feedback', 'created_at',
        )
        read_only_fields = ('id', 'job', 'relevance_score', 'match_reason', 'created_at')


class JobMatchFeedbackSerializer(serializers.ModelSerializer):
    """Write-only — update user_feedback on a match."""
    class Meta:
        model = JobMatch
        fields = ('user_feedback',)

    def validate_user_feedback(self, value):
        valid = {c[0] for c in JobMatch.FEEDBACK_CHOICES} - {JobMatch.FEEDBACK_PENDING}
        if value not in valid:
            raise serializers.ValidationError(
                f'Invalid feedback. Choose from: {", ".join(sorted(valid))}.'
            )
        return value


class JobAlertRunSerializer(serializers.ModelSerializer):
    """Read-only run stats."""
    class Meta:
        model = JobAlertRun
        fields = (
            'id', 'jobs_discovered', 'jobs_matched', 'notification_sent',
            'credits_used', 'error_message', 'duration_seconds', 'created_at',
        )
        read_only_fields = fields


class JobAlertSerializer(serializers.ModelSerializer):
    """List serializer — lightweight."""
    last_run = serializers.SerializerMethodField()
    resume_filename = serializers.CharField(source='resume.original_filename', read_only=True)
    search_profile = JobSearchProfileSerializer(
        source='resume.job_search_profile', read_only=True, default=None,
    )

    class Meta:
        model = JobAlert
        fields = (
            'id', 'resume', 'resume_filename', 'frequency', 'is_active',
            'preferences', 'last_run_at', 'next_run_at',
            'search_profile', 'last_run', 'created_at',
        )
        read_only_fields = (
            'id', 'resume_filename', 'last_run_at', 'next_run_at',
            'search_profile', 'last_run', 'created_at',
        )

    def get_last_run(self, instance):
        latest = instance.runs.order_by('-created_at').first()
        return JobAlertRunSerializer(latest).data if latest else None


class JobAlertCreateSerializer(serializers.ModelSerializer):
    """Create a new job alert."""
    class Meta:
        model = JobAlert
        fields = ('resume', 'frequency', 'preferences')

    def validate_resume(self, resume):
        user = self.context['request'].user
        if resume.user_id != user.id:
            raise serializers.ValidationError('Resume not found.')
        # Prevent duplicate active alerts for the same resume
        from .models import JobAlert
        if JobAlert.objects.filter(user=user, resume=resume, is_active=True).exists():
            raise serializers.ValidationError(
                'An active job alert already exists for this resume.'
            )
        return resume

    def validate_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('preferences must be a JSON object.')
        return value


class JobAlertUpdateSerializer(serializers.ModelSerializer):
    """Update frequency and preferences on an existing alert."""
    class Meta:
        model = JobAlert
        fields = ('frequency', 'preferences', 'is_active')

    def validate_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('preferences must be a JSON object.')
        return value

