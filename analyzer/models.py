import uuid

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


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
    def find_cached(cls, url: str, max_age_hours: int = 24):
        """Return a recent successful scrape for the same URL, or None."""
        cutoff = timezone.now() - timezone.timedelta(hours=max_age_hours)
        return (
            cls.objects
            .filter(source_url=url, status=cls.STATUS_DONE, created_at__gte=cutoff)
            .order_by('-created_at')
            .first()
        )


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
    resume_text = models.TextField(blank=True)

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
    ats_score = models.PositiveSmallIntegerField(null=True, blank=True)
    ats_score_breakdown = models.JSONField(null=True, blank=True)
    keyword_gaps = models.JSONField(null=True, blank=True)
    section_suggestions = models.JSONField(null=True, blank=True)
    rewritten_bullets = models.JSONField(null=True, blank=True)
    overall_assessment = models.TextField(blank=True)

    ai_provider_used = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} | ATS {self.ats_score} | {self.created_at:%Y-%m-%d}"
