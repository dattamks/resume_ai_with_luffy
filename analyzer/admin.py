from django.contrib import admin
from .models import ResumeAnalysis, Resume, ScrapeResult, LLMResponse, GeneratedResume, ResumeVersion, InterviewPrep, CoverLetter, ResumeTemplate
from .models import Company, CompanyEntity, CompanyCareerPage


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
    readonly_fields = ('resume_text', 'resolved_jd', 'parsed_content', 'created_at', 'updated_at', 'deleted_at')
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


# ── Company Intelligence ──────────────────────────────────────────────────────


class CompanyEntityInline(admin.TabularInline):
    model = CompanyEntity
    extra = 0
    fields = ('display_name', 'legal_name', 'operating_country', 'operating_city', 'is_headquarters', 'is_indian_entity', 'website', 'is_active')
    readonly_fields = ('id',)


class CompanyCareerPageInline(admin.TabularInline):
    model = CompanyCareerPage
    extra = 0
    fields = ('url', 'label', 'country', 'crawl_frequency', 'is_active', 'last_crawled_at')
    readonly_fields = ('id', 'last_crawled_at')


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'industry', 'company_size', 'headquarters_country', 'headquarters_city', 'is_active', 'entity_count', 'updated_at')
    list_filter = ('is_active', 'company_size', 'industry')
    search_fields = ('name', 'slug')
    readonly_fields = ('id', 'created_at', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [CompanyEntityInline]
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'logo', 'industry', 'company_size', 'founded_year', 'is_active'),
        }),
        ('Headquarters', {
            'fields': ('headquarters_country', 'headquarters_city'),
        }),
        ('Links', {
            'fields': ('linkedin_url', 'glassdoor_url'),
        }),
        ('Technical', {
            'fields': ('tech_stack',),
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Entities')
    def entity_count(self, obj):
        return obj.entities.count()


@admin.register(CompanyEntity)
class CompanyEntityAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'company', 'operating_country', 'is_headquarters', 'is_indian_entity', 'is_active', 'career_page_count')
    list_filter = ('is_headquarters', 'is_indian_entity', 'is_active', 'operating_country')
    search_fields = ('display_name', 'legal_name', 'company__name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    raw_id_fields = ('company',)
    inlines = [CompanyCareerPageInline]

    @admin.display(description='Career Pages')
    def career_page_count(self, obj):
        return obj.career_pages.count()


@admin.register(CompanyCareerPage)
class CompanyCareerPageAdmin(admin.ModelAdmin):
    list_display = ('entity', 'label', 'url_short', 'country', 'crawl_frequency', 'is_active', 'last_crawled_at')
    list_filter = ('is_active', 'crawl_frequency', 'country')
    search_fields = ('entity__display_name', 'entity__company__name', 'url')
    readonly_fields = ('id', 'last_crawled_at', 'created_at', 'updated_at')
    raw_id_fields = ('entity',)

    @admin.display(description='URL')
    def url_short(self, obj):
        return obj.url[:80]


# ── Phase 11: Smart Job Alerts ────────────────────────────────────────────────

from .models import JobSearchProfile, JobAlert, DiscoveredJob, JobMatch, JobAlertRun, CrawlSource, RoleFamily  # noqa: E402


@admin.register(RoleFamily)
class RoleFamilyAdmin(admin.ModelAdmin):
    list_display = ('id', 'source_titles_short', 'related_count', 'generated_at', 'created_at')
    search_fields = ('source_titles', 'related_titles', 'titles_hash')
    readonly_fields = ('titles_hash', 'source_titles', 'related_titles', 'generated_at', 'created_at')
    list_per_page = 50

    @admin.display(description='Source Titles')
    def source_titles_short(self, obj):
        titles = obj.source_titles or []
        text = ', '.join(titles[:3])
        if len(titles) > 3:
            text += f' +{len(titles) - 3}'
        return text

    @admin.display(description='Related')
    def related_count(self, obj):
        return len(obj.related_titles or [])


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
    list_display = ('id', 'source', 'title', 'company', 'location', 'country', 'seniority_level', 'remote_policy', 'industry', 'posted_at', 'created_at')
    list_filter = ('source', 'country', 'seniority_level', 'employment_type', 'remote_policy', 'industry')
    search_fields = ('title', 'company', 'location', 'country', 'skills_required')
    readonly_fields = ('id', 'raw_data', 'created_at')
    raw_id_fields = ('company_entity',)
    list_per_page = 50
    fieldsets = (
        (None, {
            'fields': ('source', 'external_id', 'source_page_url', 'url', 'title', 'company', 'company_entity', 'location', 'country'),
        }),
        ('Enriched Data', {
            'fields': ('skills_required', 'skills_nice_to_have', 'experience_years_min', 'experience_years_max',
                       'employment_type', 'remote_policy', 'seniority_level', 'industry', 'education_required',
                       'salary_range', 'salary_min_usd', 'salary_max_usd'),
        }),
        ('Content', {
            'fields': ('description_snippet', 'raw_data'),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('id', 'posted_at', 'created_at'),
        }),
    )


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

from .models import SentAlert, Notification, UserCompanyFollow  # noqa: E402


@admin.register(SentAlert)
class SentAlertAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'discovered_job', 'channel', 'sent_at')
    list_filter = ('channel',)
    search_fields = ('user__username',)
    readonly_fields = ('id', 'sent_at')
    list_per_page = 50


@admin.register(UserCompanyFollow)
class UserCompanyFollowAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'company', 'relation', 'created_at')
    list_filter = ('relation',)
    search_fields = ('user__username', 'company__name')
    readonly_fields = ('id', 'created_at')
    raw_id_fields = ('user', 'company')
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


# ── Phase 15: Conversational Resume Builder ──────────────────────────────────

from .models import ResumeChat, ResumeChatMessage  # noqa: E402


@admin.register(ResumeChat)
class ResumeChatAdmin(admin.ModelAdmin):
    list_display = ('id_short', 'user', 'source', 'current_step', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'source', 'current_step')
    search_fields = ('user__username', 'id')
    readonly_fields = ('id', 'resume_data', 'created_at', 'updated_at')
    raw_id_fields = ('user', 'base_resume', 'generated_resume')
    list_per_page = 50

    @admin.display(description='ID')
    def id_short(self, obj):
        return str(obj.id)[:8]


@admin.register(ResumeChatMessage)
class ResumeChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'chat_short', 'role', 'step', 'created_at')
    list_filter = ('role', 'step')
    search_fields = ('chat__user__username',)
    readonly_fields = ('id', 'content', 'ui_spec', 'extracted_data', 'created_at')
    raw_id_fields = ('chat',)
    list_per_page = 50

    @admin.display(description='Chat')
    def chat_short(self, obj):
        return str(obj.chat_id)[:8]


# ── Phase 18: User Activity ─────────────────────────────────────────────────
from .models import UserActivity  # noqa: E402


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'action_count', 'actions', 'updated_at')
    list_filter = ('date',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('user', 'date', 'action_count', 'actions', 'created_at', 'updated_at')
    list_per_page = 50
    ordering = ('-date',)

