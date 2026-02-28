from django.contrib import admin
from .models import ResumeAnalysis, Resume, ScrapeResult, LLMResponse, GeneratedResume, ResumeVersion, InterviewPrep, CoverLetter, ResumeTemplate


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'original_filename', 'file_size_bytes', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('user__username', 'original_filename', 'file_hash')
    readonly_fields = ('id', 'file_hash', 'uploaded_at')
    raw_id_fields = ('user',)


@admin.register(ResumeAnalysis)
class ResumeAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'jd_role', 'jd_company', 'status', 'overall_grade', 'ats_score', 'is_deleted', 'created_at')
    list_filter = ('status', 'jd_input_type', 'ai_provider_used', 'deleted_at')
    search_fields = ('user__username', 'jd_role', 'jd_company')
    readonly_fields = ('resume_text', 'resolved_jd', 'created_at', 'updated_at', 'deleted_at')
    raw_id_fields = ('user', 'resume')

    def get_queryset(self, request):
        """Show all analyses including soft-deleted in admin."""
        return ResumeAnalysis.all_objects.all()

    @admin.display(boolean=True, description='Deleted?')
    def is_deleted(self, obj):
        return obj.deleted_at is not None


@admin.register(ScrapeResult)
class ScrapeResultAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'source_url', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('source_url',)


@admin.register(LLMResponse)
class LLMResponseAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'model_used', 'call_purpose', 'status', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'estimated_cost_usd', 'duration_seconds', 'created_at')
    list_filter = ('status', 'model_used', 'call_purpose')
    search_fields = ('model_used', 'call_purpose')
    readonly_fields = ('id', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'estimated_cost_usd', 'created_at')


@admin.register(GeneratedResume)
class GeneratedResumeAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'analysis', 'template', 'format', 'status', 'created_at')
    list_filter = ('status', 'template', 'format')
    search_fields = ('user__username',)
    readonly_fields = ('id', 'resume_content', 'created_at')
    raw_id_fields = ('user', 'analysis')


# ── Phase 11: Smart Job Alerts ────────────────────────────────────────────────

from .models import JobSearchProfile, JobAlert, DiscoveredJob, JobMatch, JobAlertRun, CrawlSource  # noqa: E402


@admin.register(JobSearchProfile)
class JobSearchProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'resume', 'seniority', 'experience_years', 'updated_at')
    list_filter = ('seniority',)
    search_fields = ('resume__user__username', 'resume__original_filename')
    readonly_fields = ('resume', 'raw_extraction', 'created_at', 'updated_at')


@admin.register(JobAlert)
class JobAlertAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'resume', 'frequency', 'is_active', 'last_run_at', 'next_run_at', 'created_at')
    list_filter = ('frequency', 'is_active')
    search_fields = ('user__username',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    raw_id_fields = ('user', 'resume')


@admin.register(DiscoveredJob)
class DiscoveredJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'source', 'title', 'company', 'location', 'posted_at', 'created_at')
    list_filter = ('source',)
    search_fields = ('title', 'company', 'location')
    readonly_fields = ('id', 'raw_data', 'created_at')
    list_per_page = 50


@admin.register(JobMatch)
class JobMatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'job_alert', 'discovered_job', 'relevance_score', 'user_feedback', 'created_at')
    list_filter = ('user_feedback',)
    search_fields = ('job_alert__user__username',)
    readonly_fields = ('id', 'created_at')
    raw_id_fields = ('job_alert', 'discovered_job')


@admin.register(JobAlertRun)
class JobAlertRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'job_alert', 'jobs_discovered', 'jobs_matched', 'notification_sent', 'credits_used', 'duration_seconds', 'created_at')
    list_filter = ('notification_sent',)
    readonly_fields = ('id', 'created_at')


@admin.register(CrawlSource)
class CrawlSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'source_type', 'is_active', 'priority', 'last_crawled_at', 'created_at')
    list_filter = ('source_type', 'is_active')
    search_fields = ('name', 'url_template')
    readonly_fields = ('id', 'last_crawled_at', 'created_at', 'updated_at')
    ordering = ('priority', 'name')
    fieldsets = (
        (None, {
            'fields': ('name', 'source_type', 'url_template', 'is_active', 'priority'),
        }),
        ('Status', {
            'fields': ('last_crawled_at', 'created_at', 'updated_at'),
        }),
    )


# ── Phase 12: Notifications & Dedup ──────────────────────────────────────────

from .models import SentAlert, Notification  # noqa: E402


@admin.register(SentAlert)
class SentAlertAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'discovered_job', 'channel', 'sent_at')
    list_filter = ('channel',)
    search_fields = ('user__username',)
    readonly_fields = ('id', 'sent_at')
    list_per_page = 50


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title_short', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('user__username', 'title')
    readonly_fields = ('id', 'metadata', 'created_at')
    list_per_page = 50

    @admin.display(description='Title')
    def title_short(self, obj):
        return obj.title[:60]


# ── New Feature Models ───────────────────────────────────────────────────────


@admin.register(ResumeVersion)
class ResumeVersionAdmin(admin.ModelAdmin):
    list_display = ('id', 'resume', 'version_number', 'change_summary', 'created_at')
    list_filter = ('version_number',)
    search_fields = ('resume__user__username', 'resume__original_filename', 'change_summary')
    readonly_fields = ('id', 'created_at')
    raw_id_fields = ('resume', 'previous_resume')


@admin.register(InterviewPrep)
class InterviewPrepAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'analysis', 'status', 'credits_deducted', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__username',)
    readonly_fields = ('id', 'questions', 'tips', 'created_at')
    raw_id_fields = ('user', 'analysis', 'llm_response')


@admin.register(CoverLetter)
class CoverLetterAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'analysis', 'tone', 'status', 'credits_deducted', 'created_at')
    list_filter = ('status', 'tone')
    search_fields = ('user__username',)
    readonly_fields = ('id', 'content', 'content_html', 'created_at')
    raw_id_fields = ('user', 'analysis', 'llm_response')


# ── Phase 14: Resume Templates ──────────────────────────────────────────────────────


@admin.register(ResumeTemplate)
class ResumeTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'category', 'is_premium', 'is_active', 'sort_order', 'updated_at')
    list_filter = ('is_premium', 'is_active', 'category')
    list_editable = ('is_premium', 'is_active', 'sort_order')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('sort_order', 'name')

