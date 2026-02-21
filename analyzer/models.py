from django.db import models
from django.contrib.auth.models import User


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

    # Analysis results
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
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
