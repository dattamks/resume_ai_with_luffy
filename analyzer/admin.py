from django.contrib import admin
from .models import ResumeAnalysis, Resume, ScrapeResult, LLMResponse, GeneratedResume


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'original_filename', 'file_size_bytes', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('user__username', 'original_filename', 'file_hash')
    readonly_fields = ('id', 'file_hash', 'uploaded_at')


@admin.register(ResumeAnalysis)
class ResumeAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'jd_role', 'jd_company', 'status', 'overall_grade', 'ats_score', 'is_deleted', 'created_at')
    list_filter = ('status', 'jd_input_type', 'ai_provider_used', 'deleted_at')
    search_fields = ('user__username', 'jd_role', 'jd_company')
    readonly_fields = ('resume_text', 'resolved_jd', 'created_at', 'updated_at', 'deleted_at')

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
    list_display = ('id', 'user', 'model_used', 'status', 'duration_seconds', 'created_at')
    list_filter = ('status', 'model_used')
    search_fields = ('model_used',)


@admin.register(GeneratedResume)
class GeneratedResumeAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'analysis', 'template', 'format', 'status', 'created_at')
    list_filter = ('status', 'template', 'format')
    search_fields = ('user__username',)
    readonly_fields = ('id', 'resume_content', 'created_at')


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


@admin.register(DiscoveredJob)
class DiscoveredJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'source', 'title', 'company', 'location', 'posted_at', 'created_at')
    list_filter = ('source',)
    search_fields = ('title', 'company', 'location')
    readonly_fields = ('id', 'raw_data', 'created_at')


@admin.register(JobMatch)
class JobMatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'job_alert', 'discovered_job', 'relevance_score', 'user_feedback', 'created_at')
    list_filter = ('user_feedback',)
    search_fields = ('job_alert__user__username',)
    readonly_fields = ('id', 'created_at')


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

