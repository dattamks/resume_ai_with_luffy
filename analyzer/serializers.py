from rest_framework import serializers
from django.conf import settings

from .models import ResumeAnalysis, ScrapeResult, LLMResponse, Resume, GeneratedResume, JobAlert, JobMatch, DiscoveredJob, JobAlertRun, JobSearchProfile, ResumeVersion, InterviewPrep, CoverLetter, ResumeTemplate, ResumeChat, ResumeChatMessage


class ResumeSerializer(serializers.ModelSerializer):
    """Read-only serializer for the Resume model."""
    active_analysis_count = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    days_since_upload = serializers.SerializerMethodField()
    last_analyzed_at = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = (
            'id', 'original_filename', 'file_size_bytes',
            'uploaded_at', 'active_analysis_count', 'file_url',
            'days_since_upload', 'last_analyzed_at',
        )
        read_only_fields = fields

    def get_active_analysis_count(self, obj):
        # Annotated by the view queryset for efficiency
        return getattr(obj, 'active_analysis_count', 0)

    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None

    def get_days_since_upload(self, obj):
        from django.utils import timezone
        delta = timezone.now() - obj.uploaded_at
        return delta.days

    def get_last_analyzed_at(self, obj):
        latest = obj.analyses.filter(
            deleted_at__isnull=True,
            status='done',
        ).order_by('-created_at').values_list('created_at', flat=True).first()
        return latest


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
            'prompt_tokens', 'completion_tokens', 'total_tokens',
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
    ai_response_time_seconds = serializers.SerializerMethodField()

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
            'parsed_content',
            'ai_provider_used',
            'ai_response_time_seconds',
            'report_pdf_url',
            'share_token',
            'share_url',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_ai_response_time_seconds(self, obj):
        llm = getattr(obj, 'llm_response', None)
        if llm and llm.duration_seconds is not None:
            return round(llm.duration_seconds, 2)
        return None

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
            path = f'/api/v1/shared/{obj.share_token}/'
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
            path = f'/api/v1/shared/{obj.share_token}/'
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


