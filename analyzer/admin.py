from django.contrib import admin
from .models import ResumeAnalysis, Resume, ScrapeResult, LLMResponse, Job


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


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title', 'company', 'relevance', 'source', 'created_at')
    list_filter = ('relevance', 'source')
    search_fields = ('user__username', 'title', 'company', 'job_url')
    readonly_fields = ('id', 'created_at', 'updated_at')
