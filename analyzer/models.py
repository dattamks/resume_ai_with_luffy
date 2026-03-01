import hashlib
import uuid

from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# pgvector — only enabled when BOTH the Python package is available
# AND the database backend is PostgreSQL (not SQLite during tests).
_HAS_PGVECTOR = False
_db_engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
if 'postgresql' in _db_engine:
    try:
        from pgvector.django import VectorField, HnswIndex
        _HAS_PGVECTOR = True
    except ImportError:
        pass


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
        If a resume with the same filename but different content exists,
        create a version history link.
        Returns (resume_instance, created_bool).
        """
        file_hash = cls.compute_hash(uploaded_file)
        try:
            existing = cls.objects.get(user=user, file_hash=file_hash)
            return existing, False
        except cls.DoesNotExist:
            # Check for previous version (same filename, different content)
            previous = cls.objects.filter(
                user=user,
                original_filename=uploaded_file.name,
            ).order_by('-uploaded_at').first()

            resume = cls(
                user=user,
                file=uploaded_file,
                file_hash=file_hash,
                original_filename=uploaded_file.name,
                file_size_bytes=uploaded_file.size,
            )
            resume.save()

            # Create version history entry
            if previous:
                # Find the latest version number for this lineage
                prev_version = ResumeVersion.objects.filter(
                    user=user, resume=previous,
                ).first()
                version_num = (prev_version.version_number + 1) if prev_version else 2

                # Get best score from previous resume's analyses
                prev_best = previous.analyses.filter(
                    deleted_at__isnull=True, status='done',
                ).order_by('-ats_score').values_list('ats_score', 'overall_grade').first()

                # Ensure previous resume has a version entry
                ResumeVersion.objects.get_or_create(
                    user=user, resume=previous,
                    defaults={
                        'version_number': version_num - 1,
                        'best_ats_score': prev_best[0] if prev_best else None,
                        'best_grade': prev_best[1] if prev_best else '',
                    },
                )

                ResumeVersion.objects.create(
                    user=user,
                    resume=resume,
                    previous_resume=previous,
                    version_number=version_num,
                    change_summary=f'Updated version of {uploaded_file.name}',
                )
            else:
                # First version — create initial version entry
                ResumeVersion.objects.create(
                    user=user,
                    resume=resume,
                    version_number=1,
                )

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

    # ── Token usage tracking ────────────────────────────────────────────────
    prompt_tokens = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Number of tokens in the prompt (from API response.usage).',
    )
    completion_tokens = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Number of tokens in the completion (from API response.usage).',
    )
    total_tokens = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Total tokens used (prompt + completion).',
    )
    estimated_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True,
        help_text='Estimated cost in USD based on model pricing.',
    )

    # ── Call context ────────────────────────────────────────────────────────
    call_purpose = models.CharField(
        max_length=50, blank=True, default='',
        help_text='Purpose of this LLM call (analysis, resume_rewrite, job_matching, profile_extraction, job_extraction).',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['call_purpose', '-created_at']),
        ]

    def __str__(self):
        tokens = f' {self.total_tokens}tok' if self.total_tokens else ''
        return f"LLM {self.model_used} | {self.status}{tokens} | {self.created_at:%Y-%m-%d %H:%M}"


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
    STEP_RESUME_PARSE = 'resume_parse'
    STEP_DONE = 'done'
    STEP_FAILED = 'failed'
    STEP_CHOICES = [
        (STEP_PENDING, 'Pending'),
        (STEP_PDF_EXTRACT, 'Extracting PDF'),
        (STEP_JD_SCRAPE, 'Scraping JD'),
        (STEP_LLM_CALL, 'Calling LLM'),
        (STEP_PARSE_RESULT, 'Parsing Result'),
        (STEP_RESUME_PARSE, 'Parsing Resume Data'),
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

    # Structured resume data extracted from resume_text by LLM
    parsed_content = models.JSONField(
        null=True, blank=True,
        help_text='Structured resume data (contact, experience, education, skills, etc.) extracted from resume_text',
    )

    # Kept for backward compat in dashboard stats (generic_ats score is copied here)
    ats_score = models.PositiveSmallIntegerField(null=True, blank=True)

    ai_provider_used = models.CharField(max_length=50, blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True, help_text='Celery task ID for tracking')
    report_pdf = models.FileField(upload_to='reports/', blank=True, help_text='Pre-generated PDF report (stored in R2)')
    share_token = models.UUIDField(
        null=True, blank=True, unique=True,
        help_text='Public share token — when set, analysis is viewable at /api/v1/shared/<token>/',
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
        self.parsed_content = None

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
            'parsed_content', 'report_pdf', 'scrape_result', 'llm_response',
        ])


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
        null=True, blank=True,
        related_name='generated_resumes',
        help_text='The analysis whose findings drive the resume rewrite (NULL for builder-created resumes)',
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


# ── Company Intelligence ─────────────────────────────────────────────────────


class Company(models.Model):
    """
    A top-level brand / parent company (e.g., Google, Infosys, Stripe).

    This is the umbrella identity. Actual legal entities that operate in
    specific countries are stored as CompanyEntity records linked here.
    A company with no separate country entities still gets one CompanyEntity
    (the HQ itself).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=255, unique=True,
        help_text='Brand / common name (e.g. "Google", "TCS", "Stripe")',
    )
    slug = models.SlugField(
        max_length=255, unique=True,
        help_text='URL-safe identifier, auto-generated from name',
    )
    description = models.TextField(
        blank=True,
        help_text='Brief company description for display',
    )
    logo = models.URLField(
        max_length=2048, blank=True,
        help_text='URL to company logo image',
    )
    industry = models.CharField(max_length=100, blank=True)
    founded_year = models.PositiveSmallIntegerField(null=True, blank=True)

    SIZE_STARTUP = 'startup'
    SIZE_SMALL = 'small'
    SIZE_MID = 'mid'
    SIZE_LARGE = 'large'
    SIZE_ENTERPRISE = 'enterprise'
    SIZE_CHOICES = [
        (SIZE_STARTUP, 'Startup (1-50)'),
        (SIZE_SMALL, 'Small (51-200)'),
        (SIZE_MID, 'Mid-size (201-1000)'),
        (SIZE_LARGE, 'Large (1001-10000)'),
        (SIZE_ENTERPRISE, 'Enterprise (10000+)'),
    ]
    company_size = models.CharField(
        max_length=12, blank=True, choices=SIZE_CHOICES,
    )
    headquarters_country = models.CharField(max_length=100, blank=True)
    headquarters_city = models.CharField(max_length=100, blank=True)
    linkedin_url = models.URLField(max_length=2048, blank=True)
    glassdoor_url = models.URLField(max_length=2048, blank=True)
    tech_stack = models.JSONField(
        default=list, blank=True,
        help_text='Known tech stack ["Python", "Kubernetes", ...]',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive companies are hidden from suggestions',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Company'
        verbose_name_plural = 'Companies'

    def __str__(self):
        return self.name


class CompanyEntity(models.Model):
    """
    A legal / operating entity of a Company in a specific country.

    Examples:
      Company "Stripe"  → CompanyEntity "Stripe Inc" (US)
                         → CompanyEntity "Stripe India Pvt Ltd" (India)
      Company "SAP"     → CompanyEntity "SAP SE" (Germany)
                         → CompanyEntity "SAP Labs India" (India)

    Each entity can have its own career pages, websites, and is treated
    independently for crawling and matching purposes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='entities',
        help_text='Parent brand / company',
    )
    legal_name = models.CharField(
        max_length=500, blank=True,
        help_text='Registered legal name (e.g. "Google India Pvt Ltd")',
    )
    display_name = models.CharField(
        max_length=255,
        help_text='Short display name (e.g. "Google India", "Stripe US")',
    )
    operating_country = models.CharField(
        max_length=100,
        help_text='Country this entity operates in (e.g. "India", "United States")',
    )
    operating_city = models.CharField(max_length=100, blank=True)
    is_headquarters = models.BooleanField(
        default=False,
        help_text='Whether this entity is the global HQ',
    )
    is_indian_entity = models.BooleanField(
        default=False, db_index=True,
        help_text='Quick filter for Indian entities',
    )
    website = models.URLField(
        max_length=2048, blank=True,
        help_text='Corporate website for this entity (not brand site)',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company', 'operating_country']
        verbose_name = 'Company Entity'
        verbose_name_plural = 'Company Entities'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'operating_country', 'display_name'],
                name='unique_entity_per_country',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'operating_country']),
            models.Index(fields=['is_indian_entity']),
        ]

    def __str__(self):
        hq = ' (HQ)' if self.is_headquarters else ''
        return f"{self.display_name} — {self.operating_country}{hq}"


class CompanyCareerPage(models.Model):
    """
    A career page URL belonging to a CompanyEntity.

    One entity can have multiple career pages (e.g. engineering vs general,
    or region-specific sub-pages). Each active page becomes a CrawlSource
    automatically during crawl.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        CompanyEntity, on_delete=models.CASCADE, related_name='career_pages',
        help_text='The entity this career page belongs to',
    )
    url = models.URLField(
        max_length=2048,
        help_text='Career page URL (e.g. "https://careers.google.com/jobs/")',
    )
    label = models.CharField(
        max_length=100, blank=True,
        help_text='Label (e.g. "Engineering", "All Roles", "Campus")',
    )
    country = models.CharField(
        max_length=100, blank=True,
        help_text='Country this page targets (may differ from entity country)',
    )
    is_active = models.BooleanField(default=True, db_index=True)
    last_crawled_at = models.DateTimeField(null=True, blank=True)
    crawl_frequency = models.CharField(
        max_length=10,
        choices=[('daily', 'Daily'), ('weekly', 'Weekly')],
        default='weekly',
        help_text='How often to crawl this page',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['entity', 'label']
        verbose_name = 'Career Page'
        verbose_name_plural = 'Career Pages'

    def __str__(self):
        label = f' ({self.label})' if self.label else ''
        return f"{self.entity.display_name}{label} — {self.url[:60]}"


# ── Smart Job Alerts ─────────────────────────────────────────────────────────


class CrawlSource(models.Model):
    """
    Admin-managed crawl source. Each entry defines a job board or company
    career page that the daily crawl should scrape.

    Managed via Django Admin — no user-facing API.
    """

    TYPE_JOB_BOARD = 'job_board'
    TYPE_COMPANY = 'company'
    TYPE_CHOICES = [
        (TYPE_JOB_BOARD, 'Job Board'),
        (TYPE_COMPANY, 'Company Career Page'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text='Display name (e.g. "LinkedIn", "Google Careers")',
    )
    source_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_JOB_BOARD,
        help_text='Job board (uses {query}/{location} URL template) or company career page',
    )
    url_template = models.CharField(
        max_length=2048,
        help_text=(
            'URL template with {query} and {location} placeholders for job boards. '
            'Plain URL for company career pages.'
        ),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='Inactive sources are skipped during crawl',
    )
    priority = models.PositiveSmallIntegerField(
        default=10,
        help_text='Lower = crawled first. Use to prioritise important sources.',
    )
    last_crawled_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Timestamp of last successful crawl',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'name']
        verbose_name = 'Crawl Source'
        verbose_name_plural = 'Crawl Sources'

    def __str__(self):
        status = '✓' if self.is_active else '✗'
        return f"[{status}] {self.name} ({self.get_source_type_display()})"


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

    # Phase 12: embedding for pgvector similarity matching
    if _HAS_PGVECTOR:
        embedding = VectorField(
            dimensions=1536, null=True, blank=True,
            help_text='Resume text embedding for similarity matching',
        )

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
        Resume, on_delete=models.PROTECT,
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
            'salary_min (int), excluded_companies (list), '
            'priority_companies (list)'
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
    A job posting discovered from an external source (Firecrawl).
    Global — not per-user. Deduplicated by (source, external_id).
    """

    SOURCE_FIRECRAWL = 'firecrawl'
    SOURCE_CHOICES = [
        (SOURCE_FIRECRAWL, 'Firecrawl'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, db_index=True)
    external_id = models.CharField(
        max_length=255,
        help_text='Unique job ID from the source API',
    )
    source_page_url = models.URLField(
        max_length=2048, blank=True,
        help_text='The search/career page URL we crawled to discover this job',
    )
    url = models.URLField(
        max_length=2048,
        help_text='Direct link to the actual job posting / apply page',
    )
    title = models.CharField(max_length=500, blank=True)
    company = models.CharField(max_length=255, blank=True)
    company_entity = models.ForeignKey(
        CompanyEntity, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='discovered_jobs',
        help_text='Matched CompanyEntity record (linked post-crawl or via career page)',
    )
    location = models.CharField(max_length=255, blank=True)
    salary_range = models.CharField(max_length=255, blank=True)
    description_snippet = models.TextField(blank=True, help_text='Short job description excerpt')

    # ── Enriched fields (extracted by LLM during crawl) ──
    skills_required = models.JSONField(
        default=list, blank=True,
        help_text='Required skills extracted from listing ["Python", "AWS", ...]',
    )
    skills_nice_to_have = models.JSONField(
        default=list, blank=True,
        help_text='Nice-to-have / preferred skills ["Go", "Terraform", ...]',
    )
    experience_years_min = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Minimum years of experience required',
    )
    experience_years_max = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Maximum years of experience required',
    )
    EMPLOYMENT_FULL_TIME = 'full_time'
    EMPLOYMENT_PART_TIME = 'part_time'
    EMPLOYMENT_CONTRACT = 'contract'
    EMPLOYMENT_INTERNSHIP = 'internship'
    EMPLOYMENT_FREELANCE = 'freelance'
    EMPLOYMENT_CHOICES = [
        (EMPLOYMENT_FULL_TIME, 'Full Time'),
        (EMPLOYMENT_PART_TIME, 'Part Time'),
        (EMPLOYMENT_CONTRACT, 'Contract'),
        (EMPLOYMENT_INTERNSHIP, 'Internship'),
        (EMPLOYMENT_FREELANCE, 'Freelance'),
    ]
    employment_type = models.CharField(
        max_length=15, blank=True, choices=EMPLOYMENT_CHOICES,
    )
    REMOTE_ONSITE = 'onsite'
    REMOTE_HYBRID = 'hybrid'
    REMOTE_REMOTE = 'remote'
    REMOTE_CHOICES = [
        (REMOTE_ONSITE, 'On-site'),
        (REMOTE_HYBRID, 'Hybrid'),
        (REMOTE_REMOTE, 'Remote'),
    ]
    remote_policy = models.CharField(
        max_length=10, blank=True, choices=REMOTE_CHOICES,
    )
    SENIORITY_INTERN = 'intern'
    SENIORITY_JUNIOR = 'junior'
    SENIORITY_MID = 'mid'
    SENIORITY_SENIOR = 'senior'
    SENIORITY_LEAD = 'lead'
    SENIORITY_MANAGER = 'manager'
    SENIORITY_DIRECTOR = 'director'
    SENIORITY_EXECUTIVE = 'executive'
    SENIORITY_CHOICES = [
        (SENIORITY_INTERN, 'Intern'),
        (SENIORITY_JUNIOR, 'Junior'),
        (SENIORITY_MID, 'Mid-level'),
        (SENIORITY_SENIOR, 'Senior'),
        (SENIORITY_LEAD, 'Lead'),
        (SENIORITY_MANAGER, 'Manager'),
        (SENIORITY_DIRECTOR, 'Director'),
        (SENIORITY_EXECUTIVE, 'Executive'),
    ]
    seniority_level = models.CharField(
        max_length=12, blank=True, choices=SENIORITY_CHOICES,
    )
    industry = models.CharField(max_length=100, blank=True, db_index=True)
    education_required = models.CharField(
        max_length=50, blank=True,
        help_text='Minimum education (e.g. "bachelor", "master", "none")',
    )
    salary_min_usd = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='LLM-normalised annual salary lower bound in USD',
    )
    salary_max_usd = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='LLM-normalised annual salary upper bound in USD',
    )

    posted_at = models.DateTimeField(null=True, blank=True)
    raw_data = models.JSONField(null=True, blank=True, help_text='Full raw API response for this job')
    created_at = models.DateTimeField(auto_now_add=True)

    # Phase 12: embedding for pgvector similarity matching
    if _HAS_PGVECTOR:
        embedding = VectorField(
            dimensions=1536, null=True, blank=True,
            help_text='Job listing embedding for similarity matching',
        )

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
    feedback_reason = models.TextField(
        blank=True,
        help_text='User-provided reason for their feedback (used in learning loop)',
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
    credits_deducted = models.BooleanField(
        default=False,
        help_text='Whether credits were deducted for this run (for idempotent refund)',
    )
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


# ── Phase 12: Firecrawl + pgvector Job Alerts Redesign ────────────────────────


class SentAlert(models.Model):
    """
    Deduplication log — prevents resending the same job to the same user
    on the same channel. Checked before sending email or in-app notification.
    """

    CHANNEL_EMAIL = 'email'
    CHANNEL_IN_APP = 'in_app'
    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, 'Email'),
        (CHANNEL_IN_APP, 'In-App'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_alerts')
    discovered_job = models.ForeignKey(
        DiscoveredJob, on_delete=models.CASCADE,
        related_name='sent_alerts',
    )
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        help_text='Notification channel used',
    )
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'Sent Alert'
        verbose_name_plural = 'Sent Alerts'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'discovered_job', 'channel'],
                name='unique_sent_alert_per_channel',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-sent_at'], name='sentalert_user_sent_idx'),
        ]

    def __str__(self):
        return f"SentAlert({self.user.username}, {self.discovered_job.title[:30]}, {self.channel})"


class Notification(models.Model):
    """
    In-app notification store. Powers the notification bell/badge in the frontend.
    Supports multiple notification types with metadata for deep-linking.
    """

    TYPE_JOB_MATCH = 'job_match'
    TYPE_ANALYSIS_DONE = 'analysis_done'
    TYPE_RESUME_GENERATED = 'resume_generated'
    TYPE_SYSTEM = 'system'
    TYPE_CHOICES = [
        (TYPE_JOB_MATCH, 'Job Match'),
        (TYPE_ANALYSIS_DONE, 'Analysis Complete'),
        (TYPE_RESUME_GENERATED, 'Resume Generated'),
        (TYPE_SYSTEM, 'System'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    link = models.CharField(
        max_length=2048, blank=True,
        help_text='Relative URL or external link for deep-linking',
    )
    is_read = models.BooleanField(default=False, db_index=True)
    notification_type = models.CharField(
        max_length=30, choices=TYPE_CHOICES, db_index=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        indexes = [
            models.Index(fields=['user', '-created_at'], name='notification_user_created_idx'),
            models.Index(fields=['user', 'is_read', '-created_at'], name='notification_user_unread_idx'),
        ]

    def __str__(self):
        read_marker = '✓' if self.is_read else '●'
        return f"{read_marker} {self.title[:50]} ({self.user.username})"


# ── Resume Version History ───────────────────────────────────────────────────


class ResumeVersion(models.Model):
    """
    Tracks version history for resumes. Each time a user uploads a new version
    of a resume (same filename different content), a version entry is created
    linking old → new. Enables improvement timeline tracking.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resume_versions')
    resume = models.ForeignKey(
        Resume, on_delete=models.CASCADE, related_name='versions',
        help_text='The current resume in this version chain.',
    )
    previous_resume = models.ForeignKey(
        Resume, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='next_versions',
        help_text='The previous version of this resume (NULL if first version).',
    )
    version_number = models.PositiveIntegerField(
        default=1,
        help_text='Sequential version number within this resume lineage.',
    )
    change_summary = models.CharField(
        max_length=500, blank=True,
        help_text='Auto-generated or user-provided summary of changes.',
    )
    best_ats_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Best ATS score achieved with this resume version.',
    )
    best_grade = models.CharField(
        max_length=2, blank=True,
        help_text='Best overall grade achieved with this resume version.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version_number']
        verbose_name = 'Resume Version'
        verbose_name_plural = 'Resume Versions'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'resume'],
                name='unique_version_per_resume',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"v{self.version_number} — {self.resume.original_filename} ({self.user.username})"


