import hashlib
import uuid

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Resume(models.Model):
    """
    Deduplicated resume file storage.

    The same physical file (by SHA-256 hash) is stored once per user.
    Multiple ResumeAnalysis rows can reference the same Resume.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resumes')
    file = models.FileField(upload_to='resumes/')
    file_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text='SHA-256 hex digest for deduplication',
    )
    original_filename = models.CharField(max_length=255)
    file_size_bytes = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'file_hash'],
                name='unique_resume_per_user',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-uploaded_at']),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.user.username})"

    @staticmethod
    def compute_hash(file_obj) -> str:
        """Compute SHA-256 of an uploaded file, then reset seek position."""
        hasher = hashlib.sha256()
        for chunk in file_obj.chunks():
            hasher.update(chunk)
        file_obj.seek(0)
        return hasher.hexdigest()

    @classmethod
    def get_or_create_from_upload(cls, user, uploaded_file):
        """
        Deduplicate: if a file with the same SHA-256 already exists for this
        user, return the existing Resume. Otherwise create a new one.
        Returns (resume_instance, created_bool).
        """
        file_hash = cls.compute_hash(uploaded_file)
        try:
            existing = cls.objects.get(user=user, file_hash=file_hash)
            return existing, False
        except cls.DoesNotExist:
            resume = cls(
                user=user,
                file=uploaded_file,
                file_hash=file_hash,
                original_filename=uploaded_file.name,
                file_size_bytes=uploaded_file.size,
            )
            resume.save()
            return resume, True


class ScrapeResult(models.Model):
    """Stores the raw output from a Firecrawl scrape."""

    STATUS_PENDING = 'pending'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scrape_results')
    source_url = models.URLField(max_length=2048)
    markdown = models.TextField(blank=True)
    json_data = models.JSONField(null=True, blank=True)
    summary = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['source_url', 'status', '-created_at']),
        ]

    def __str__(self):
        return f"Scrape {self.source_url[:60]} | {self.status} | {self.created_at:%Y-%m-%d %H:%M}"

    @classmethod
    def find_cached(cls, url: str, user=None, max_age_hours: int = 24):
        """Return a recent successful scrape for the same URL by the same user, or None."""
        cutoff = timezone.now() - timezone.timedelta(hours=max_age_hours)
        qs = cls.objects.filter(
            source_url=url, status=cls.STATUS_DONE, created_at__gte=cutoff,
        )
        if user:
            qs = qs.filter(user=user)
        return qs.order_by('-created_at').first()


class LLMResponse(models.Model):
    """Stores the raw and parsed output from an LLM call."""

    STATUS_PENDING = 'pending'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='llm_responses')
    prompt_sent = models.TextField(blank=True, help_text='Exact prompt/messages sent to the LLM')
    raw_response = models.TextField(blank=True, help_text='Raw LLM output as-is')
    parsed_response = models.JSONField(null=True, blank=True, help_text='Validated JSON result')
    model_used = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"LLM {self.model_used} | {self.status} | {self.created_at:%Y-%m-%d %H:%M}"


class ActiveAnalysisManager(models.Manager):
    """Default manager — excludes soft-deleted analyses."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class ResumeAnalysis(models.Model):
    JD_INPUT_TEXT = 'text'
    JD_INPUT_URL = 'url'
    JD_INPUT_FORM = 'form'
    JD_INPUT_CHOICES = [
        (JD_INPUT_TEXT, 'Raw Text'),
        (JD_INPUT_URL, 'URL'),
        (JD_INPUT_FORM, 'Structured Form'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    # Pipeline step tracking — allows resuming interrupted analyses
    STEP_PENDING = 'pending'
    STEP_PDF_EXTRACT = 'pdf_extract'
    STEP_JD_SCRAPE = 'jd_scrape'
    STEP_LLM_CALL = 'llm_call'
    STEP_PARSE_RESULT = 'parse_result'
    STEP_DONE = 'done'
    STEP_FAILED = 'failed'
    STEP_CHOICES = [
        (STEP_PENDING, 'Pending'),
        (STEP_PDF_EXTRACT, 'Extracting PDF'),
        (STEP_JD_SCRAPE, 'Scraping JD'),
        (STEP_LLM_CALL, 'Calling LLM'),
        (STEP_PARSE_RESULT, 'Parsing Result'),
        (STEP_DONE, 'Done'),
        (STEP_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='analyses')
    resume_file = models.FileField(upload_to='resumes/')
    resume = models.ForeignKey(
        Resume, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='analyses',
        help_text='Deduplicated resume reference',
    )
    resume_text = models.TextField(blank=True)
    deleted_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text='Soft-delete timestamp; NULL = active',
    )

    # Job description inputs
    jd_input_type = models.CharField(max_length=10, choices=JD_INPUT_CHOICES)
    jd_text = models.TextField(blank=True, help_text='Raw job description text')
    jd_url = models.URLField(blank=True, help_text='URL to job posting')
    jd_role = models.CharField(max_length=255, blank=True, help_text='Job role/title')
    jd_company = models.CharField(max_length=255, blank=True)
    jd_skills = models.TextField(blank=True, help_text='Comma-separated required skills')
    jd_experience_years = models.PositiveSmallIntegerField(null=True, blank=True)
    jd_industry = models.CharField(max_length=255, blank=True)
    jd_extra_details = models.TextField(blank=True, help_text='Any other relevant details')

    # Resolved job description (after fetching URL or assembling form fields)
    resolved_jd = models.TextField(blank=True)

    # Linked artifacts
    scrape_result = models.ForeignKey(
        ScrapeResult, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='analyses',
    )
    llm_response = models.ForeignKey(
        LLMResponse, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='analyses',
    )

    # Analysis results
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    pipeline_step = models.CharField(max_length=20, choices=STEP_CHOICES, default=STEP_PENDING)
    error_message = models.TextField(blank=True)

    # New schema fields
    overall_grade = models.CharField(max_length=2, blank=True, help_text='Letter grade A-F')
    scores = models.JSONField(null=True, blank=True, help_text='generic_ats, workday_ats, greenhouse_ats, keyword_match_percent')
    ats_disclaimers = models.JSONField(null=True, blank=True)
    keyword_analysis = models.JSONField(null=True, blank=True, help_text='matched_keywords, missing_keywords, recommended_to_add')
    section_feedback = models.JSONField(null=True, blank=True, help_text='Array of per-section feedback objects')
    sentence_suggestions = models.JSONField(null=True, blank=True, help_text='Array of original/suggested/reason objects')
    formatting_flags = models.JSONField(null=True, blank=True, help_text='Array of formatting issues')
    quick_wins = models.JSONField(null=True, blank=True, help_text='Array of priority/action objects')
    summary = models.TextField(blank=True, help_text='2-3 sentence overall summary')

    # Kept for backward compat in dashboard stats (generic_ats score is copied here)
    ats_score = models.PositiveSmallIntegerField(null=True, blank=True)

    ai_provider_used = models.CharField(max_length=50, blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True, help_text='Celery task ID for tracking')
    report_pdf = models.FileField(upload_to='reports/', blank=True, help_text='Pre-generated PDF report (stored in R2)')
    share_token = models.UUIDField(
        null=True, blank=True, unique=True,
        help_text='Public share token — when set, analysis is viewable at /api/shared/<token>/',
    )
    credits_deducted = models.BooleanField(
        default=False,
        help_text='Whether credits were deducted for this analysis. Prevents double-deduction on Celery redelivery.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Managers — 'objects' is the default (active only); 'all_objects' includes soft-deleted
    objects = ActiveAnalysisManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['-created_at']
        default_manager_name = 'objects'
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status', 'updated_at']),
            models.Index(fields=['user', 'deleted_at']),
            models.Index(fields=['user', 'status', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} | {self.overall_grade or '?'} ({self.ats_score or '?'}) | {self.created_at:%Y-%m-%d}"

    def soft_delete(self):
        """
        Soft-delete this analysis:
        - Set deleted_at timestamp
        - Clear heavy text fields to reclaim space
        - Delete report_pdf from storage
        - Delete orphaned ScrapeResult and LLMResponse
        """
        self.deleted_at = timezone.now()

        # Clear heavy fields — keep lightweight metadata for analytics
        self.resume_text = ''
        self.resolved_jd = ''
        self.jd_text = ''

        # Delete report PDF from storage (R2)
        if self.report_pdf:
            try:
                self.report_pdf.delete(save=False)
            except Exception:
                pass  # Don't fail soft-delete if storage cleanup fails

        # Delete orphaned ScrapeResult
        if self.scrape_result:
            scrape = self.scrape_result
            self.scrape_result = None
            if not scrape.analyses.exclude(pk=self.pk).exists():
                scrape.delete()

        # Delete orphaned LLMResponse
        if self.llm_response:
            llm = self.llm_response
            self.llm_response = None
            if not llm.analyses.exclude(pk=self.pk).exists():
                llm.delete()

        self.save(update_fields=[
            'deleted_at', 'resume_text', 'resolved_jd', 'jd_text',
            'report_pdf', 'scrape_result', 'llm_response',
        ])


class Job(models.Model):
    """
    Tracked job posting — linked to a user and optionally a resume.
    Used for matching relevant jobs from the internet and sending
    notifications to the user.
    """

    RELEVANCE_PENDING = 'pending'
    RELEVANCE_RELEVANT = 'relevant'
    RELEVANCE_IRRELEVANT = 'irrelevant'
    RELEVANCE_CHOICES = [
        (RELEVANCE_PENDING, 'Pending'),
        (RELEVANCE_RELEVANT, 'Relevant'),
        (RELEVANCE_IRRELEVANT, 'Irrelevant'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs')
    resume = models.ForeignKey(
        Resume, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='jobs',
        help_text='Resume used for matching this job',
    )
    job_url = models.URLField(max_length=2048, help_text='URL of the job posting')
    title = models.CharField(max_length=500, blank=True, help_text='Job title/role')
    company = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True, help_text='Job description snippet')
    relevance = models.CharField(
        max_length=15,
        choices=RELEVANCE_CHOICES,
        default=RELEVANCE_PENDING,
        db_index=True,
        help_text='User feedback on job relevance',
    )
    source = models.CharField(max_length=100, blank=True, help_text='Where the job was found (e.g. linkedin, indeed)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'relevance']),
        ]

    def __str__(self):
        return f"{self.title or self.job_url[:60]} ({self.user.username})"


class GeneratedResume(models.Model):
    """
    AI-generated improved resume based on analysis findings.

    The LLM rewrites the user's resume incorporating all improvements
    identified in the analysis report (missing keywords, sentence rewrites,
    section feedback, quick wins). Output is rendered as ATS-optimized PDF/DOCX.
    """

    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    FORMAT_PDF = 'pdf'
    FORMAT_DOCX = 'docx'
    FORMAT_CHOICES = [
        (FORMAT_PDF, 'PDF'),
        (FORMAT_DOCX, 'DOCX'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis = models.ForeignKey(
        ResumeAnalysis, on_delete=models.CASCADE,
        related_name='generated_resumes',
        help_text='The analysis whose findings drive the resume rewrite',
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='generated_resumes')
    template = models.SlugField(
        max_length=50, default='ats_classic',
        help_text='Template slug (e.g. ats_classic, modern_clean)',
    )
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default=FORMAT_PDF)
    file = models.FileField(
        upload_to='generated_resumes/', blank=True,
        help_text='Generated resume file (stored in R2)',
    )
    llm_response = models.ForeignKey(
        LLMResponse, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='generated_resumes',
        help_text='LLM response for the rewrite call',
    )
    resume_content = models.JSONField(
        null=True, blank=True,
        help_text='Structured resume JSON (contact, summary, experience, education, skills, etc.)',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    credits_deducted = models.BooleanField(
        default=False,
        help_text='Whether credits were deducted. Prevents double-deduction on retry.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['analysis', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"Generated resume for analysis #{self.analysis_id} ({self.template}, {self.format})"


# ── Phase 11: Smart Job Alerts ────────────────────────────────────────────────


class JobSearchProfile(models.Model):
    """
    LLM-extracted job search criteria from a resume.
    One profile per resume — updated when the user edits and re-triggers extraction.
    """

    resume = models.OneToOneField(
        Resume, on_delete=models.CASCADE,
        related_name='job_search_profile',
        help_text='Resume this profile was extracted from',
    )
    titles = models.JSONField(default=list, help_text='List of target job titles')
    skills = models.JSONField(default=list, help_text='Key skills extracted from resume')
    seniority = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('junior', 'Junior'),
            ('mid', 'Mid'),
            ('senior', 'Senior'),
            ('lead', 'Lead'),
            ('executive', 'Executive'),
        ],
        help_text='Seniority level inferred from resume',
    )
    industries = models.JSONField(default=list, help_text='Target industries')
    locations = models.JSONField(default=list, help_text='Preferred work locations')
    experience_years = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Years of experience inferred from resume',
    )
    raw_extraction = models.JSONField(
        null=True, blank=True,
        help_text='Full LLM output for debugging / re-processing',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"JobSearchProfile for {self.resume.original_filename} ({self.resume.user.username})"


class JobAlert(models.Model):
    """
    A user's job alert subscription linked to a specific resume.
    The system periodically discovers matching jobs and notifies the user.
    """

    FREQUENCY_DAILY = 'daily'
    FREQUENCY_WEEKLY = 'weekly'
    FREQUENCY_CHOICES = [
        (FREQUENCY_DAILY, 'Daily'),
        (FREQUENCY_WEEKLY, 'Weekly'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='job_alerts')
    resume = models.ForeignKey(
        Resume, on_delete=models.CASCADE,
        related_name='job_alerts',
        help_text='Resume used for job matching',
    )
    frequency = models.CharField(
        max_length=10, choices=FREQUENCY_CHOICES, default=FREQUENCY_WEEKLY,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    preferences = models.JSONField(
        default=dict,
        help_text=(
            'Alert preferences: remote_ok (bool), location (str), '
            'salary_min (int), excluded_companies (list)'
        ),
    )
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['is_active', 'next_run_at']),
        ]

    def __str__(self):
        return f"JobAlert {self.id} ({self.user.username}, {self.frequency})"

    def set_next_run(self):
        """Update next_run_at based on frequency, starting from now."""
        now = timezone.now()
        if self.frequency == self.FREQUENCY_DAILY:
            self.next_run_at = now + timezone.timedelta(days=1)
        else:
            self.next_run_at = now + timezone.timedelta(weeks=1)


class DiscoveredJob(models.Model):
    """
    A job posting discovered from an external source (SerpAPI, Adzuna, etc.).
    Global — not per-user. Deduplicated by (source, external_id).
    """

    SOURCE_SERPAPI = 'serpapi'
    SOURCE_ADZUNA = 'adzuna'
    SOURCE_CHOICES = [
        (SOURCE_SERPAPI, 'SerpAPI (Google Jobs)'),
        (SOURCE_ADZUNA, 'Adzuna'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, db_index=True)
    external_id = models.CharField(
        max_length=255,
        help_text='Unique job ID from the source API',
    )
    url = models.URLField(max_length=2048)
    title = models.CharField(max_length=500, blank=True)
    company = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
    salary_range = models.CharField(max_length=255, blank=True)
    description_snippet = models.TextField(blank=True, help_text='Short job description excerpt')
    posted_at = models.DateTimeField(null=True, blank=True)
    raw_data = models.JSONField(null=True, blank=True, help_text='Full raw API response for this job')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'],
                name='unique_discovered_job_per_source',
            ),
        ]
        indexes = [
            models.Index(fields=['source', 'external_id']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.title or self.url[:60]} @ {self.company} [{self.source}]"


class JobMatch(models.Model):
    """
    Junction between a JobAlert and a DiscoveredJob.
    Stores the LLM relevance score and user feedback.
    """

    FEEDBACK_PENDING = 'pending'
    FEEDBACK_RELEVANT = 'relevant'
    FEEDBACK_IRRELEVANT = 'irrelevant'
    FEEDBACK_APPLIED = 'applied'
    FEEDBACK_DISMISSED = 'dismissed'
    FEEDBACK_CHOICES = [
        (FEEDBACK_PENDING, 'Pending'),
        (FEEDBACK_RELEVANT, 'Relevant'),
        (FEEDBACK_IRRELEVANT, 'Irrelevant'),
        (FEEDBACK_APPLIED, 'Applied'),
        (FEEDBACK_DISMISSED, 'Dismissed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_alert = models.ForeignKey(
        JobAlert, on_delete=models.CASCADE,
        related_name='matches',
    )
    discovered_job = models.ForeignKey(
        DiscoveredJob, on_delete=models.CASCADE,
        related_name='matches',
    )
    relevance_score = models.PositiveSmallIntegerField(
        help_text='LLM relevance score 0-100',
    )
    match_reason = models.TextField(
        blank=True,
        help_text='LLM-generated reason why this job matches the resume',
    )
    user_feedback = models.CharField(
        max_length=15,
        choices=FEEDBACK_CHOICES,
        default=FEEDBACK_PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-relevance_score', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['job_alert', 'discovered_job'],
                name='unique_match_per_alert',
            ),
        ]
        indexes = [
            models.Index(fields=['job_alert', '-relevance_score']),
            models.Index(fields=['job_alert', 'user_feedback']),
        ]

    def __str__(self):
        return f"Match: {self.discovered_job.title[:40]} → alert {self.job_alert_id} (score={self.relevance_score})"


class JobAlertRun(models.Model):
    """
    Audit log entry for each discovery + matching pipeline run for a JobAlert.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_alert = models.ForeignKey(
        JobAlert, on_delete=models.CASCADE,
        related_name='runs',
    )
    jobs_discovered = models.PositiveIntegerField(default=0)
    jobs_matched = models.PositiveIntegerField(default=0)
    notification_sent = models.BooleanField(default=False)
    credits_used = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job_alert', '-created_at']),
        ]

    def __str__(self):
        return f"Run {self.id} for alert {self.job_alert_id} ({self.jobs_matched}/{self.jobs_discovered} matched)"