class ResumeTemplateSerializer(serializers.ModelSerializer):
    """Read-only serializer for the template marketplace listing."""
    preview_image_url = serializers.SerializerMethodField()
    accessible = serializers.SerializerMethodField()

    class Meta:
        model = ResumeTemplate
        fields = [
            'id', 'name', 'slug', 'description', 'category',
            'preview_image_url', 'is_premium', 'is_active',
            'sort_order', 'accessible',
        ]
        read_only_fields = fields

    def get_preview_image_url(self, obj):
        if obj.preview_image:
            return obj.preview_image.url
        return None

    def get_accessible(self, obj):
        """Whether the requesting user can use this template."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return not obj.is_premium
        if not obj.is_premium:
            return True
        # Check user's plan premium_templates flag
        profile = getattr(request.user, 'profile', None)
        if profile and profile.plan:
            return profile.plan.premium_templates
        return False


class GeneratedResumeCreateSerializer(serializers.Serializer):
    """Serializer for requesting a resume generation."""
    template = serializers.SlugField(max_length=50, default='ats_classic')
    format = serializers.ChoiceField(
        choices=[('pdf', 'PDF'), ('docx', 'DOCX')],
        default='pdf',
    )

    def validate_template(self, value):
        """Validate template exists in DB and is active."""
        try:
            template_obj = ResumeTemplate.objects.get(slug=value, is_active=True)
        except ResumeTemplate.DoesNotExist:
            active_slugs = list(
                ResumeTemplate.objects.filter(is_active=True)
                .values_list('slug', flat=True)
            )
            raise serializers.ValidationError(
                f'Template "{value}" is not available. '
                f'Available: {", ".join(active_slugs) or "none"}'
            )
        # Stash the template object for plan gating in the view
        self._template_obj = template_obj
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
            'id', 'source', 'title', 'company', 'company_entity', 'location',
            'salary_range', 'description_snippet', 'url', 'source_page_url',
            'posted_at', 'created_at',
            # Enriched fields
            'skills_required', 'skills_nice_to_have',
            'experience_years_min', 'experience_years_max',
            'employment_type', 'remote_policy', 'seniority_level',
            'industry', 'education_required',
            'salary_min_usd', 'salary_max_usd',
        )
        read_only_fields = fields


class JobMatchSerializer(serializers.ModelSerializer):
    """Serializer for a job match result (includes nested DiscoveredJob)."""
    job = DiscoveredJobSerializer(source='discovered_job', read_only=True)

    class Meta:
        model = JobMatch
        fields = (
            'id', 'job', 'relevance_score', 'match_reason',
            'user_feedback', 'feedback_reason', 'created_at',
        )
        read_only_fields = ('id', 'job', 'relevance_score', 'match_reason', 'created_at')


class JobMatchFeedbackSerializer(serializers.ModelSerializer):
    """Write-only — update user_feedback and optional feedback_reason on a match."""
    class Meta:
        model = JobMatch
        fields = ('user_feedback', 'feedback_reason')

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
    total_matches = serializers.SerializerMethodField()
    resume_filename = serializers.CharField(source='resume.original_filename', read_only=True)
    search_profile = JobSearchProfileSerializer(
        source='resume.job_search_profile', read_only=True, default=None,
    )

    class Meta:
        model = JobAlert
        fields = (
            'id', 'resume', 'resume_filename', 'frequency', 'is_active',
            'preferences', 'last_run_at', 'next_run_at',
            'search_profile', 'last_run', 'total_matches', 'created_at',
        )
        read_only_fields = (
            'id', 'resume_filename', 'last_run_at', 'next_run_at',
            'search_profile', 'last_run', 'total_matches', 'created_at',
        )

    def get_last_run(self, instance):
        latest = instance.runs.order_by('-created_at').first()
        return JobAlertRunSerializer(latest).data if latest else None

    def get_total_matches(self, instance):
        return getattr(instance, 'total_matches', instance.matches.count())


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
        # Validate known preference keys
        allowed = {'remote_ok', 'location', 'salary_min', 'excluded_companies', 'priority_companies'}
        unknown = set(value.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                f'Unknown preference keys: {", ".join(sorted(unknown))}. '
                f'Allowed: {", ".join(sorted(allowed))}'
            )
        for list_key in ('excluded_companies', 'priority_companies'):
            if list_key in value and not isinstance(value[list_key], list):
                raise serializers.ValidationError(f'{list_key} must be a list of strings.')
        return value


class JobAlertUpdateSerializer(serializers.ModelSerializer):
    """Update frequency and preferences on an existing alert."""
    class Meta:
        model = JobAlert
        fields = ('frequency', 'preferences', 'is_active')

    def validate_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('preferences must be a JSON object.')
        allowed = {'remote_ok', 'location', 'salary_min', 'excluded_companies', 'priority_companies'}
        unknown = set(value.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                f'Unknown preference keys: {", ".join(sorted(unknown))}. '
                f'Allowed: {", ".join(sorted(allowed))}'
            )
        for list_key in ('excluded_companies', 'priority_companies'):
            if list_key in value and not isinstance(value[list_key], list):
                raise serializers.ValidationError(f'{list_key} must be a list of strings.')
        return value


# ── Phase 12: Notifications ──────────────────────────────────────────────────

class NotificationSerializer(serializers.ModelSerializer):
    """Read-only serializer for in-app notifications."""
    class Meta:
        model = None  # Set dynamically to avoid circular import at import time
        fields = (
            'id', 'title', 'body', 'link', 'is_read',
            'notification_type', 'metadata', 'created_at',
        )
        read_only_fields = fields

    def __init__(self, *args, **kwargs):
        from .models import Notification
        self.Meta.model = Notification
        super().__init__(*args, **kwargs)


class NotificationMarkReadSerializer(serializers.Serializer):
    """Mark one or all notifications as read."""
    notification_id = serializers.UUIDField(required=False, help_text='Specific notification ID. Omit to mark all as read.')
    mark_all = serializers.BooleanField(required=False, default=False)


# ── Resume Version History ───────────────────────────────────────────────────

class ResumeVersionSerializer(serializers.ModelSerializer):
    """Read-only serializer for resume version history."""
    resume_filename = serializers.CharField(source='resume.original_filename', read_only=True)
    resume_id = serializers.UUIDField(source='resume.id', read_only=True)
    previous_resume_id = serializers.UUIDField(source='previous_resume.id', read_only=True, default=None)

    class Meta:
        model = ResumeVersion
        fields = (
            'id', 'resume_id', 'resume_filename', 'previous_resume_id',
            'version_number', 'change_summary',
            'best_ats_score', 'best_grade', 'created_at',
        )
        read_only_fields = fields


# ── Interview Prep ───────────────────────────────────────────────────────────

class InterviewPrepSerializer(serializers.ModelSerializer):
    """Read-only serializer for interview prep results."""

    class Meta:
        model = InterviewPrep
        fields = (
            'id', 'analysis', 'questions', 'tips',
            'status', 'error_message', 'created_at',
        )
        read_only_fields = fields


class InterviewPrepCreateSerializer(serializers.Serializer):
    """No extra fields needed — analysis ID comes from URL."""
    pass


# ── Cover Letter ─────────────────────────────────────────────────────────────

class CoverLetterSerializer(serializers.ModelSerializer):
    """Read-only serializer for cover letter results."""
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = CoverLetter
        fields = (
            'id', 'analysis', 'tone', 'content', 'content_html',
            'status', 'error_message', 'file_url', 'created_at',
        )
        read_only_fields = fields

    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None


class CoverLetterCreateSerializer(serializers.Serializer):
    """Serializer for requesting a cover letter generation."""
    tone = serializers.ChoiceField(
        choices=[('professional', 'Professional'), ('conversational', 'Conversational'), ('enthusiastic', 'Enthusiastic')],
        default='professional',
    )


# ── Bulk Analysis ────────────────────────────────────────────────────────────

class BulkAnalysisCreateSerializer(serializers.Serializer):
    """
    Analyze one resume against multiple job descriptions at once.
    """
    resume_file = serializers.FileField(required=False)
    resume_id = serializers.UUIDField(required=False)
    job_descriptions = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        max_length=10,
        help_text='Array of JD objects, each with jd_input_type + corresponding fields.',
    )

    def validate_resume_file(self, value):
        max_bytes = settings.MAX_RESUME_SIZE_MB * 1024 * 1024
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f'Resume file must be under {settings.MAX_RESUME_SIZE_MB}MB.'
            )
        if not value.name.lower().endswith('.pdf'):
            raise serializers.ValidationError('Only PDF files are accepted.')
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

        # Validate each JD entry
        for i, jd in enumerate(attrs.get('job_descriptions', [])):
            jd_type = jd.get('jd_input_type')
            if jd_type not in ('text', 'url', 'form'):
                raise serializers.ValidationError(
                    {f'job_descriptions[{i}]': 'jd_input_type must be "text", "url", or "form".'}
                )
            if jd_type == 'text' and not jd.get('jd_text'):
                raise serializers.ValidationError(
                    {f'job_descriptions[{i}]': 'jd_text is required when jd_input_type is "text".'}
                )
            if jd_type == 'url' and not jd.get('jd_url'):
                raise serializers.ValidationError(
                    {f'job_descriptions[{i}]': 'jd_url is required when jd_input_type is "url".'}
                )
            if jd_type == 'form' and not jd.get('jd_role'):
                raise serializers.ValidationError(
                    {f'job_descriptions[{i}]': 'jd_role is required when jd_input_type is "form".'}
                )

        return attrs


# ── Resume Chat (Conversational Builder) ──────────────────────────────────────


class ResumeChatMessageSerializer(serializers.ModelSerializer):
    """Read-only serializer for individual chat messages."""

    class Meta:
        model = ResumeChatMessage
        fields = (
            'id', 'role', 'content', 'ui_spec',
            'extracted_data', 'step', 'created_at',
        )
        read_only_fields = fields


class ResumeChatSerializer(serializers.ModelSerializer):
    """Read-only serializer for a chat session with messages."""
    messages = ResumeChatMessageSerializer(many=True, read_only=True)
    step_number = serializers.IntegerField(read_only=True)
    total_steps = serializers.IntegerField(read_only=True)
    generated_resume_url = serializers.SerializerMethodField()

    class Meta:
        model = ResumeChat
        fields = (
            'id', 'source', 'current_step', 'status',
            'target_role', 'target_company', 'target_industry',
            'experience_level', 'resume_data',
            'step_number', 'total_steps',
            'generated_resume_url', 'credits_deducted',
            'created_at', 'updated_at', 'messages',
        )
        read_only_fields = fields

    def get_generated_resume_url(self, obj):
        if obj.generated_resume and obj.generated_resume.file:
            return obj.generated_resume.file.url
        return None


class ResumeChatListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing chat sessions (no messages)."""
    step_number = serializers.IntegerField(read_only=True)
    total_steps = serializers.IntegerField(read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        model = ResumeChat
        fields = (
            'id', 'source', 'current_step', 'status',
            'target_role', 'step_number', 'total_steps',
            'name', 'created_at', 'updated_at',
        )
        read_only_fields = fields

    def get_name(self, obj):
        contact = (obj.resume_data or {}).get('contact', {})
        return contact.get('name', '') or 'Untitled Resume'


class ResumeChatStartSerializer(serializers.Serializer):
    """Input serializer for starting a new chat session."""
    source = serializers.ChoiceField(
        choices=[
            ('scratch', 'Start Fresh'),
            ('profile', 'From Profile Data'),
            ('previous', 'From Previous Resume'),
        ],
        default='scratch',
    )
    base_resume_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        source = attrs.get('source')
        base_resume_id = attrs.get('base_resume_id')
        if source == 'previous' and not base_resume_id:
            raise serializers.ValidationError(
                {'base_resume_id': 'Required when source is "previous".'}
            )
        return attrs


class ResumeChatSubmitSerializer(serializers.Serializer):
    """Input serializer for submitting an action in a chat step."""
    action = serializers.CharField(max_length=50)
    payload = serializers.DictField(required=False, default=dict)


class ResumeChatFinalizeSerializer(serializers.Serializer):
    """Input serializer for finalizing a chat session (generate PDF/DOCX)."""
    template = serializers.SlugField(max_length=50, default='ats_classic')
    format = serializers.ChoiceField(
        choices=[('pdf', 'PDF'), ('docx', 'DOCX')],
        default='pdf',
    )

    def validate_template(self, value):
        """Validate template exists and is active."""
        try:
            template_obj = ResumeTemplate.objects.get(slug=value, is_active=True)
        except ResumeTemplate.DoesNotExist:
            active_slugs = list(
                ResumeTemplate.objects.filter(is_active=True)
                .values_list('slug', flat=True)
            )
            raise serializers.ValidationError(
                f'Template "{value}" is not available. '
                f'Available: {", ".join(active_slugs) or "none"}'
            )
        self._template_obj = template_obj
        return value