# ── Interview Prep ───────────────────────────────────────────────────────────


class InterviewPrep(models.Model):
    """
    AI-generated interview preparation questions customized to a specific
    analysis (resume + JD combination). Leverages gap analysis to generate
    likely interview questions.
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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis = models.ForeignKey(
        ResumeAnalysis, on_delete=models.CASCADE,
        related_name='interview_preps',
        help_text='The analysis whose findings drive question generation.',
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='interview_preps')
    llm_response = models.ForeignKey(
        LLMResponse, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='interview_preps',
    )

    # Structured output
    questions = models.JSONField(
        null=True, blank=True,
        help_text='Array of question objects: {category, question, why_asked, sample_answer, difficulty}',
    )
    tips = models.JSONField(
        null=True, blank=True,
        help_text='General interview tips based on the analysis.',
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
        verbose_name = 'Interview Prep'
        verbose_name_plural = 'Interview Preps'
        indexes = [
            models.Index(fields=['analysis', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"InterviewPrep for analysis #{self.analysis_id} ({self.status})"


# ── Cover Letter ─────────────────────────────────────────────────────────────


class CoverLetter(models.Model):
    """
    AI-generated cover letter tailored to a specific analysis (resume + JD).
    Uses analysis findings to create a compelling, personalized cover letter.
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

    TONE_PROFESSIONAL = 'professional'
    TONE_CONVERSATIONAL = 'conversational'
    TONE_ENTHUSIASTIC = 'enthusiastic'
    TONE_CHOICES = [
        (TONE_PROFESSIONAL, 'Professional'),
        (TONE_CONVERSATIONAL, 'Conversational'),
        (TONE_ENTHUSIASTIC, 'Enthusiastic'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis = models.ForeignKey(
        ResumeAnalysis, on_delete=models.CASCADE,
        related_name='cover_letters',
        help_text='The analysis whose findings inform the cover letter.',
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cover_letters')
    llm_response = models.ForeignKey(
        LLMResponse, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='cover_letters',
    )

    tone = models.CharField(
        max_length=20, choices=TONE_CHOICES, default=TONE_PROFESSIONAL,
        help_text='Desired tone for the cover letter.',
    )
    content = models.TextField(
        blank=True,
        help_text='The generated cover letter text.',
    )
    content_html = models.TextField(
        blank=True,
        help_text='HTML-formatted version of the cover letter.',
    )
    file = models.FileField(
        upload_to='cover_letters/', blank=True,
        help_text='Generated cover letter PDF (stored in R2).',
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
        verbose_name = 'Cover Letter'
        verbose_name_plural = 'Cover Letters'
        indexes = [
            models.Index(fields=['analysis', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"CoverLetter for analysis #{self.analysis_id} ({self.tone}, {self.status})"


# ── Resume Templates ─────────────────────────────────────────────────────────


class ResumeTemplate(models.Model):
    """
    Admin-managed resume template metadata.

    Each template maps to a pair of renderer modules (PDF + DOCX)
    registered in the template_registry. Admin controls visibility,
    ordering, and premium gating via Django Admin.
    """

    CATEGORY_CHOICES = [
        ('professional', 'Professional'),
        ('creative', 'Creative'),
        ('academic', 'Academic'),
        ('executive', 'Executive'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100,
        help_text='Display name (e.g., "ATS Classic", "Modern Clean").',
    )
    slug = models.SlugField(
        max_length=50,
        unique=True,
        help_text='Template identifier used in API calls (e.g., "ats_classic", "modern").',
    )
    description = models.TextField(
        blank=True,
        help_text='Short description shown on the template marketplace.',
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='professional',
        help_text='Template category for filtering.',
    )
    preview_image = models.ImageField(
        upload_to='template_previews/',
        blank=True,
        help_text='Preview thumbnail shown in the template picker.',
    )
    is_premium = models.BooleanField(
        default=False,
        help_text='Premium templates require a paid plan with premium_templates enabled.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive templates are hidden from the marketplace.',
    )
    sort_order = models.IntegerField(
        default=0,
        help_text='Display order in the marketplace (lower = first).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'Resume Template'
        verbose_name_plural = 'Resume Templates'

    def __str__(self):
        premium_tag = ' [PREMIUM]' if self.is_premium else ''
        return f"{self.name}{premium_tag}"


# ── Conversational Resume Builder ────────────────────────────────────────────


class ResumeChat(models.Model):
    """
    Guided conversational session for building a resume from scratch.

    The user proceeds through a sequence of steps (contact → experience →
    education → skills → certifications → projects → review → done).
    Each step produces structured data that accumulates in ``resume_data``.

    The final ``resume_data`` JSON follows the same schema as
    ``GeneratedResume.resume_content`` so all existing template renderers
    work unchanged.
    """

    # ── Source (how the session was initialised) ─────────────────────────
    SOURCE_SCRATCH = 'scratch'
    SOURCE_PROFILE = 'profile'
    SOURCE_PREVIOUS = 'previous'
    SOURCE_CHOICES = [
        (SOURCE_SCRATCH, 'Start Fresh'),
        (SOURCE_PROFILE, 'From Profile Data'),
        (SOURCE_PREVIOUS, 'From Previous Resume'),
    ]

    # ── Wizard steps ────────────────────────────────────────────────────
    STEP_START = 'start'
    STEP_CONTACT = 'contact'
    STEP_TARGET_ROLE = 'target_role'
    STEP_EXPERIENCE_INPUT = 'experience_input'
    STEP_EXPERIENCE_REVIEW = 'experience_review'
    STEP_EDUCATION = 'education'
    STEP_SKILLS = 'skills'
    STEP_CERTIFICATIONS = 'certifications'
    STEP_PROJECTS = 'projects'
    STEP_REVIEW = 'review'
    STEP_DONE = 'done'
    STEP_CHOICES = [
        (STEP_START, 'Start'),
        (STEP_CONTACT, 'Contact Info'),
        (STEP_TARGET_ROLE, 'Target Role'),
        (STEP_EXPERIENCE_INPUT, 'Experience Input'),
        (STEP_EXPERIENCE_REVIEW, 'Experience Review'),
        (STEP_EDUCATION, 'Education'),
        (STEP_SKILLS, 'Skills'),
        (STEP_CERTIFICATIONS, 'Certifications'),
        (STEP_PROJECTS, 'Projects'),
        (STEP_REVIEW, 'Review & Polish'),
        (STEP_DONE, 'Done'),
    ]

    # Ordered list of steps for navigation
    STEP_ORDER = [
        STEP_START, STEP_CONTACT, STEP_TARGET_ROLE,
        STEP_EXPERIENCE_INPUT, STEP_EXPERIENCE_REVIEW,
        STEP_EDUCATION, STEP_SKILLS, STEP_CERTIFICATIONS,
        STEP_PROJECTS, STEP_REVIEW, STEP_DONE,
    ]

    # ── Status ──────────────────────────────────────────────────────────
    STATUS_ACTIVE = 'active'
    STATUS_COMPLETED = 'completed'
    STATUS_ABANDONED = 'abandoned'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_ABANDONED, 'Abandoned'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='resume_chats',
    )
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=SOURCE_SCRATCH,
    )

    # If source == 'previous', which resume was used as base
    base_resume = models.ForeignKey(
        Resume, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='builder_chats',
        help_text='Resume used as base data (for source=previous)',
    )

    # Progressive resume data — same schema as GeneratedResume.resume_content
    resume_data = models.JSONField(
        default=dict,
        help_text='Accumulated structured resume JSON (contact, experience, education, skills, etc.)',
    )

    # Target role context (optional, used for AI polish)
    target_role = models.CharField(max_length=255, blank=True)
    target_company = models.CharField(max_length=255, blank=True)
    target_industry = models.CharField(max_length=100, blank=True)
    experience_level = models.CharField(max_length=30, blank=True)

    # Step tracking
    current_step = models.CharField(
        max_length=30, choices=STEP_CHOICES, default=STEP_START,
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    # Final output link
    generated_resume = models.ForeignKey(
        GeneratedResume, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='builder_chat',
        help_text='Final generated resume file after finalize step',
    )

    credits_deducted = models.BooleanField(
        default=False,
        help_text='Whether credits were deducted for PDF/DOCX generation.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Resume Chat Session'
        verbose_name_plural = 'Resume Chat Sessions'
        indexes = [
            models.Index(fields=['user', '-updated_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        name = (self.resume_data or {}).get('contact', {}).get('name', 'Untitled')
        return f"ResumeChat {name} ({self.status}, step={self.current_step})"

    @property
    def step_number(self):
        """1-based index of current step in the wizard."""
        try:
            return self.STEP_ORDER.index(self.current_step) + 1
        except ValueError:
            return 0

    @property
    def total_steps(self):
        return len(self.STEP_ORDER)

    def advance_step(self):
        """Move to the next step in the wizard. Returns the new step name."""
        try:
            idx = self.STEP_ORDER.index(self.current_step)
        except ValueError:
            return self.current_step
        if idx + 1 < len(self.STEP_ORDER):
            self.current_step = self.STEP_ORDER[idx + 1]
        return self.current_step

    def go_back(self):
        """Move to the previous step. Returns the new step name."""
        try:
            idx = self.STEP_ORDER.index(self.current_step)
        except ValueError:
            return self.current_step
        if idx > 0:
            self.current_step = self.STEP_ORDER[idx - 1]
        return self.current_step


class ResumeChatMessage(models.Model):
    """
    Individual message in a resume chat session.

    Each assistant message includes a ``ui_spec`` JSON that tells the
    frontend what interactive component to render (buttons, chips,
    editable cards, etc.).
    """

    ROLE_USER = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_SYSTEM = 'system'
    ROLE_CHOICES = [
        (ROLE_USER, 'User'),
        (ROLE_ASSISTANT, 'Assistant'),
        (ROLE_SYSTEM, 'System'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(
        ResumeChat, on_delete=models.CASCADE, related_name='messages',
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField(
        blank=True,
        help_text='Display text for the message bubble',
    )
    ui_spec = models.JSONField(
        null=True, blank=True,
        help_text='Structured UI specification for the frontend to render (type, fields, actions, etc.)',
    )
    extracted_data = models.JSONField(
        null=True, blank=True,
        help_text='Partial resume_data extracted/updated in this turn',
    )
    step = models.CharField(
        max_length=30, blank=True,
        help_text='Which wizard step this message belongs to',
    )

    # Link to LLM response for cost tracking (only for assistant messages that used AI)
    llm_response = models.ForeignKey(
        LLMResponse, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chat_messages',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Resume Chat Message'
        verbose_name_plural = 'Resume Chat Messages'
        indexes = [
            models.Index(fields=['chat', 'created_at']),
        ]

    def __str__(self):
        preview = self.content[:50] if self.content else '(no text)'
        return f"[{self.role}] {preview}"


class UserActivity(models.Model):
    """
    Tracks one row per user per calendar day.
    Used to compute activity streaks and monthly action counts
    for the dashboard Activity Streak widget.

    A new row is upserted via ``UserActivity.record(user, action)``
    whenever the user performs a trackable action (analysis, resume gen,
    interview prep, cover letter, job alert run, builder finalize, login).
    """
    ACTION_ANALYSIS = 'analysis'
    ACTION_RESUME_GEN = 'resume_gen'
    ACTION_INTERVIEW_PREP = 'interview_prep'
    ACTION_COVER_LETTER = 'cover_letter'
    ACTION_JOB_ALERT_RUN = 'job_alert_run'
    ACTION_BUILDER_FINALIZE = 'builder_finalize'
    ACTION_LOGIN = 'login'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    date = models.DateField(
        help_text='Calendar date (UTC) of the activity.',
    )
    action_count = models.PositiveIntegerField(
        default=1,
        help_text='Total actions performed on this date.',
    )
    actions = models.JSONField(
        default=dict,
        help_text='Breakdown by action type, e.g. {"analysis": 2, "login": 1}.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'date')]
        ordering = ['-date']
        verbose_name = 'User Activity'
        verbose_name_plural = 'User Activities'
        indexes = [
            models.Index(fields=['user', '-date']),
        ]

    def __str__(self):
        return f"{self.user.username} — {self.date} ({self.action_count} actions)"

    @classmethod
    def record(cls, user, action: str):
        """
        Upsert today's activity row for the user.
        Increments global ``action_count`` and per-action counters.
        Thread-safe via ``update_or_create`` + F-expressions.
        """
        from django.db.models import F
        today = timezone.now().date()

        obj, created = cls.objects.get_or_create(
            user=user,
            date=today,
            defaults={'action_count': 1, 'actions': {action: 1}},
        )
        if not created:
            obj.action_count = F('action_count') + 1
            obj.save(update_fields=['action_count', 'updated_at'])
            # Refresh to get actual value, then update actions dict
            obj.refresh_from_db()
            actions = obj.actions or {}
            actions[action] = actions.get(action, 0) + 1
            obj.actions = actions
            obj.save(update_fields=['actions'])

    @classmethod
    def get_streak(cls, user):
        """
        Returns ``(streak_days, actions_this_month)`` for the user.

        streak_days: consecutive calendar days of activity ending today
                     (or yesterday if no activity yet today).
        actions_this_month: total action_count in the current calendar month.
        """
        today = timezone.now().date()
        first_of_month = today.replace(day=1)

        # Monthly total
        from django.db.models import Sum as _Sum
        monthly = cls.objects.filter(
            user=user,
            date__gte=first_of_month,
        ).aggregate(total=_Sum('action_count'))['total'] or 0

        # Streak — walk backwards from today
        dates = list(
            cls.objects.filter(user=user, date__lte=today)
            .order_by('-date')
            .values_list('date', flat=True)[:90]
        )
        if not dates:
            return 0, monthly

        streak = 0
        expected = today
        # If no activity today, start counting from yesterday
        if dates[0] != today:
            expected = today - timezone.timedelta(days=1)
            if not dates or dates[0] != expected:
                return 0, monthly

        for d in dates:
            if d == expected:
                streak += 1
                expected -= timezone.timedelta(days=1)
            else:
                break

        return streak, monthly
